from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

from .models import PRECISION_PROFILES, Precision, ReconstructionPlan, TaskResult
from .codex_agent import run_codex_rebuild
from .solidworks_bridge import import_reference
from .stl_analyzer import analyze_stl


Progress = Callable[[int, str], None]


def default_workspace() -> Path:
    base = Path(os.getenv("USERPROFILE", Path.home())) / "Documents" / "Ti5 Scan Rebuild"
    base.mkdir(parents=True, exist_ok=True)
    return base


def build_plan(source: Path, precision: Precision) -> ReconstructionPlan:
    profile = PRECISION_PROFILES[precision]
    stages = [
        {"id": "mesh_check", "label": "检查网格与尺度", "status": "completed"},
        {"id": "datum", "label": "识别主方向和候选基准", "status": "planned"},
        {"id": "sections", "label": f"提取 {profile.section_count} 组候选截面", "status": "planned"},
        {"id": "features", "label": "识别平面、圆柱和主要孔槽", "status": "planned"},
        {"id": "native", "label": "生成 SolidWorks 参数特征", "status": "review_required"},
        {"id": "verify", "label": "重开、四视图和偏差验证", "status": "planned"},
    ]
    return ReconstructionPlan(
        precision=precision.value,
        source=str(source),
        target_deviation_mm=profile.target_deviation_mm,
        sections=profile.section_count,
        max_p95_deviation_mm=profile.max_p95_deviation_mm,
        min_surface_coverage=profile.min_surface_coverage,
        min_feature_coverage=profile.min_feature_coverage,
        min_native_features=profile.min_native_features,
        min_refinement_iterations=profile.min_refinement_iterations,
        required_regions=list(profile.required_regions),
        stages=stages,
        limitations=[
            "扫描网格不包含原始设计意图、公差或特征历史。",
            "当前通用版本生成参考 SLDPRT；参数化特征重建需匹配零件类型模板并人工复核。",
            "输出不得未经工程复核直接用于制造。",
        ],
    )


def run_forward_rebuild(
    source: str | Path,
    precision: Precision,
    output_root: str | Path | None = None,
    units: str = "mm",
    model: str = "",
    progress: Progress | None = None,
    cancel_event=None,
) -> TaskResult:
    """Run the proven align -> forward model -> STEP -> review Codex workflow."""
    notify = progress or (lambda value, message: None)
    source_path = Path(source).resolve()
    root = (Path(output_root) if output_root else default_workspace()).expanduser().resolve()
    task_dir = root / f"{source_path.stem}_FORWARD_{datetime.now():%Y%m%d_%H%M%S_%f}"
    task_dir.mkdir(parents=True, exist_ok=False)

    notify(8, "检查 STL 文件和网格质量")
    analysis = analyze_stl(source_path, precision)
    analysis_path = task_dir / "mesh_analysis.json"
    analysis_path.write_text(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    notify(22, "建立正向重建任务和验收门禁")
    plan = build_plan(source_path, precision)
    plan_path = task_dir / "reconstruction_plan.json"
    plan_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError(f"任务已由用户停止。任务目录：{task_dir}")
    agent = run_codex_rebuild(source_path, task_dir, precision.value, units, model, notify, cancel_event)
    output_sldprt = Path(agent["sldprt_path"])
    output_step = Path(agent["step_path"])
    evidence = "\n".join(f"- {item}" for item in agent.get("evidence", [])) or "- 已通过结构化交付门禁"
    limitations = "\n".join(f"- {item}" for item in agent.get("limitations", [])) or "- 无额外限制记录"
    metrics = agent.get("quality_metrics") or {}
    gate = agent.get("precision_gate") or {}
    gate_failures = "\n".join(f"- {item}" for item in gate.get("failures", [])) or "- 全部硬门禁通过"
    report_path = task_dir / "task_report.md"
    report_path.write_text(
        f"""# Ti5 Codex 正向重建任务报告

## 输入

- STL：`{source_path}`
- SHA-256：`{analysis.sha256}`
- 单位：{units}
- 重建等级：{PRECISION_PROFILES[precision].label}

## 正向重建交付

- SolidWorks：`{output_sldprt}`
- STEP：`{output_step}`
- 实体 Body：{agent['solid_body_count']}
- 正向特征：{agent['feature_count']}
- 对齐清单：`{agent['alignment_manifest_path']}`
- 审查报告：`{agent['review_report_path']}`

## 所选精度门禁

- RMS 偏差：{metrics.get('rms_deviation_mm', '未记录')} mm
- P95 偏差：{metrics.get('p95_deviation_mm', '未记录')} mm
- 表面覆盖率：{metrics.get('surface_coverage_ratio', '未记录')}
- 特征复刻率：{metrics.get('feature_coverage_ratio', '未记录')}
- 偏差迭代：{metrics.get('refinement_iterations', '未记录')}

{gate_failures}

## 验收证据

{evidence}

## 工程限制

{limitations}

该结果是基于扫描件的正向设计参考。扫描数据不包含原始设计意图、公差和全部不可见结构，制造前仍需工程师确认。
""",
        encoding="utf-8",
    )
    review_required = agent.get("status") == "review_required"
    warnings = []
    if review_required:
        gate_reason = "；".join(gate.get("failures", []))
        warnings.append(
            "SLDPRT 与 STEP 已生成，但未完全达到所选精度或其他门禁需要人工复核。\n"
            f"精度门禁：{gate_reason or '未报告数值失败'}\n"
            f"任务摘要：{agent.get('summary', '请查看 review_report.json')}\n"
            "产物没有被删除，可在任务目录中继续检查和编辑。"
        )
        notify(100, "产物已生成：部分门禁需人工复核")
    else:
        notify(100, "正向重建完成：SLDPRT 与 STEP 已通过门禁")
    return TaskResult(
        task_dir=task_dir, analysis_path=analysis_path, plan_path=plan_path,
        report_path=report_path, output_sldprt=output_sldprt, output_step=output_step,
        warnings=warnings,
    )


def run_task(
    source: str | Path,
    precision: Precision,
    output_root: str | Path | None = None,
    create_reference_sldprt: bool = False,
    units: str = "mm",
    progress: Progress | None = None,
    cancel_event=None,
) -> TaskResult:
    notify = progress or (lambda value, message: None)
    source_path = Path(source).resolve()
    root = (Path(output_root) if output_root else default_workspace()).expanduser().resolve()
    task_name = f"{source_path.stem}_{datetime.now():%Y%m%d_%H%M%S_%f}"
    task_dir = root / task_name
    task_dir.mkdir(parents=True, exist_ok=False)
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError(f"任务已由用户停止。任务目录：{task_dir}")

    notify(8, "检查 STL 文件")
    analysis = analyze_stl(source_path, precision)
    analysis_path = task_dir / "mesh_analysis.json"
    analysis_path.write_text(json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    notify(34, "生成重建计划")
    plan = build_plan(source_path, precision)
    plan_path = task_dir / "reconstruction_plan.json"
    plan_path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    output_sldprt = None
    sw_result = None
    task_warnings: list[str] = []
    if create_reference_sldprt:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError(f"任务已由用户停止。任务目录：{task_dir}")
        notify(52, "重建 SolidWorks 可编辑实体")
        output_sldprt = task_dir / f"{source_path.stem}_SOLID.SLDPRT"
        try:
            sw_result = import_reference(source_path, output_sldprt, task_dir / "review", units)
        except Exception as exc:
            output_sldprt = None
            detail = str(exc).strip() or type(exc).__name__
            task_warnings.append(f"SolidWorks 可编辑实体未生成：{detail}")
            sw_result = {"status": "failed", "error": detail}
        (task_dir / "solidworks_import.json").write_text(
            json.dumps(sw_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    notify(88, "生成任务报告")
    warning_lines = "\n".join(f"- {item}" for item in analysis.warnings) or "- 未发现明显网格警告"
    solidworks_lines = "\n".join(f"- {item}" for item in task_warnings) or (
        "- 已生成并验证 SolidWorks 实体 Body。" if create_reference_sldprt else "- 本次未请求 SolidWorks 实体。"
    )
    report = f"""# Ti5 扫描件重建任务报告

## 输入

- 文件：`{source_path}`
- STL 单位：{units}
- SHA-256：`{analysis.sha256}`
- STL 格式：{analysis.format}
- 三角面：{analysis.triangle_count:,}
- 包围尺寸：{analysis.dimensions[0]:.3f} × {analysis.dimensions[1]:.3f} × {analysis.dimensions[2]:.3f}

## 策略

- 精度：{PRECISION_PROFILES[precision].label}
- 目标抽样偏差：{plan.target_deviation_mm:.3f} mm
- 计划截面：{plan.sections}

## 检查结果

{warning_lines}

## SolidWorks 输出

{solidworks_lines}

## 输出说明

当前版本将闭合 STL 导入并验证为 SolidWorks 实体 Body，可进行直接编辑并继续添加特征；它不承诺恢复扫描件原始的草图尺寸与设计历史。制造前仍需完成尺寸、偏差与人工视觉复核。
"""
    report_path = task_dir / "task_report.md"
    report_path.write_text(report, encoding="utf-8")
    notify(100, "任务完成" if not task_warnings else "分析完成，SolidWorks 输出需要处理")
    return TaskResult(
        task_dir=task_dir, analysis_path=analysis_path, plan_path=plan_path,
        report_path=report_path, output_sldprt=output_sldprt, warnings=task_warnings,
    )
