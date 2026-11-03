from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QSizePolicy, QVBoxLayout, QWidget)

from .models import PRECISION_PROFILES, Precision
from .codex_runtime import find_codex
from .settings import DEFAULT_CODEX_MODEL, ProviderSettings, SettingsStore
from .solidworks_bridge import probe_solidworks
from .stl_viewer import StlView
from .task_engine import default_workspace, run_forward_rebuild, run_task

C = {"ink":"#142126", "panel":"#FFFFFF", "line":"#C8D2D0", "muted":"#53615F",
     "cyan":"#73F5DC", "cyan2":"#087F70", "orange":"#F15A29", "stage":"#10191D"}


def codex_status() -> tuple[str, str]:
    executable = find_codex()
    if not executable:
        return "missing", "未找到 Codex 运行时"
    try:
        result = subprocess.run([executable, "login", "status"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as exc:
        return "error", f"状态检查失败：{exc}"
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode == 0 and "logged in" in output.lower():
        source = "随软件运行时" if "codex-runtime" in executable.lower() else "本机 Codex"
        return "ready", f"{source}已登录（无需保持 Codex 窗口打开）"
    return "signed_out", output or "Codex 尚未登录"


class SettingsDialog(QDialog):
    status_ready = Signal(str, str)

    def __init__(self, store: SettingsStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("模型服务设置")
        self.setMinimumSize(650, 520)
        current = store.load()
        root = QVBoxLayout(self); root.setContentsMargins(38, 28, 38, 28)
        eye = QLabel("MODEL PROVIDER"); eye.setObjectName("eye")
        title = QLabel("模型服务设置"); title.setObjectName("dialogTitle")
        hint = QLabel("选择外接模型服务。Codex 登录与 API Key 是两条独立认证路径。"); hint.setObjectName("helpText")
        root.addWidget(eye); root.addWidget(title); root.addWidget(hint); root.addSpacing(14)
        form = QFormLayout(); form.setVerticalSpacing(11)
        self.provider = QComboBox()
        self.provider.addItems(("OpenAI 兼容接口", "OpenAI API", "Codex（ChatGPT 登录）", "DeepSeek", "本地模型"))
        providers = [self.provider.itemText(i) for i in range(self.provider.count())]
        self.provider.setCurrentText(current.provider if current.provider in providers else providers[0])
        self.url, self.key, self.model = QLineEdit(current.base_url), QLineEdit(current.api_key), QLineEdit(current.model)
        self.key.setEchoMode(QLineEdit.Password); self.key.setPlaceholderText("使用 Windows DPAPI 加密保存")
        form.addRow("服务商", self.provider); form.addRow("API 地址", self.url)
        form.addRow("API Key", self.key); form.addRow("模型名称", self.model); root.addLayout(form)
        self.codex_panel = QFrame(); self.codex_panel.setObjectName("codexPanel")
        cp = QVBoxLayout(self.codex_panel); cp.setContentsMargins(14, 12, 14, 12)
        line = QHBoxLayout(); self.codex_dot = QLabel("●"); self.codex_state = QLabel("正在检查…")
        self.codex_state.setObjectName("codexState"); line.addWidget(self.codex_dot); line.addWidget(self.codex_state, 1)
        self.check = QPushButton("重新检查"); self.check.clicked.connect(self.refresh_codex)
        self.login = QPushButton("登录 Codex"); self.login.setObjectName("primarySmall"); self.login.clicked.connect(self.start_login)
        line.addWidget(self.check); line.addWidget(self.login); cp.addLayout(line)
        note = QLabel("登录会打开 OpenAI 官方授权页面；软件不读取或保存你的 ChatGPT 密码。")
        note.setObjectName("helpText"); note.setWordWrap(True); cp.addWidget(note); root.addWidget(self.codex_panel)
        self.preview = QCheckBox("允许发送低分辨率预览图（默认仅发送测量摘要）")
        self.preview.setChecked(current.send_preview); root.addWidget(self.preview); root.addStretch()
        actions = QHBoxLayout(); actions.addStretch(); cancel = QPushButton("取消"); cancel.clicked.connect(self.reject)
        save = QPushButton("保存设置"); save.setObjectName("primarySmall"); save.clicked.connect(self.save)
        actions.addWidget(cancel); actions.addWidget(save); root.addLayout(actions)
        self.status_ready.connect(self.show_status)
        self.provider.currentTextChanged.connect(self.provider_changed)
        self.provider_changed(self.provider.currentText()); self.refresh_codex()

    def provider_changed(self, provider: str) -> None:
        is_codex = provider.startswith("Codex")
        self.codex_panel.setVisible(is_codex); self.url.setEnabled(not is_codex); self.key.setEnabled(not is_codex)
        if is_codex:
            self.url.clear(); self.key.clear()
            self.model.setText(DEFAULT_CODEX_MODEL); self.model.setEnabled(False)
        else:
            self.model.setEnabled(True)
            if not self.url.text().strip(): self.url.setText("https://api.openai.com/v1")

    def refresh_codex(self) -> None:
        self.codex_state.setText("正在检查…"); self.check.setEnabled(False)
        threading.Thread(target=lambda: self.status_ready.emit(*codex_status()), daemon=True).start()

    def show_status(self, state: str, message: str) -> None:
        colors = {"ready":"#087F70", "missing":"#B54708", "signed_out":"#B54708", "error":"#B42318"}
        self.codex_dot.setStyleSheet(f"color:{colors.get(state, '#53615F')}")
        self.codex_state.setText(message); self.check.setEnabled(True); self.login.setEnabled(state != "missing")
        self.login.setText("重新登录 Codex" if state == "ready" else "登录 Codex")

    def start_login(self) -> None:
        executable = find_codex()
        if not executable:
            QMessageBox.warning(self, "未安装 Codex", "未检测到 Codex CLI，请先安装后再登录。"); return
        try:
            subprocess.Popen([executable, "login"], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.codex_state.setText("已打开官方登录流程；完成后点击“重新检查”")
        except OSError as exc: QMessageBox.critical(self, "无法启动登录", str(exc))

    def save(self) -> None:
        self.store.save(ProviderSettings(self.provider.currentText(), self.url.text().strip(),
            self.model.text().strip(), self.key.text(), self.preview.isChecked())); self.accept()


class PrecisionCard(QFrame):
    def __init__(self, precision: Precision, checked=False):
        super().__init__(); self.setObjectName("precisionCard"); self.setProperty("selected", checked)
        self.setCursor(Qt.PointingHandCursor); profile = PRECISION_PROFILES[precision]
        row = QHBoxLayout(self); row.setContentsMargins(13, 9, 13, 9)
        self.radio = QRadioButton(); self.radio.setChecked(checked)
        title = QLabel(profile.label); title.setObjectName("cardTitle")
        desc = QLabel(profile.description); desc.setObjectName("cardDescription")
        row.addWidget(self.radio); row.addWidget(title); row.addWidget(desc, 1)
        self.radio.toggled.connect(self.select)

    def select(self, checked):
        self.setProperty("selected", checked); self.style().unpolish(self); self.style().polish(self)

    def mousePressEvent(self, event):
        self.radio.setChecked(True); super().mousePressEvent(event)


class TaskMessageDialog(QDialog):
    """Readable replacement for QMessageBox, including long CAD diagnostics."""
    def __init__(self, title: str, summary: str, detail: str, error: bool, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title); self.setModal(True); self.setMinimumSize(560, 330); self.resize(680, 410)
        root = QVBoxLayout(self); root.setContentsMargins(26, 22, 26, 22); root.setSpacing(12)
        heading = QLabel(summary); heading.setObjectName("errorTitle" if error else "successTitle"); heading.setWordWrap(True)
        explanation = QLabel("下面是可复制的详细信息，可据此定位问题。" if error else "任务产物已经写入指定目录。")
        explanation.setObjectName("helpText")
        details = QPlainTextEdit(); details.setReadOnly(True); details.setPlainText(detail or "未返回详细信息")
        details.setObjectName("taskDetails"); root.addWidget(heading); root.addWidget(explanation); root.addWidget(details, 1)
        actions = QHBoxLayout(); actions.addStretch(); close = QPushButton("关闭"); close.setObjectName("primarySmall"); close.clicked.connect(self.accept)
        actions.addWidget(close); root.addLayout(actions)


class Events(QObject):
    progress = Signal(int, str); done = Signal(object); failed = Signal(str); sw = Signal(bool, str)
    codex = Signal(str, str)
    cancelled = Signal(str)


class Window(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle("Ti5 Scan Rebuild"); self.resize(1440, 900); self.setMinimumSize(1120, 720)
        self.store, self.source, self.output_root, self.result = SettingsStore(), None, default_workspace(), None
        self.sw_ok, self.codex_ok, self.task_running = False, False, False
        self.events = Events(); self.events.progress.connect(self.on_progress); self.events.done.connect(self.on_done)
        self.events.failed.connect(self.on_failed); self.events.sw.connect(self.on_sw)
        self.events.codex.connect(self.on_codex)
        self.events.cancelled.connect(self.on_cancelled)
        self.cancel_event = threading.Event()
        central = QWidget(); root = QVBoxLayout(central); root.setContentsMargins(0,0,0,0); root.setSpacing(0)
        root.addWidget(self.topbar()); body = QHBoxLayout(); body.setContentsMargins(0,0,0,0); body.setSpacing(0)
        body.addWidget(self.controls()); body.addWidget(self.visual(), 1); holder = QWidget(); holder.setLayout(body)
        root.addWidget(holder, 1); self.setCentralWidget(central)
        self.refresh_environment()

    def topbar(self):
        bar = QFrame(); bar.setObjectName("topbar"); bar.setFixedHeight(68); row = QHBoxLayout(bar); row.setContentsMargins(24,0,24,0)
        mark = QLabel("Ti5"); mark.setObjectName("brandMark"); mark.setAlignment(Qt.AlignCenter); mark.setFixedSize(42,34)
        brand = QVBoxLayout(); brand.setSpacing(0); name = QLabel("SCAN REBUILD"); name.setObjectName("brandName")
        sub = QLabel("STL → 可审查的 SolidWorks 重建任务"); sub.setObjectName("small"); brand.addWidget(name); brand.addWidget(sub)
        self.sw = QLabel("●  正在检查 SolidWorks")
        self.codex = QLabel("●  正在检查 Codex")
        refresh = QPushButton("环境自检"); refresh.setObjectName("compactButton"); refresh.clicked.connect(self.refresh_environment)
        guide = QPushButton("使用说明"); guide.setObjectName("compactButton"); guide.clicked.connect(self.show_guide)
        settings = QPushButton("⚙  模型设置"); settings.clicked.connect(self.open_settings)
        row.addWidget(mark); row.addSpacing(12); row.addLayout(brand); row.addStretch(); row.addWidget(self.codex); row.addSpacing(12); row.addWidget(self.sw); row.addWidget(refresh); row.addWidget(guide); row.addSpacing(8); row.addWidget(settings)
        return bar

    def controls(self):
        panel = QFrame(); panel.setObjectName("controls"); panel.setFixedWidth(455)
        v = QVBoxLayout(panel); v.setContentsMargins(42,26,42,24); v.setSpacing(0)
        eye = QLabel("新建任务"); eye.setObjectName("eye"); title = QLabel("把扫描件重建为\n可编辑模型"); title.setObjectName("hero")
        intro = QLabel("选择 STL、检查真实网格并确认重建精度。"); intro.setObjectName("small")
        v.addWidget(eye); v.addSpacing(5); v.addWidget(title); v.addSpacing(6); v.addWidget(intro); v.addSpacing(18)
        v.addWidget(self.caption("扫描文件")); v.addSpacing(7)
        file_box = QPushButton(); file_box.setObjectName("fileBox"); file_box.setMinimumHeight(74); file_box.clicked.connect(self.choose)
        row = QHBoxLayout(file_box); row.setContentsMargins(12,10,12,10); badge = QLabel("STL"); badge.setObjectName("badge")
        badge.setAlignment(Qt.AlignCenter); badge.setFixedSize(48,48); copy = QVBoxLayout(); copy.setSpacing(2)
        self.file_name = QLabel("选择扫描文件"); self.file_name.setObjectName("fileName")
        self.file_meta = QLabel("支持二进制与 ASCII STL"); self.file_meta.setObjectName("fileMeta")
        copy.addWidget(self.file_name); copy.addWidget(self.file_meta); browse = QLabel("浏览"); browse.setObjectName("browse")
        row.addWidget(badge); row.addLayout(copy,1); row.addWidget(browse); v.addWidget(file_box)
        v.addSpacing(11); v.addWidget(self.caption("输出文件夹")); v.addSpacing(6)
        output = QPushButton(); output.setObjectName("outputBox"); output.setMinimumHeight(45); output.clicked.connect(self.choose_output)
        output_row = QHBoxLayout(output); output_row.setContentsMargins(12,6,12,6)
        self.output_label = QLabel(str(self.output_root)); self.output_label.setObjectName("outputPath"); self.output_label.setToolTip(str(self.output_root))
        self.output_label.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        output_row.addWidget(QLabel("▣")); output_row.addWidget(self.output_label,1); output_row.addWidget(QLabel("选择")); v.addWidget(output)
        v.addSpacing(11); v.addWidget(self.caption("重建精度")); v.addSpacing(6); self.cards = {}
        for precision in Precision:
            card = PrecisionCard(precision, precision == Precision.MEDIUM); card.radio.toggled.connect(lambda checked,p=precision:self.pick(p,checked))
            self.cards[precision] = card; v.addWidget(card); v.addSpacing(6)
        unit_row = QHBoxLayout(); unit_row.setSpacing(12)
        unit_label = self.caption("STL 单位"); unit_label.setObjectName("formLabel"); unit_label.setFixedWidth(64); unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.units = QComboBox(); self.units.setObjectName("formCombo"); self.units.setFixedHeight(40); self.units.addItems(("mm", "cm", "m", "inch"))
        unit_row.addWidget(unit_label); unit_row.addWidget(self.units, 1); v.addLayout(unit_row); v.addSpacing(9)
        engine_row = QHBoxLayout(); engine_row.setSpacing(12)
        engine_label = self.caption("重建引擎"); engine_label.setObjectName("formLabel"); engine_label.setFixedWidth(64); engine_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.engine = QComboBox(); self.engine.setObjectName("formCombo"); self.engine.setFixedHeight(40); self.engine.addItems(("Codex 正向重建（推荐）", "本地网格实体化（备用）")); self.engine.currentIndexChanged.connect(self.environment_changed)
        engine_row.addWidget(engine_label); engine_row.addWidget(self.engine, 1); v.addLayout(engine_row); v.addSpacing(9)
        self.reference = QCheckBox("生成 SolidWorks 输出和四视图审查（需先启动 SolidWorks）"); self.reference.setChecked(True); v.addWidget(self.reference)
        self.reference.toggled.connect(self.environment_changed)
        self.model_info = QLabel("正在执行环境自检…"); self.model_info.setObjectName("preflightInfo"); self.model_info.setWordWrap(True); v.addSpacing(6); v.addWidget(self.model_info); v.addSpacing(10)
        self.start = QPushButton("开始对齐并正向重建  →"); self.start.setObjectName("primary"); self.start.setEnabled(False); self.start.clicked.connect(self.start_task)
        self.stop = QPushButton("停止当前任务"); self.stop.setObjectName("stopButton"); self.stop.setEnabled(False); self.stop.clicked.connect(self.stop_task)
        v.addWidget(self.start); v.addSpacing(7); v.addWidget(self.stop); v.addStretch(); return panel

    def visual(self):
        panel = QFrame(); panel.setObjectName("visual"); v = QVBoxLayout(panel); v.setContentsMargins(0,0,0,0); v.setSpacing(0)
        toolbar = QFrame(); toolbar.setObjectName("toolbar"); toolbar.setFixedHeight(56); tr = QHBoxLayout(toolbar); tr.setContentsMargins(22,0,18,0)
        label = QLabel("●  SCAN WORKSPACE  /  REAL MESH PREVIEW"); label.setObjectName("toolbarText")
        reset = QPushButton("重置视图"); reset.setObjectName("viewportButton"); tr.addWidget(label); tr.addStretch(); tr.addWidget(reset)
        self.canvas = StlView(); reset.clicked.connect(self.canvas.reset_view)
        status = QFrame(); status.setObjectName("status"); status.setFixedHeight(126); sv = QVBoxLayout(status); sv.setContentsMargins(24,12,24,12)
        top = QHBoxLayout(); self.progress_label = QLabel("等待添加扫描文件"); self.progress_label.setObjectName("statusText")
        self.progress_percent = QLabel("0%"); self.progress_percent.setObjectName("statusPercent")
        top.addWidget(self.progress_label); top.addStretch(); top.addWidget(self.progress_percent)
        self.progress = QProgressBar(); self.progress.setRange(0,100); self.progress.setTextVisible(False)
        stages = QHBoxLayout(); self.stage_labels = []
        for text in ("读取网格","分析几何","生成计划","SolidWorks","输出报告"):
            item=QLabel(text); item.setObjectName("stagePending"); self.stage_labels.append(item); stages.addWidget(item)
        stages.addStretch(); self.open_btn=QPushButton("打开任务目录"); self.open_btn.setObjectName("open"); self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self.open_output); stages.addWidget(self.open_btn)
        sv.addLayout(top); sv.addWidget(self.progress); sv.addLayout(stages); v.addWidget(toolbar); v.addWidget(self.canvas,1); v.addWidget(status); return panel

    @staticmethod
    def caption(text): label=QLabel(text); label.setObjectName("caption"); return label
    @staticmethod
    def model_summary(settings):
        return "模型引擎：Codex（使用 ChatGPT 登录）" if settings.provider.startswith("Codex") else f"模型引擎：{settings.model or '未配置'} · 原始 STL 默认不上传"
    def pick(self,p,checked):
        if checked:
            for key,card in self.cards.items():
                if key != p: card.radio.setChecked(False)
    def precision(self): return next((p for p,c in self.cards.items() if c.radio.isChecked()),Precision.MEDIUM)
    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,"选择扫描 STL","","STL 网格 (*.stl)")
        if path:
            self.source=Path(path); self.file_name.setText(self.source.name); self.file_meta.setText(f"{self.source.stat().st_size/1048576:.1f} MB · 正在载入真实网格")
            self.canvas.load_stl(self.source); self.progress_label.setText("文件已就绪，可旋转、缩放和平移检查"); self.update_start_enabled()
    def choose_output(self):
        path=QFileDialog.getExistingDirectory(self,"选择输出文件夹",str(self.output_root))
        if path: self.output_root=Path(path); self.output_label.setText(path); self.output_label.setToolTip(path); self.progress_label.setText("输出文件夹已更新")
    def open_settings(self):
        if SettingsDialog(self.store,self).exec(): self.refresh_environment()
    def refresh_environment(self):
        if hasattr(self, "sw"):
            self.sw.setText("●  正在检查 SolidWorks"); self.codex.setText("●  正在检查 Codex")
        self.sw_ok = False; self.codex_ok = False; self.update_start_enabled()
        threading.Thread(target=lambda:self.events.sw.emit(*probe_solidworks()),daemon=True).start()
        threading.Thread(target=lambda:self.events.codex.emit(*codex_status()),daemon=True).start()
    def refresh_solidworks(self):
        self.refresh_environment()
    def on_sw(self,ok,msg):
        self.sw_ok = ok; self.sw.setText(f"●  {msg}"); self.sw.setStyleSheet(f"color:{'#087F70' if ok else '#B54708'}"); self.update_start_enabled()
    def on_codex(self,state,msg):
        self.codex_ok = state == "ready"; self.codex.setText(f"●  {msg}"); self.codex.setStyleSheet(f"color:{'#087F70' if self.codex_ok else '#B54708'}"); self.update_start_enabled()
    def environment_changed(self, *_args):
        self.update_start_enabled()
    def update_start_enabled(self):
        if not hasattr(self, "start"): return
        forward = self.engine.currentIndex() == 0
        requirements = [(self.sw_ok, "SolidWorks 已连接")]
        if forward: requirements.insert(0, (self.codex_ok, "Codex 已安装并登录"))
        ready = (not self.task_running) and self.source is not None and all(ok for ok, _ in requirements)
        self.start.setEnabled(ready)
        status = [f"{'✓' if ok else '○'} {label}" for ok, label in requirements]
        status.append("✓ 已选择 STL" if self.source else "○ 请选择 STL")
        engine = "Codex 正向重建 · 使用用户的 ChatGPT 登录" if forward else "本地网格实体化 · 不调用大模型"
        self.model_info.setText(engine + "\n" + "   ".join(status))
        self.model_info.setStyleSheet(f"color:{'#087F70' if ready else '#8A4B08'}")
    def show_guide(self):
        detail = ("1. 安装并启动 SolidWorks，等待主界面加载完成。\n"
                  "2. Codex 只需安装并登录，不要求窗口保持打开。\n"
                  "3. 点击“环境自检”，确认 Codex 与 SolidWorks 均为绿色。\n"
                  "4. 选择 STL、输出文件夹、单位和重建精度。\n"
                  "5. 使用“Codex 正向重建”输出可编辑 SLDPRT 与 STEP。\n"
                  "6. 处理中不要关闭本软件或 SolidWorks；完成后打开任务目录检查四视图和报告。\n\n"
                  "注意：重建结果是工程设计参考，制造前必须复核尺寸、公差、材料与工艺。")
        TaskMessageDialog("使用说明", "钛虎扫描件参数化重建助手", detail, False, self).exec()
    def start_task(self):
        if not self.source:return
        if self.engine.currentIndex() == 0 and not self.codex_ok:
            TaskMessageDialog("环境未就绪", "Codex 尚未安装或登录", "请打开“模型设置”完成 ChatGPT 登录，然后点击“环境自检”。Codex 窗口不需要保持打开。", True, self).exec(); return
        if not self.sw_ok:
            TaskMessageDialog("环境未就绪", "SolidWorks 尚未连接", "请启动 SolidWorks，等待主界面加载完成，然后点击“环境自检”。", True, self).exec(); return
        self._task_precision = self.precision(); self._task_create_solid = self.reference.isChecked(); self._task_units = self.units.currentText(); self._task_engine = self.engine.currentIndex(); self._task_settings = self.store.load()
        self.cancel_event = threading.Event(); self.task_running = True
        self.start.setEnabled(False); self.start.setText("正在执行…"); self.stop.setEnabled(True); self.open_btn.setEnabled(False); self.on_progress(1,"正在准备任务")
        threading.Thread(target=self.worker,daemon=True).start()
    def stop_task(self):
        if not self.stop.isEnabled(): return
        self.cancel_event.set(); self.stop.setEnabled(False); self.stop.setText("正在停止…")
        self.progress_label.setText("正在停止当前任务并保留已生成文件…")
    def worker(self):
        try:
            progress=lambda n,s:self.events.progress.emit(n,s)
            if self._task_engine == 0:
                model=DEFAULT_CODEX_MODEL if self._task_settings.provider.startswith("Codex") else ""
                result=run_forward_rebuild(self.source,self._task_precision,self.output_root,self._task_units,model,progress,self.cancel_event)
            else:
                result=run_task(self.source,self._task_precision,self.output_root,self._task_create_solid,self._task_units,progress,self.cancel_event)
            self.events.done.emit(result)
        except InterruptedError as exc:self.events.cancelled.emit(str(exc))
        except Exception as exc:self.events.failed.emit(str(exc))
    def on_progress(self,value,message):
        self.progress.setValue(value); self.progress_percent.setText(f"{value}%"); self.progress_label.setText(message); thresholds=(8,34,52,88,100)
        for index,label in enumerate(self.stage_labels):
            name="stageDone" if value>=thresholds[index] else "stageActive" if index==0 or value>=thresholds[index-1] else "stagePending"
            label.setObjectName(name); label.style().unpolish(label); label.style().polish(label)
    def on_done(self,result):
        self.result=result; self.task_running=False; self.stop.setEnabled(False); self.stop.setText("停止当前任务"); self.start.setText("再次执行  →"); self.open_btn.setEnabled(True); self.update_start_enabled()
        if result.warnings:
            self.on_progress(100,"SLDPRT 与 STEP 已生成；部分工程门禁需人工复核")
            self.stage_labels[3].setObjectName("stageWarning"); self.stage_labels[3].style().unpolish(self.stage_labels[3]); self.stage_labels[3].style().polish(self.stage_labels[3])
            detail=("\n\n".join(result.warnings)+
                    f"\n\n任务目录：{result.task_dir}"
                    f"\nSolidWorks：{result.output_sldprt or '未生成'}"
                    f"\nSTEP：{result.output_step or '未生成'}")
            TaskMessageDialog("任务需复核", "模型文件已生成，但尚未通过全部自动验收", detail, True, self).exec()
        else:
            self.on_progress(100,"任务完成：SLDPRT、STEP 和审查证据已生成")
            detail=f"任务目录：{result.task_dir}\nSolidWorks：{result.output_sldprt or '未生成'}\nSTEP：{result.output_step or '本模式未生成'}"
            TaskMessageDialog("任务完成", "正向重建交付已生成并验证", detail, False, self).exec()
    def on_failed(self,msg):
        detail=(msg or "").strip() or "程序没有返回错误文本，请检查运行日志。"
        self.task_running=False; self.stop.setEnabled(False); self.stop.setText("停止当前任务"); self.start.setText("重试  →"); self.update_start_enabled(); self.progress_label.setText(f"任务失败：{detail.splitlines()[-1][:80]}"); self.progress_percent.setText("失败")
        TaskMessageDialog("任务失败", "任务未能完成", detail, True, self).exec()
    def on_cancelled(self,msg):
        self.task_running=False; self.stop.setEnabled(False); self.stop.setText("停止当前任务"); self.start.setText("重新执行  →"); self.update_start_enabled()
        self.progress_label.setText("任务已停止；已生成文件已保留"); self.progress_percent.setText("已停止")
        TaskMessageDialog("任务已停止", "已停止当前重建任务", msg + "\n\n请检查 SolidWorks 中是否留有本轮临时文档；确认无用后可手动关闭。", False, self).exec()
    def open_output(self):
        if self.result:os.startfile(self.result.task_dir)


STYLE=f"""
*{{font-family:'Microsoft YaHei UI';color:{C['ink']};font-size:12px}} QWidget{{background:#F2F4F3}} QLabel{{background:transparent}}
#topbar{{background:white;border-bottom:1px solid {C['line']}}} #brandMark{{background:{C['ink']};color:{C['cyan']};border-radius:8px;font:bold 17px 'Bahnschrift'}}
#brandName{{font:bold 17px 'Bahnschrift'}} #small,#helpText{{color:{C['muted']};font-size:11px}}
QPushButton{{border:1px solid {C['line']};background:white;padding:8px 12px;border-radius:7px}} QPushButton:hover{{border-color:{C['cyan2']};background:#F1FBF9}}
#controls{{background:white;border-right:1px solid {C['line']}}} #eye{{color:{C['orange']};font:bold 10px 'Bahnschrift';letter-spacing:2px}}
#hero{{font:bold 29px 'Microsoft YaHei UI'}} #dialogTitle{{font:bold 24px 'Microsoft YaHei UI'}} #caption{{color:#354542;font-size:11px;font-weight:bold}}
#fileBox{{text-align:left;background:#F7F9F8;border:1px dashed #879894;padding:0}} #fileBox:hover{{background:#EFFAF8;border-color:{C['cyan2']}}}
#badge{{background:{C['ink']};color:{C['cyan']};border-radius:6px;font:bold 10px 'Bahnschrift'}} #cardTitle,#fileName{{font-size:12px;font-weight:bold}}
#fileMeta,#cardDescription{{color:{C['muted']};font-size:10px}} #browse{{color:{C['cyan2']};font-size:11px;font-weight:bold}}
#outputBox{{text-align:left;background:#F7F9F8;border:1px solid {C['line']};padding:0}} #outputPath{{color:#354542;font-size:10px}}
#precisionCard{{background:#F8FAF9;border:1px solid #AAB8B5;border-radius:8px}} #precisionCard:hover{{border:1px solid {C['cyan2']};background:#F1FBF9}}
#precisionCard[selected="true"]{{background:#DDF8F2;border:2px solid #087F70}} #precisionCard[selected="true"] #cardTitle{{color:#075E54}}
QRadioButton::indicator{{width:17px;height:17px;border-radius:9px;border:2px solid #657572;background:white}} QRadioButton::indicator:checked{{border:5px solid #087F70;background:{C['cyan']}}}
#targetBadge{{background:#E3EBE9;color:#354542;border-radius:8px;padding:3px 7px;font-size:10px;font-weight:bold}} #precisionCard[selected="true"] #targetBadge{{background:#087F70;color:white}}
#primary{{background:{C['ink']};color:white;border:0;padding:14px;font-weight:bold}} #primary:disabled{{background:#AAB4B2;color:#EEF1F0}} #primarySmall{{background:{C['ink']};color:white;font-weight:bold}}
#stopButton{{background:white;color:#B42318;border:1px solid #D92D20;padding:10px;font-weight:bold}} #stopButton:hover{{background:#FFF1F0;border-color:#B42318}} #stopButton:disabled{{color:#98A2A0;border-color:#C8D2D0;background:#F5F7F6}}
#visual,#toolbar{{background:{C['stage']}}} #toolbar{{border-bottom:1px solid #314248}} #toolbarText{{color:#AFC2BD;font:bold 10px 'Bahnschrift';letter-spacing:1px}}
#viewportButton{{background:#1C2A2F;border:1px solid #3D5257;color:#D8E5E2;padding:6px 10px}} #status{{background:#121D21;border-top:1px solid #314248}}
#statusText{{color:#F2F7F5;font-size:12px;font-weight:bold}} #statusPercent{{color:{C['cyan']};font:bold 17px 'Bahnschrift'}}
QProgressBar{{background:#2A393E;border:0;height:9px;border-radius:4px}} QProgressBar::chunk{{background:{C['cyan']};border-radius:4px}}
#stagePending{{color:#70827D;font-size:10px}} #stageActive{{color:{C['cyan']};font-size:10px;font-weight:bold}} #stageDone{{color:#D4E0DD;font-size:10px}} #stageWarning{{color:#FFB36B;font-size:10px;font-weight:bold}}
#open{{background:transparent;border:1px solid #46615C;color:{C['cyan']};padding:5px 9px}} #open:disabled{{color:#667773;border-color:#344641}}
#compactButton{{padding:5px 8px;font-size:10px}}
#preflightInfo{{background:#FFF8E8;border:1px solid #E7C783;border-radius:6px;padding:8px;color:#8A4B08;font-size:10px}}
QDialog{{background:white}} QLineEdit,QComboBox{{background:#F8FAF9;border:1px solid #AAB8B5;border-radius:6px;padding:9px;color:#142126}}
QLineEdit:focus,QComboBox:focus{{border:2px solid {C['cyan2']}}} #codexPanel{{background:#F2F8F6;border:1px solid #B7CBC6;border-radius:8px}} #codexState{{font-weight:bold;color:#354542}}
#formLabel{{color:#354542;font-size:11px;font-weight:bold;padding:0}}
#formCombo{{background:#F8FAF9;border:1px solid #AAB8B5;border-radius:6px;padding:0 38px 0 12px;color:#142126;font-size:11px}}
#formCombo:hover{{border-color:#6F8580;background:#F3F8F6}} #formCombo:focus{{border:2px solid {C['cyan2']};padding-left:11px}}
#formCombo::drop-down{{subcontrol-origin:padding;subcontrol-position:top right;width:32px;border-left:1px solid #D5DEDC;background:#EEF3F1;border-top-right-radius:5px;border-bottom-right-radius:5px}}
#errorTitle{{color:#B42318;font-size:18px;font-weight:bold}} #successTitle{{color:#087F70;font-size:18px;font-weight:bold}}
#taskDetails{{background:#F6F8F7;border:1px solid #B9C5C2;border-radius:7px;padding:10px;color:#243330;font-family:'Cascadia Mono';font-size:11px}}
"""

def run():
    app=QApplication(sys.argv); app.setApplicationName("Ti5 Scan Rebuild"); app.setStyleSheet(STYLE); window=Window(); window.show(); raise SystemExit(app.exec())
