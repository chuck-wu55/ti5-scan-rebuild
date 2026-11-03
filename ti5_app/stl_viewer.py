from __future__ import annotations

import math
import struct
import threading
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF, QWheelEvent
from PySide6.QtWidgets import QWidget

Triangle = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]


def load_preview(path: Path, limit: int = 25_000) -> list[Triangle]:
    """Read a representative STL sample for interactive display."""
    size = path.stat().st_size
    binary_count = None
    if size >= 84:
        with path.open("rb") as stream:
            stream.seek(80)
            count = struct.unpack("<I", stream.read(4))[0]
        if 84 + count * 50 == size:
            binary_count = count
    triangles: list[Triangle] = []
    if binary_count is not None:
        stride = max(1, math.ceil(binary_count / limit))
        with path.open("rb") as stream:
            stream.seek(84)
            for index in range(binary_count):
                block = stream.read(50)
                if len(block) != 50:
                    break
                if index % stride == 0:
                    values = struct.unpack("<12fH", block)
                    triangles.append((values[3:6], values[6:9], values[9:12]))
        return triangles
    vertices: list[tuple[float, float, float]] = []
    with path.open("r", encoding="utf-8", errors="ignore") as stream:
        for line in stream:
            parts = line.strip().split()
            if len(parts) != 4 or parts[0].lower() != "vertex":
                continue
            try:
                vertices.append(tuple(float(value) for value in parts[1:4]))
            except ValueError:
                continue
            if len(vertices) == 3:
                if len(triangles) < limit:
                    triangles.append((vertices[0], vertices[1], vertices[2]))
                vertices = []
    return triangles


class StlView(QWidget):
    mesh_loaded = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self._triangles: list[Triangle] = []
        self._name = ""
        self._message = "打开 STL 文件后可在这里检查真实网格"
        self._yaw, self._pitch, self._zoom = -35.0, 24.0, 1.0
        self._pan, self._last = QPoint(), QPoint()
        self._drag_button = Qt.NoButton
        self.mesh_loaded.connect(self._accept_mesh)

    def load_stl(self, path: Path) -> None:
        self._triangles = []
        self._name = path.name
        self._message = "正在读取三维网格…"
        self.update()

        def worker() -> None:
            try:
                mesh = load_preview(path)
                message = f"已载入 {len(mesh):,} 个预览三角面"
            except Exception as exc:
                mesh, message = [], f"预览失败：{exc}"
            self.mesh_loaded.emit(mesh, message)

        threading.Thread(target=worker, daemon=True).start()

    def _accept_mesh(self, mesh: object, message: str) -> None:
        self._triangles = list(mesh)
        self._message = message
        self.reset_view()

    def reset_view(self) -> None:
        self._yaw, self._pitch, self._zoom = -35.0, 24.0, 1.0
        self._pan = QPoint()
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._last = event.position().toPoint()
        self._drag_button = event.button()
        self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_button == Qt.NoButton:
            return
        pos = event.position().toPoint()
        delta, self._last = pos - self._last, pos
        if self._drag_button == Qt.LeftButton:
            self._yaw += delta.x() * 0.6
            self._pitch = max(-89.0, min(89.0, self._pitch + delta.y() * 0.6))
        else:
            self._pan += delta
        self.update()

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_button = Qt.NoButton
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._zoom = max(0.15, min(8.0, self._zoom * (1.12 ** (event.angleDelta().y() / 120))))
        self.update()

    @staticmethod
    def _rotate(vertex, yaw: float, pitch: float):
        x, y, z = vertex
        cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
        x, z = x * cy + z * sy, -x * sy + z * cy
        return x, y * cp - z * sp, y * sp + z * cp

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#10191d"))
        painter.setPen(QPen(QColor(43, 60, 65, 120), 1))
        for x in range(0, self.width(), 36):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 36):
            painter.drawLine(0, y, self.width(), y)
        if not self._triangles:
            painter.setPen(QColor("#d6e2df"))
            painter.drawText(self.rect(), Qt.AlignCenter, self._message)
            return
        points = [point for triangle in self._triangles for point in triangle]
        mins = [min(p[a] for p in points) for a in range(3)]
        maxs = [max(p[a] for p in points) for a in range(3)]
        center = [(mins[a] + maxs[a]) / 2 for a in range(3)]
        extent = max(maxs[a] - mins[a] for a in range(3)) or 1.0
        scale = min(self.width(), self.height()) * 0.66 / extent * self._zoom
        yaw, pitch = math.radians(self._yaw), math.radians(self._pitch)
        ox, oy = self.width() / 2 + self._pan.x(), self.height() / 2 + self._pan.y()
        rendered = []
        for triangle in self._triangles:
            rotated = [self._rotate(tuple(v[a] - center[a] for a in range(3)), yaw, pitch) for v in triangle]
            a, b, c = rotated
            ab, ac = (b[0]-a[0], b[1]-a[1], b[2]-a[2]), (c[0]-a[0], c[1]-a[1], c[2]-a[2])
            normal = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
            length = math.sqrt(sum(n*n for n in normal)) or 1.0
            light = max(.18, min(1.0, (normal[0]*-.35 + normal[1]*-.45 + normal[2]*.82)/length*.5 + .55))
            polygon = QPolygonF([QPointF(ox+x*scale, oy-y*scale) for x, y, _z in rotated])
            rendered.append((sum(p[2] for p in rotated)/3, polygon, light))
        rendered.sort(key=lambda item: item[0])
        painter.setPen(QPen(QColor(77, 219, 196, 75), .55))
        for _depth, polygon, light in rendered:
            painter.setBrush(QColor.fromRgbF(.16*light, .70*light, .63*light, .95))
            painter.drawPolygon(polygon)
        painter.setPen(QColor("#d6e2df"))
        painter.drawText(18, self.height()-36, self._name)
        painter.setPen(QColor("#86a09a"))
        painter.drawText(18, self.height()-17, self._message)
        painter.setPen(QColor("#73f5dc"))
        painter.drawText(self.width()-240, 28, "左键旋转 · 滚轮缩放 · 右键平移")
