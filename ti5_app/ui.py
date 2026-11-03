from __future__ import annotations

import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import PRECISION_PROFILES, Precision
from .settings import ProviderSettings, SettingsStore
from .solidworks_bridge import probe_solidworks
from .task_engine import default_workspace, run_task


COLORS = {
    "paper": "#F2F4F3",
    "panel": "#FBFCFB",
    "ink": "#172024",
    "muted": "#667176",
    "line": "#D7DDDA",
    "cyan": "#59E0DC",
    "cyan_dark": "#147B79",
    "orange": "#F36A2E",
    "stage": "#11191D",
}


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, store: SettingsStore, on_saved) -> None:
        super().__init__(parent)
        self.store = store
        self.on_saved = on_saved
        current = store.load()
        self.title("模型服务设置")
        self.geometry("500x430")
        self.resizable(False, False)
        self.configure(bg=COLORS["panel"])
        self.transient(parent)
        self.grab_set()

        body = tk.Frame(self, bg=COLORS["panel"], padx=30, pady=26)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="MODEL PROVIDER", bg=COLORS["panel"], fg=COLORS["orange"], font=("Segoe UI", 8, "bold")).pack(anchor="w")
        tk.Label(body, text="模型服务设置", bg=COLORS["panel"], fg=COLORS["ink"], font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w", pady=(3, 20))

        self.provider = tk.StringVar(value=current.provider)
        self.base_url = tk.StringVar(value=current.base_url)
        self.api_key = tk.StringVar(value=current.api_key)
        self.model = tk.StringVar(value=current.model)
        self.send_preview = tk.BooleanVar(value=current.send_preview)
        self._field(body, "服务商", self.provider, values=("OpenAI 兼容接口", "OpenAI", "Anthropic", "DeepSeek", "本地模型"))
        self._field(body, "API 地址", self.base_url)
        self._field(body, "API Key", self.api_key, secret=True)
        self._field(body, "模型名称", self.model)
        tk.Checkbutton(body, text="允许发送低分辨率预览图（默认仅发送测量摘要）", variable=self.send_preview, bg=COLORS["panel"], fg=COLORS["muted"], activebackground=COLORS["panel"], font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(4, 16))
        buttons = tk.Frame(body, bg=COLORS["panel"])
        buttons.pack(fill="x")
        tk.Button(buttons, text="取消", command=self.destroy, relief="flat", padx=18, pady=8).pack(side="right")
        tk.Button(buttons, text="保存设置", command=self._save, bg=COLORS["ink"], fg="white", activebackground="#26363c", activeforeground="white", relief="flat", padx=18, pady=8).pack(side="right", padx=8)

    def _field(self, parent, label, variable, values=None, secret=False):
        tk.Label(parent, text=label, bg=COLORS["panel"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        if values:
            widget = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        else:
            widget = ttk.Entry(parent, textvariable=variable, show="•" if secret else "")
        widget.pack(fill="x", ipady=6, pady=(5, 12))

    def _save(self):
        self.store.save(ProviderSettings(self.provider.get(), self.base_url.get().strip(), self.model.get().strip(), self.api_key.get(), self.send_preview.get()))
        self.on_saved()
        self.destroy()


class Ti5App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Ti5 Scan Rebuild · 钛虎扫描件参数化重建助手")
        self.geometry("1180x760")
        self.minsize(1040, 700)
        self.configure(bg=COLORS["paper"])
        self.source_path: Path | None = None
        self.last_result = None
        self.events: queue.Queue = queue.Queue()
        self.store = SettingsStore()
        self.precision = tk.StringVar(value=Precision.MEDIUM.value)
        self.create_reference = tk.BooleanVar(value=True)
        self._build_styles()
        self._build_ui()
        self.after(100, self._poll_events)
        threading.Thread(target=self._probe_sw, daemon=True).start()

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Ti5.Horizontal.TProgressbar", troughcolor="#263236", background=COLORS["cyan"], borderwidth=0, thickness=8)

    def _build_ui(self):
        top = tk.Frame(self, height=76, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1)
        top.pack(fill="x")
        top.pack_propagate(False)
        mark = tk.Frame(top, width=45, height=45, bg=COLORS["ink"])
        mark.pack(side="left", padx=(28, 12), pady=15)
        mark.pack_propagate(False)
        tk.Label(mark, text="Ti⁵", bg=COLORS["ink"], fg=COLORS["cyan"], font=("Bahnschrift", 15, "bold")).pack(expand=True)
        brand = tk.Frame(top, bg=COLORS["panel"])
        brand.pack(side="left")
        tk.Label(brand, text="Ti5 Scan Rebuild", bg=COLORS["panel"], fg=COLORS["ink"], font=("Bahnschrift", 15, "bold")).pack(anchor="w")
        tk.Label(brand, text="钛虎扫描件参数化重建助手", bg=COLORS["panel"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 8)).pack(anchor="w")
        tk.Button(top, text="⚙  模型设置", command=self._open_settings, relief="flat", bg=COLORS["panel"], fg=COLORS["ink"], padx=12, pady=8).pack(side="right", padx=24)
        self.sw_label = tk.Label(top, text="●  正在检测 SolidWorks", bg=COLORS["panel"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 9))
        self.sw_label.pack(side="right")

        main = tk.PanedWindow(self, orient="horizontal", sashwidth=1, bd=0, bg=COLORS["line"])
        main.pack(fill="both", expand=True)
        left = tk.Frame(main, bg=COLORS["panel"], padx=54, pady=38)
        right = tk.Frame(main, bg=COLORS["stage"])
        main.add(left, minsize=455, width=500)
        main.add(right, minsize=520)

        tk.Label(left, text="新建任务", bg=COLORS["panel"], fg=COLORS["orange"], font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
        tk.Label(left, text="把扫描件重建为\n可编辑模型", justify="left", bg=COLORS["panel"], fg=COLORS["ink"], font=("Microsoft YaHei UI", 26, "bold")).pack(anchor="w", pady=(8, 8))
        tk.Label(left, text="选择 STL，确认精度，其余步骤由 Ti5 在本机执行。", bg=COLORS["panel"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 24))

        self._caption(left, "扫描文件")
        file_box = tk.Frame(left, bg="#F7F9F8", highlightbackground="#ADB9B7", highlightthickness=1, padx=14, pady=12, cursor="hand2")
        file_box.pack(fill="x", ipady=4)
        file_box.bind("<Button-1>", lambda event: self._choose_file())
        badge = tk.Label(file_box, text="STL", width=5, height=2, bg=COLORS["ink"], fg=COLORS["cyan"], font=("Bahnschrift", 9, "bold"))
        badge.pack(side="left", padx=(0, 12))
        badge.bind("<Button-1>", lambda event: self._choose_file())
        copy = tk.Frame(file_box, bg="#F7F9F8")
        copy.pack(side="left", fill="x", expand=True)
        self.file_name = tk.Label(copy, text="选择扫描文件", anchor="w", bg="#F7F9F8", fg=COLORS["ink"], font=("Microsoft YaHei UI", 9, "bold"))
        self.file_name.pack(fill="x")
        self.file_meta = tk.Label(copy, text="支持二进制与 ASCII STL", anchor="w", bg="#F7F9F8", fg=COLORS["muted"], font=("Microsoft YaHei UI", 8))
        self.file_meta.pack(fill="x", pady=(4, 0))
        tk.Button(file_box, text="浏览", command=self._choose_file, relief="flat", bg="#F7F9F8", fg=COLORS["cyan_dark"]).pack(side="right")

        self._caption(left, "重建精度", top=22)
        for value in Precision:
            profile = PRECISION_PROFILES[value]
            row = tk.Frame(left, bg=COLORS["panel"], highlightbackground=COLORS["line"], highlightthickness=1, padx=10, pady=8)
            row.pack(fill="x", pady=3)
            tk.Radiobutton(row, variable=self.precision, value=value.value, bg=COLORS["panel"], activebackground=COLORS["panel"], selectcolor=COLORS["cyan"], command=self._update_precision).pack(side="left")
            text = tk.Frame(row, bg=COLORS["panel"])
            text.pack(side="left", fill="x", expand=True)
            tk.Label(text, text=profile.label, bg=COLORS["panel"], fg=COLORS["ink"], font=("Microsoft YaHei UI", 9, "bold")).pack(anchor="w")
            tk.Label(text, text=profile.description, bg=COLORS["panel"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 8)).pack(anchor="w")
            tk.Label(row, text=f"目标 {profile.target_deviation_mm:g} mm", bg=COLORS["panel"], fg=COLORS["muted"], font=("Segoe UI", 8)).pack(side="right")

        tk.Checkbutton(left, text="同时生成 SolidWorks 网格参考件和四视图审查", variable=self.create_reference, bg=COLORS["panel"], fg=COLORS["muted"], activebackground=COLORS["panel"], font=("Microsoft YaHei UI", 8)).pack(anchor="w", pady=(15, 6))
        settings = self.store.load()
        self.model_info = tk.Label(left, text=f"模型引擎：{settings.model or '未配置'} · 原始 STL 不上传", bg=COLORS["panel"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 8))
        self.model_info.pack(anchor="w", pady=(0, 12))
        self.start_button = tk.Button(left, text="开始分析与重建   →", state="disabled", command=self._start, bg=COLORS["ink"], disabledforeground="#EEF2F1", fg="white", activebackground="#26363C", activeforeground="white", relief="flat", pady=13, font=("Microsoft YaHei UI", 10, "bold"))
        self.start_button.pack(fill="x")

        tk.Label(right, text="  SCAN WORKSPACE", bg=COLORS["stage"], fg="#91A09C", font=("Bahnschrift", 9, "bold"), anchor="w", padx=20).pack(fill="x", ipady=18)
        stage = tk.Canvas(right, bg=COLORS["stage"], highlightthickness=0)
        stage.pack(fill="both", expand=True)
        self.canvas = stage
        stage.bind("<Configure>", self._draw_stage)
        bottom = tk.Frame(right, bg="#151F23", height=100)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)
        self.progress_label = tk.Label(bottom, text="等待添加扫描件", bg="#151F23", fg="#C8D2CF", font=("Microsoft YaHei UI", 9))
        self.progress_label.pack(anchor="w", padx=24, pady=(15, 8))
        self.progress = ttk.Progressbar(bottom, style="Ti5.Horizontal.TProgressbar", maximum=100)
        self.progress.pack(fill="x", padx=24)
        self.output_button = tk.Button(bottom, text="打开任务目录", state="disabled", command=self._open_output, relief="flat", bg="#151F23", fg=COLORS["cyan"], disabledforeground="#56615E")
        self.output_button.pack(anchor="e", padx=20, pady=5)

    def _caption(self, parent, text, top=0):
        tk.Label(parent, text=text, bg=COLORS["panel"], fg="#4F5A5E", font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w", pady=(top, 8))

    def _draw_stage(self, event=None):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 1), max(c.winfo_height(), 1)
        for x in range(0, w, 38): c.create_line(x, 0, x, h, fill="#1C292D")
        for y in range(0, h, 38): c.create_line(0, y, w, y, fill="#1C292D")
        if not self.source_path:
            c.create_text(w/2, h/2-45, text="01", fill="#1B4245", font=("Bahnschrift", 70, "bold"))
            c.create_text(w/2, h/2+8, text="添加扫描件开始", fill="#E5ECEA", font=("Microsoft YaHei UI", 13, "bold"))
            c.create_text(w/2, h/2+36, text="这里将显示网格检查和重建状态", fill="#74817E", font=("Microsoft YaHei UI", 9))
        else:
            cx, cy = w/2, h/2
            for i, color in enumerate((COLORS["cyan"], "#338B8A", "#275A5D")):
                pad = 50 + i * 28
                c.create_oval(cx-170+pad, cy-120+pad/2, cx+170-pad, cy+120-pad/2, outline=color, width=1)
            c.create_line(cx-220, cy, cx+220, cy, fill=COLORS["orange"], width=2)
            c.create_text(24, h-24, text=self.source_path.name.upper(), fill="#6B7C78", anchor="w", font=("Cascadia Mono", 8))

    def _choose_file(self):
        value = filedialog.askopenfilename(title="选择扫描 STL", filetypes=(("STL 网格", "*.stl"),))
        if not value: return
        self.source_path = Path(value)
        size = self.source_path.stat().st_size / 1024 / 1024
        self.file_name.config(text=self.source_path.name)
        self.file_meta.config(text=f"{size:.1f} MB · 等待网格检查")
        self.start_button.config(state="normal")
        self.progress_label.config(text="文件已就绪")
        self._draw_stage()

    def _update_precision(self):
        profile = PRECISION_PROFILES[Precision(self.precision.get())]
        self.progress_label.config(text=f"已选择{profile.label}模式 · 目标抽样偏差 {profile.target_deviation_mm:g} mm")

    def _open_settings(self):
        SettingsDialog(self, self.store, self._refresh_settings)

    def _refresh_settings(self):
        settings = self.store.load()
        self.model_info.config(text=f"模型引擎：{settings.model or '未配置'} · 原始 STL 不上传")

    def _probe_sw(self):
        ok, message = probe_solidworks()
        self.events.put(("sw", ok, message))

    def _start(self):
        if not self.source_path: return
        self.start_button.config(state="disabled", text="正在执行…")
        self.output_button.config(state="disabled")
        self.progress["value"] = 0
        precision = Precision(self.precision.get())
        threading.Thread(target=self._worker, args=(precision,), daemon=True).start()

    def _worker(self, precision):
        try:
            result = run_task(self.source_path, precision, default_workspace(), self.create_reference.get(), lambda value, message: self.events.put(("progress", value, message)))
            self.events.put(("done", result))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "sw":
                    self.sw_label.config(text=f"●  {event[2]}", fg="#238661" if event[1] else COLORS["orange"])
                elif event[0] == "progress":
                    self.progress["value"] = event[1]
                    self.progress_label.config(text=event[2])
                elif event[0] == "done":
                    self.last_result = event[1]
                    self.start_button.config(state="normal", text="再次执行   →")
                    self.output_button.config(state="normal")
                    messagebox.showinfo("任务完成", f"分析和任务报告已生成。\n\n{self.last_result.task_dir}")
                elif event[0] == "error":
                    self.start_button.config(state="normal", text="重试   →")
                    self.progress_label.config(text="任务失败")
                    messagebox.showerror("任务失败", event[1])
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _open_output(self):
        if self.last_result:
            os.startfile(self.last_result.task_dir)


def run():
    Ti5App().mainloop()

