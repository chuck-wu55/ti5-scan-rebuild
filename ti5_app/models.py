from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Precision(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    FINE = "fine"


@dataclass(frozen=True)
class PrecisionProfile:
    label: str
    sample_limit: int
    boundary_check_limit: int
    section_count: int
    target_deviation_mm: float
    description: str
    max_p95_deviation_mm: float
    min_surface_coverage: float
    min_feature_coverage: float
    min_native_features: int
    min_refinement_iterations: int
    required_regions: tuple[str, ...]


PRECISION_PROFILES = {
    Precision.SIMPLE: PrecisionProfile(
        "简单", 100_000, 250_000, 8, 2.0, "主体外形、安装基准与主要接口",
        4.0, 0.50, 0.70, 1, 1, ("主体外轮廓", "安装基准", "主要接口"),
    ),
    Precision.MEDIUM: PrecisionProfile(
        "中等", 500_000, 1_000_000, 16, 1.0, "核心外形、主孔槽与可编辑接口",
        2.0, 0.60, 0.80, 2, 2,
        ("主体外轮廓", "内轮廓", "端面", "主孔槽", "主要筋或台阶"),
    ),
    Precision.FINE: PrecisionProfile(
        "精细", 2_000_000, 2_500_000, 32, 0.5, "昨日标准：核心曲面、功能接口与大特征",
        1.0, 0.70, 0.90, 3, 3,
        ("主体外轮廓", "内轮廓", "端面", "全部可证实孔槽", "筋与台阶", "局部曲面与过渡"),
    ),
}


@dataclass
class StlAnalysis:
    source: str
    format: str
    size_bytes: int
    triangle_count: int
    sampled_triangles: int
    bounds_min: list[float]
    bounds_max: list[float]
    dimensions: list[float]
    degenerate_triangles: int
    boundary_edge_count: int | None
    watertight_likely: bool | None
    warnings: list[str] = field(default_factory=list)
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconstructionPlan:
    precision: str
    source: str
    target_deviation_mm: float
    sections: int
    max_p95_deviation_mm: float
    min_surface_coverage: float
    min_feature_coverage: float
    min_native_features: int
    min_refinement_iterations: int
    required_regions: list[str]
    stages: list[dict[str, Any]]
    limitations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskResult:
    task_dir: Path
    analysis_path: Path
    plan_path: Path
    report_path: Path
    output_sldprt: Path | None = None
    output_step: Path | None = None
    warnings: list[str] = field(default_factory=list)
