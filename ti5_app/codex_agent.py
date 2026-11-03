from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import re
from pathlib import Path
from typing import Any, Callable

from .codex_runtime import resolve_codex
from .models import PRECISION_PROFILES, Precision
from .settings import DEFAULT_CODEX_MODEL, DEFAULT_CODEX_REASONING


Progress = Callable[[int, str], None]

RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["completed", "review_required", "failed"]},
        "summary": {"type": "string"},
        "sldprt_path": {"type": "string"},
        "step_path": {"type": "string"},
        "alignment_manifest_path": {"type": "string"},
        "review_report_path": {"type": "string"},
        "solid_body_count": {"type": "integer", "minimum": 0},
        "feature_count": {"type": "integer", "minimum": 0},
        "quality_metrics": {
            "type": "object",
            "properties": {
                "measurement_method": {"type": "string"},
                "rms_deviation_mm": {"type": "number", "minimum": 0},
                "p95_deviation_mm": {"type": "number", "minimum": 0},
                "max_deviation_mm": {"type": "number", "minimum": 0},
                "surface_coverage_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                "detected_feature_count": {"type": "integer", "minimum": 0},
                "reconstructed_feature_count": {"type": "integer", "minimum": 0},
                "feature_coverage_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                "refinement_iterations": {"type": "integer", "minimum": 0},
                "region_results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "region_name": {"type": "string"},
                            "status": {"type": "string", "enum": ["passed", "failed", "not_applicable"]},
                            "rms_deviation_mm": {"type": "number", "minimum": 0},
                            "p95_deviation_mm": {"type": "number", "minimum": 0},
                            "surface_coverage_ratio": {"type": "number", "minimum": 0, "maximum": 1},
                            "detected_feature_count": {"type": "integer", "minimum": 0},
                            "reconstructed_feature_count": {"type": "integer", "minimum": 0},
                            "evidence": {"type": "string"},
                        },
                        "required": ["region_name", "status", "rms_deviation_mm", "p95_deviation_mm",
                                     "surface_coverage_ratio", "detected_feature_count",
                                     "reconstructed_feature_count", "evidence"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["measurement_method", "rms_deviation_mm", "p95_deviation_mm", "max_deviation_mm",
                         "surface_coverage_ratio", "detected_feature_count", "reconstructed_feature_count",
                         "feature_coverage_ratio", "refinement_iterations", "region_results"],
            "additionalProperties": False,
        },
        "engineering_checks": {
            "type": "object",
            "properties": {
                "functional_datum_aligned": {"type": "boolean"},
                "single_solid_body": {"type": "boolean"},
                "all_production_sketches_fully_defined": {"type": "boolean"},
                "fix_relations_absent": {"type": "boolean"},
                "native_reopen_passed": {"type": "boolean"},
                "dimension_roundtrip_passed": {"type": "boolean"},
                "step_reimport_solid_count": {"type": "integer", "minimum": 0},
                "step_max_extreme_delta_mm": {"type": "number", "minimum": 0},
                "visual_review_passed": {"type": "boolean"},
                "section_review_passed": {"type": "boolean"},
                "required_features": {"type": "array", "items": {"type": "string"}},
                "simplified_features": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["functional_datum_aligned", "single_solid_body",
                         "all_production_sketches_fully_defined", "fix_relations_absent",
                         "native_reopen_passed", "dimension_roundtrip_passed",
                         "step_reimport_solid_count", "step_max_extreme_delta_mm",
                         "visual_review_passed", "section_review_passed",
                         "required_features", "simplified_features"],
            "additionalProperties": False,
        },
        "evidence": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status", "summary", "sldprt_path", "step_path", "alignment_manifest_path",
        "review_report_path", "solid_body_count", "feature_count", "quality_metrics",
        "engineering_checks", "evidence", "limitations",
    ],
    "additionalProperties": False,
}


def _resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def resolve_skill_dir() -> Path:
    candidates = [
        _resource_root() / "resources" / "solidworks-automation-skill",
        Path(__file__).resolve().parents[1] / "resources" / "solidworks-automation-skill",
        Path.home() / ".codex" / "skills" / "solidworks-automation-skill",
    ]
    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            return candidate.resolve()
    raise FileNotFoundError("软件内未找到 SolidWorks 自动化技能包，请重新安装完整发布包。")


def _prompt(source: Path, task_dir: Path, skill_dir: Path, precision: str, units: str) -> str:
    profile = PRECISION_PROFILES[Precision(precision)]
    regions = "、".join(profile.required_regions)
    return f"""你正在执行 Ti5 扫描件正向重建任务。必须真实操作本机 SolidWorks，不得把 STL 网格导入件、图形体或三角面实体化冒充正向重建。

输入 STL（只读，禁止覆盖）：{source}
任务输出目录（所有新文件必须放在这里）：{task_dir}
SolidWorks 自动化技能：{skill_dir / 'SKILL.md'}
重建等级：{precision}
STL 单位：{units}

本档按昨日已验证的“可编辑正向设计参考”标准验收，不把扫描噪声、磨损和允许简化的小孔细筋当作制造级全表面拟合：
- 截面数：至少 {profile.section_count} 组；扫描到 CAD 的 RMS/P95/覆盖率必须真实测量并报告，但仅作诊断，不单独决定交付失败。
- 必须恢复功能基准、核心外轮廓/外曲面、主要接口与大孔槽；小孔、细筋、噪声和不确定内部结构可简化，但必须列入 simplified_features。
- 最终必须为单一实体 Body，生产草图完全定义且无 Fix，修改→重建→恢复、原生重开、STEP 重导入均通过。
- STEP 必须重导为一个实体，原生/STEP 用 IBody2.GetExtremePoint 比较六方向极值，最大差异不得超过 0.02 mm。
- 检测到的功能特征复刻率 ≥ {profile.min_feature_coverage:.0%}；四视图和扫描/CAD 截面需要真实复核。
- 正向特征数不少于 {profile.min_native_features}，且至少完成 {profile.min_refinement_iterations} 轮“建模→偏差检查→补特征/调参”。
- 必须分区检查：{regions}。如扫描中不存在某区域，在 region_results 中记录 not_applicable 和证据，不得直接忽略。

先完整读取上述 SKILL.md，并按技能的能力门禁、自检、COM 串行、单位和结果审查规则执行。参照已经验证的历史流程完成：
1. 分析扫描网格，识别功能安装面、主圆/孔轴、对称关系和主要截面；不要只按包围盒居中。
2. 计算旋转和平移，把功能基准摆正，保存 aligned_reference.stl 与 alignment_manifest.json；清单必须包含 4x4 变换、基准定义、源文件 SHA-256 和回转误差证据。
3. 基于对齐参考正向建模。创建新的 SolidWorks 零件，用有尺寸和关系的草图及拉伸、旋转、切除、放样等真实特征重建主要外形与接口。扫描噪声、小缺口和不确定细节可工程化简化，但必须写入 limitations。
4. 保存 editable_rebuild.SLDPRT。它必须至少包含一个实体 Body 和一个正向建模特征；禁止以 Imported、Mesh、Graphics Body 作为唯一主体后宣称完成。
5. 对关键尺寸执行一次“修改→重建→恢复”验证；检查草图约束、特征错误、保存重开和实体数量。
   - 每个生产草图必须用尺寸与几何关系完全定义，禁止用 Fix 批量锁定；使用技能中的 fully_define_sketch/inspect_model_sketches 或等价的可靠回读验收。
   - SolidWorks IModelDoc2.ForceRebuild3(False) 返回 True 表示本次强制重建成功；不要对成功值取反。除返回值外，还要回读尺寸和包围盒，证明修改后变化、恢复后回到原值。
6. 导出 editable_rebuild.STEP，重新导入并验证至少一个实体 Body；比较原生模型与 STEP 的六方向极值尺寸。
   - STEP/STP/IGES 是外来 CAD 文件，禁止用 OpenDoc6 回导。必须复用技能 scripts/sw_connect.py 的 open_document()，或严格使用 GetImportFileData + LoadFile4(path, "r", import_data, byref_errors)。
   - 回导后核对错误码、实体数量和包围盒；关闭文档时只关闭本轮明确打开的路径，避免同名文档冲突。
7. 生成正视、俯视、右视、等轴测预览，并进行扫描/重建分区偏差复核。写 review_report.json，其中必须包含与最终 quality_metrics 完全一致的测量结果。

重建质量要求：medium/fine 不得用分层拉伸阶梯冒充连续外曲面。自由曲面优先使用多截面 Loft/Boundary/Knit/Thicken 或等价的连续参数化路线。

这是持续执行任务。只要还能在当前任务目录和同一 SLDPRT 上安全改进，就必须继续诊断、修正和复核，不要为了尽快返回 JSON 而提前停止。禁止每轮丢弃已有模型重新粗建。

这是非交互任务。缺少制造尺寸时可做明确记录的设计参考假设，不要停下来提问；但不得虚构精度或制造公差。只有 SLDPRT、STEP、alignment_manifest.json、review_report.json 全部落盘且验收通过，status 才能为 completed。任何门禁未通过时返回 review_required 或 failed，并保留证据与限制。
最终响应严格符合提供的 JSON Schema，路径使用绝对路径。
"""


def _apply_precision_gate(result: dict[str, Any], precision: str) -> list[str]:
    """Independently enforce the selected quality profile on structured measurements."""
    profile = PRECISION_PROFILES[Precision(precision)]
    metrics = result.get("quality_metrics") or {}
    checks = result.get("engineering_checks") or {}
    failures: list[str] = []
    requirements = (
        (bool(checks.get("functional_datum_aligned")), "功能基准未验证对齐"),
        (bool(checks.get("single_solid_body")) and int(result.get("solid_body_count", 0)) == 1, "未合并为单一实体"),
        (bool(checks.get("all_production_sketches_fully_defined")), "生产草图未全部完全定义"),
        (bool(checks.get("fix_relations_absent")), "草图中仍存在 Fix 关系"),
        (bool(checks.get("native_reopen_passed")), "原生 SLDPRT 重开验证未通过"),
        (bool(checks.get("dimension_roundtrip_passed")), "关键尺寸修改→重建→恢复未通过"),
        (int(checks.get("step_reimport_solid_count", 0)) == 1, "STEP 重导入不是一个实体"),
        (float(checks.get("step_max_extreme_delta_mm", float("inf"))) <= 0.02, "STEP 六方向极值差超过 0.02 mm"),
        (bool(checks.get("visual_review_passed")), "四视图复核未通过"),
        (bool(checks.get("section_review_passed")), "扫描/CAD 截面复核未通过"),
        (float(metrics.get("feature_coverage_ratio", -1)) >= profile.min_feature_coverage,
         f"特征复刻率 {metrics.get('feature_coverage_ratio', '缺失')} < {profile.min_feature_coverage:.0%}"),
        (int(result.get("feature_count", 0)) >= profile.min_native_features,
         f"正向特征 {result.get('feature_count', 0)} < {profile.min_native_features}"),
        (int(metrics.get("refinement_iterations", 0)) >= profile.min_refinement_iterations,
         f"偏差迭代 {metrics.get('refinement_iterations', 0)} < {profile.min_refinement_iterations}"),
    )
    failures.extend(message for passed, message in requirements if not passed)
    if len(metrics.get("region_results") or []) < len(profile.required_regions):
        failures.append(f"分区检查记录不完整，需要 {len(profile.required_regions)} 项")
    if failures:
        result["status"] = "review_required"
        result["limitations"] = list(result.get("limitations") or []) + [
            f"未达到{profile.label}精度硬门禁：" + "；".join(failures)
        ]
    result["precision_gate"] = {"passed": not failures, "profile": precision, "failures": failures}
    return failures


def _resolve_output(raw: str, task_dir: Path, suffixes: tuple[str, ...], label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = task_dir / path
    path = path.resolve()
    try:
        path.relative_to(task_dir.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Codex 返回的{label}不在任务目录内：{path}") from exc
    if path.suffix.lower() not in suffixes or not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"Codex 返回的{label}无效或未落盘：{path}")
    return path


def _run_codex_process(command: list[str], prompt: str, task_dir: Path, log_path: Path,
                       started: float, timeout_seconds: int, cancel_event: Any | None,
                       notify: Progress, pass_index: int) -> None:
    with log_path.open("a", encoding="utf-8", errors="replace") as log:
        log.write(f"\n===== TI5 AGENT PASS {pass_index} =====\n")
        process = subprocess.Popen(
            command, cwd=task_dir, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert process.stdin is not None
        process.stdin.write(prompt); process.stdin.close()
        last_notice = 0
        while process.poll() is None:
            if cancel_event is not None and cancel_event.is_set():
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                else:
                    process.terminate()
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired: process.kill()
                raise InterruptedError(f"任务已由用户停止。已生成的文件保留在：{task_dir}")
            elapsed = int(time.monotonic() - started)
            if elapsed > timeout_seconds:
                process.terminate()
                raise TimeoutError(f"Codex 正向重建超过 {timeout_seconds // 60} 分钟，已终止。日志：{log_path}")
            if elapsed - last_notice >= 20:
                notify(min(88, 38 + elapsed // 90), f"Astra 第 {pass_index} 轮正向建模中，已运行 {elapsed // 60} 分钟")
                last_notice = elapsed
            time.sleep(1)
    if process.returncode != 0:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
        raise RuntimeError(f"Codex 正向重建失败（退出码 {process.returncode}）。\n{tail}")


def _read_and_gate_result(answer_path: Path, task_dir: Path, precision: str) -> tuple[dict[str, Any], list[str]]:
    if not answer_path.is_file():
        raise RuntimeError(f"Codex 未生成结构化结果：{answer_path}")
    result = json.loads(answer_path.read_text(encoding="utf-8"))
    if result.get("status") not in {"completed", "review_required", "failed"}:
        raise RuntimeError(f"Codex 返回了未知任务状态：{result.get('status')}")
    if int(result.get("solid_body_count", 0)) < 1 or int(result.get("feature_count", 0)) < 1:
        return result, ["尚未生成可验收的实体 Body 和正向特征"]
    for key, suffixes, label in (
        ("sldprt_path", (".sldprt",), "SLDPRT"), ("step_path", (".step", ".stp"), "STEP"),
        ("alignment_manifest_path", (".json",), "对齐清单"), ("review_report_path", (".json",), "审查报告")):
        result[key] = str(_resolve_output(result[key], task_dir, suffixes, label))
    return result, _apply_precision_gate(result, precision)


def run_codex_rebuild(
    source: Path,
    task_dir: Path,
    precision: str,
    units: str,
    model: str = "",
    progress: Progress | None = None,
    cancel_event: Any | None = None,
    timeout_seconds: int = 3 * 60 * 60,
) -> dict[str, Any]:
    notify = progress or (lambda _value, _message: None)
    codex = resolve_codex()
    skill_dir = resolve_skill_dir()
    schema_path = task_dir / "codex_result_schema.json"
    answer_path = task_dir / "codex_result.json"
    log_path = task_dir / "codex_execution.log"
    schema_path.write_text(json.dumps(RESULT_SCHEMA, ensure_ascii=False, indent=2), encoding="utf-8")
    chosen_model = DEFAULT_CODEX_MODEL
    command = [
        codex, "exec", "-C", str(task_dir), "--skip-git-repo-check",
        "--sandbox", "danger-full-access", "-c", 'approval_policy="never"',
        "-c", f'model_reasoning_effort="{DEFAULT_CODEX_REASONING}"',
        "--model", chosen_model, "--output-schema", str(schema_path),
        "--output-last-message", str(task_dir / "codex_result_pass_1.json"), "-",
    ]
    notify(38, "GPT-6 Astra 正在分析基准并规划正向重建")
    started = time.monotonic()
    log_path.write_text("", encoding="utf-8")
    profile = PRECISION_PROFILES[Precision(precision)]
    max_passes = {"simple": 2, "medium": 3, "fine": 4}[precision]
    result: dict[str, Any] = {}
    failures: list[str] = []
    session_id = ""
    for pass_index in range(1, max_passes + 1):
        pass_answer = task_dir / f"codex_result_pass_{pass_index}.json"
        if pass_index == 1:
            pass_command = command
            prompt = _prompt(source, task_dir, skill_dir, precision, units)
        else:
            pass_command = [codex, "exec", "resume", "--model", chosen_model,
                "-c", f'model_reasoning_effort="{DEFAULT_CODEX_REASONING}"',
                "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check",
                "--output-schema", str(schema_path), "--output-last-message", str(pass_answer), session_id, "-"]
            prompt = ("继续同一 Ti5 重建任务。不得丢弃或从头粗建；必须打开并修改当前 editable_rebuild.SLDPRT 及已有脚本。\n"
                      f"上一轮工程门禁未通过：{'；'.join(failures)}\n"
                      "先用扫描/CAD截面和四视图定位误差，再修正参数化特征。多实体必须合并；阶梯曲面必须替换为连续 Loft/Boundary/Knit/Thicken 路线。"
                      "重新执行修改恢复、重开、STEP LoadFile4 重导和 IBody2.GetExtremePoint 六方向验证。"
                      "只要仍可安全改进就继续执行，完成后再输出严格 JSON。")
        _run_codex_process(pass_command, prompt, task_dir, log_path, started, timeout_seconds,
                           cancel_event, notify, pass_index)
        if pass_index == 1:
            match = re.search(r"session id:\s*([0-9a-f-]{36})", log_path.read_text(encoding="utf-8", errors="replace"), re.I)
            if not match: raise RuntimeError("无法取得 Codex 任务 session id，不能执行自动返工。")
            session_id = match.group(1)
        result, failures = _read_and_gate_result(pass_answer, task_dir, precision)
        result["agent_passes"] = pass_index
        answer_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        if not failures and result.get("status") != "failed": break
        if pass_index < max_passes:
            notify(min(90, 55 + pass_index * 10), f"第 {pass_index} 轮未达昨日交付标准，Astra 正在继续修改同一模型")
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    answer_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    notify(88, "Codex 正向重建通过，正在整理交付" if result["status"] == "completed" else "产物已生成，所选精度存在需复核项")
    return result
