from __future__ import annotations

import hashlib
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Iterator

from .models import PRECISION_PROFILES, Precision, StlAnalysis


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_format(path: Path) -> tuple[str, int | None]:
    size = path.stat().st_size
    if size >= 84:
        with path.open("rb") as handle:
            handle.seek(80)
            count = struct.unpack("<I", handle.read(4))[0]
        if 84 + count * 50 == size:
            return "binary", count
    return "ascii", None


def _binary_triangles(path: Path) -> Iterator[tuple[tuple[float, float, float], ...]]:
    with path.open("rb") as handle:
        handle.seek(80)
        count = struct.unpack("<I", handle.read(4))[0]
        for _ in range(count):
            block = handle.read(50)
            if len(block) != 50:
                raise ValueError("STL 文件在三角面数据中途结束。")
            values = struct.unpack("<12fH", block)
            yield (values[3:6], values[6:9], values[9:12])


def _ascii_triangles(path: Path) -> Iterator[tuple[tuple[float, float, float], ...]]:
    vertices: list[tuple[float, float, float]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            parts = line.strip().split()
            if len(parts) == 4 and parts[0].lower() == "vertex":
                try:
                    vertices.append(tuple(float(value) for value in parts[1:4]))
                except ValueError:
                    continue
                if len(vertices) == 3:
                    yield tuple(vertices)
                    vertices = []


def _area2(triangle: tuple[tuple[float, float, float], ...]) -> float:
    a, b, c = triangle
    ab = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    ac = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return math.sqrt(sum(value * value for value in cross))


def analyze_stl(path: str | Path, precision: Precision = Precision.MEDIUM) -> StlAnalysis:
    source = Path(path).expanduser().resolve()
    if source.suffix.lower() != ".stl":
        raise ValueError("请选择 STL 文件。")
    if not source.exists() or source.stat().st_size < 15:
        raise ValueError("STL 文件不存在或内容为空。")

    format_name, declared_count = detect_format(source)
    iterator = _binary_triangles(source) if format_name == "binary" else _ascii_triangles(source)
    profile = PRECISION_PROFILES[precision]
    mins = [float("inf")] * 3
    maxs = [float("-inf")] * 3
    degenerate = 0
    count = 0
    edge_counter: Counter[tuple[tuple[float, float, float], tuple[float, float, float]]] = Counter()
    check_edges = True

    for triangle in iterator:
        count += 1
        for vertex in triangle:
            for axis in range(3):
                mins[axis] = min(mins[axis], vertex[axis])
                maxs[axis] = max(maxs[axis], vertex[axis])
        if _area2(triangle) <= 1e-12:
            degenerate += 1
        if check_edges and count <= profile.boundary_check_limit:
            rounded = [tuple(round(value, 6) for value in vertex) for vertex in triangle]
            for a, b in ((0, 1), (1, 2), (2, 0)):
                edge_counter[tuple(sorted((rounded[a], rounded[b])))] += 1
        elif count > profile.boundary_check_limit:
            check_edges = False
            edge_counter.clear()

    if count == 0:
        raise ValueError("没有在 STL 中读取到有效三角面。")
    if declared_count is not None and declared_count != count:
        raise ValueError(f"STL 面数声明为 {declared_count}，实际读取为 {count}。")

    boundary = None if not check_edges else sum(1 for uses in edge_counter.values() if uses == 1)
    watertight = None if boundary is None else boundary == 0
    warnings: list[str] = []
    if boundary:
        warnings.append(f"检测到 {boundary} 条疑似开放边，模型可能不是闭合网格。")
    if degenerate:
        warnings.append(f"检测到 {degenerate} 个退化三角面。")
    dimensions = [maxs[i] - mins[i] for i in range(3)]
    if max(dimensions) > 10_000 or max(dimensions) < 1:
        warnings.append("模型尺度异常，请确认 STL 使用的长度单位。")
    if not check_edges:
        warnings.append("模型较大，已跳过完整开放边统计以控制内存占用。")

    return StlAnalysis(
        source=str(source),
        format=format_name,
        size_bytes=source.stat().st_size,
        triangle_count=count,
        sampled_triangles=min(count, profile.sample_limit),
        bounds_min=mins,
        bounds_max=maxs,
        dimensions=dimensions,
        degenerate_triangles=degenerate,
        boundary_edge_count=boundary,
        watertight_likely=watertight,
        warnings=warnings,
        sha256=_sha256(source),
    )

