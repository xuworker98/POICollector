# -*- coding: utf-8 -*-
"""Pure Qt XYZ/TMS basemap widget.

The historical ``LeafletMapWidget`` class name is kept for compatibility;
this module uses no WebEngine, JavaScript or HTML.
"""
from __future__ import annotations

import math
from collections import OrderedDict

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QIcon, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QFrame, QMenu, QSizePolicy, QToolButton, QToolTip, QVBoxLayout, QWidget

from core.config import load_config, resource_path
from core.tile_sources import available_tile_sources


TILE_SIZE = 256
MAX_LAT = 85.05112878
DEFAULT_CENTER = (108.3669, 22.8170)


def _clamp_lat(lat: float) -> float:
    return max(-MAX_LAT, min(MAX_LAT, float(lat)))


def _lonlat_to_world(lon: float, lat: float, zoom: int) -> QPointF:
    scale = TILE_SIZE * (2 ** zoom)
    x = (float(lon) + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(_clamp_lat(lat)))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return QPointF(x, y)


def _world_to_lonlat(x: float, y: float, zoom: int) -> tuple[float, float]:
    scale = TILE_SIZE * (2 ** zoom)
    lon = x / scale * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / scale
    lat = math.degrees(math.atan(math.sinh(n)))
    return lon, _clamp_lat(lat)


class LeafletMapWidget(QWidget):
    """Native Qt tile map with the legacy public class name."""

    map_clicked = Signal(float, float)
    source_changed = Signal(str)
    poi_selected = Signal(int)
    center_requested = Signal(float, float)
    bounds_selected = Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self._center_lon, self._center_lat = DEFAULT_CENTER
        self._zoom = 11
        self._scope_text = "广西壮族自治区 · 南宁市"
        self._sources: list[dict] = []
        self._source: dict = {}
        self._fallback_order: list[str] = []
        self._fallback_attempted: set[str] = set()
        self._source_errors = 0
        self._pois: list[dict] = []
        self._clusters: list[dict] = []
        self._buffer: tuple[float, float, int] | None = None
        self._drag_start: QPoint | None = None
        self._drag_center_world: QPointF | None = None
        self._dragged = False
        self._box_mode = False
        self._box_start: QPoint | None = None
        self._box_rect: QRect | None = None
        self._pixmaps: OrderedDict[tuple, QPixmap] = OrderedDict()
        self._pending: dict[QNetworkReply, tuple] = {}
        self._network = QNetworkAccessManager(self)
        disk_cache = QNetworkDiskCache(self)
        from PySide6.QtCore import QStandardPaths
        cache_root = QStandardPaths.writableLocation(QStandardPaths.CacheLocation)
        disk_cache.setCacheDirectory(f"{cache_root}/POICollector/tiles")
        disk_cache.setMaximumCacheSize(256 * 1024 * 1024)
        self._network.setCache(disk_cache)
        self._build_toolbar()
        self.reload_config()

    def _build_toolbar(self):
        self._toolbar = QFrame(self)
        self._toolbar.setObjectName("mapToolbar")
        bar = QVBoxLayout(self._toolbar)
        bar.setContentsMargins(5, 5, 5, 5)
        bar.setSpacing(5)
        self._zoom_in = self._tool("+", "放大", "map_zoom_in.svg", compact=True)
        self._zoom_out = self._tool("−", "缩小", "map_zoom_out.svg", compact=True)
        self._locate = self._tool("定位中心", "将当前中心写入周边搜索并识别地址", "map_locate.svg")
        self._box = self._tool("框选范围", "拖动框选并自动计算中心、半径和地址", "map_box.svg")
        self._layers = self._tool("地图切换", "切换 XYZ/TMS 底图", "map_layers.svg")
        self._fit = self._tool("显示全部", "缩放至全部查询点", "map_fit.svg")
        for button in (self._zoom_in, self._zoom_out, self._locate, self._box, self._layers, self._fit):
            # 所有按钮沿外层白色工具栏的垂直中心线排列；尤其避免
            # 40px 的缩放按钮在 92px 操作按钮形成的宽容器内靠左。
            bar.addWidget(button, 0, Qt.AlignHCenter)
        self._zoom_in.clicked.connect(lambda: self._change_zoom(1))
        self._zoom_out.clicked.connect(lambda: self._change_zoom(-1))
        self._locate.clicked.connect(self._request_center)
        self._box.clicked.connect(self._begin_box_select)
        self._layers.clicked.connect(self._show_source_menu)
        self._fit.clicked.connect(self._fit_all)
        self._toolbar.setStyleSheet("""
            QFrame#mapToolbar { background: rgba(255,255,255,242); border: 1px solid #d7dee7; border-radius: 9px; }
            QToolButton { color:#334155; background:#ffffff; border:1px solid #d7dee7; border-radius:7px; }
            QToolButton[mapCompact="true"] { padding:0; margin:0; font-size:18px; text-align:center; }
            QToolButton[mapAction="true"] { padding:4px 6px; font-size:12px; }
            QToolButton:hover { color:#087fdb; border-color:#71b7ed; background:#f1f8ff; }
            QToolButton:pressed { background:#e3f1fc; }
            QToolButton:checked { color:#087fdb; border-color:#0984e3; background:#e8f4ff; }
        """)

    @staticmethod
    def _tool(text: str, tooltip: str, icon_name: str | None = None,
              compact: bool = False) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setToolTip(tooltip)
        button.setFocusPolicy(Qt.NoFocus)
        if compact:
            button.setProperty("mapCompact", True)
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setIcon(QIcon(resource_path(icon_name)))
            button.setIconSize(QSize(16, 16))
            button.setFixedSize(40, 30)
        elif icon_name:
            button.setProperty("mapAction", True)
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(QIcon(resource_path(icon_name)))
            button.setIconSize(QSize(22, 22))
            # Qt 的 TextUnderIcon 风格会在文字两侧额外预留样式边距；92px
            # 可保证四个汉字在 Windows 高 DPI 下仍完整显示，不触发省略号。
            button.setFixedSize(92, 58)
        return button

    def resizeEvent(self, event):
        super().resizeEvent(event)
        hint = self._toolbar.sizeHint()
        self._toolbar.setGeometry(max(8, self.width() - hint.width() - 10), 14, hint.width(), hint.height())
        self._toolbar.raise_()

    def reload_config(self):
        cfg = load_config()
        self._sources = [s for s in available_tile_sources(cfg) if s.get("kind") in {"xyz", "tms"}]
        basemap = cfg.get("basemap") or {}
        active = str(basemap.get("active_source") or "arcgis_hybrid")
        ids = [s["id"] for s in self._sources]
        if active not in ids:
            active = "arcgis_hybrid" if "arcgis_hybrid" in ids else (ids[0] if ids else "")
        priority = [str(i) for i in basemap.get("fallback_priority") or [] if str(i) in ids]
        self._fallback_order = list(dict.fromkeys([active, *priority, *ids]))
        self._fallback_attempted.clear()
        self.select_source(active)

    def select_source(self, source_id: str):
        source = next((item for item in self._sources if item.get("id") == source_id), None)
        if not source:
            return
        changed = source.get("id") != self._source.get("id")
        self._source = source
        self._zoom = max(int(source.get("min_zoom", 0)), min(self._zoom, int(source.get("max_zoom", 19))))
        self._source_errors = 0
        self._fallback_attempted.add(str(source.get("id")))
        self._abort_pending()
        self.update()
        if changed:
            self.source_changed.emit(str(source.get("id")))

    def _show_source_menu(self):
        menu = QMenu(self)
        for source in self._sources:
            action = menu.addAction(source.get("name") or source.get("id"))
            action.setCheckable(True)
            action.setChecked(source.get("id") == self._source.get("id"))
            action.triggered.connect(lambda _checked=False, sid=source.get("id"): self.select_source(sid))
        menu.exec(QCursor.pos())

    def _abort_pending(self):
        for reply in tuple(self._pending):
            reply.abort()
            reply.deleteLater()
        self._pending.clear()

    def _tile_url(self, template: str, z: int, x: int, y: int) -> str:
        if self._source.get("kind") == "tms":
            y = (2 ** z - 1) - y
        subdomains = str(self._source.get("subdomains") or "abc")
        subdomain = subdomains[(x + y) % len(subdomains)] if subdomains else "a"
        return (template.replace("{z}", str(z)).replace("{x}", str(x))
                .replace("{y}", str(y)).replace("{s}", subdomain))

    def _request_tile(self, key: tuple, url: str):
        if key in self._pixmaps or key in self._pending.values() or not url:
            return
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.UserAgentHeader, "POICollector/2.0 (Qt XYZ tile client)")
        request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.PreferCache)
        reply = self._network.get(request)
        self._pending[reply] = key
        reply.finished.connect(lambda r=reply: self._tile_finished(r))

    def _tile_finished(self, reply: QNetworkReply):
        key = self._pending.pop(reply, None)
        if key is None:
            reply.deleteLater()
            return
        active_id = str(self._source.get("id"))
        if reply.error() == QNetworkReply.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(reply.readAll()):
                self._pixmaps[key] = pixmap
                self._pixmaps.move_to_end(key)
                while len(self._pixmaps) > 384:
                    self._pixmaps.popitem(last=False)
                self._source_errors = 0
                self.update()
        elif key[0] == active_id and reply.error() != QNetworkReply.OperationCanceledError:
            self._source_errors += 1
            if self._source_errors >= 5:
                self._fallback_source()
        reply.deleteLater()

    def _fallback_source(self):
        for source_id in self._fallback_order:
            if source_id not in self._fallback_attempted:
                self.select_source(source_id)
                return

    def _top_left_world(self) -> QPointF:
        center = _lonlat_to_world(self._center_lon, self._center_lat, self._zoom)
        return QPointF(center.x() - self.width() / 2, center.y() - self.height() / 2)

    def _screen_to_lonlat(self, point: QPointF) -> tuple[float, float]:
        top = self._top_left_world()
        return _world_to_lonlat(top.x() + point.x(), top.y() + point.y(), self._zoom)

    def _lonlat_to_screen(self, lon: float, lat: float) -> QPointF:
        top = self._top_left_world()
        world = _lonlat_to_world(lon, lat, self._zoom)
        scale = TILE_SIZE * (2 ** self._zoom)
        dx = world.x() - top.x()
        if dx < -scale / 2:
            dx += scale
        elif dx > scale / 2:
            dx -= scale
        return QPointF(dx, world.y() - top.y())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#eef1f4"))
        self._paint_tiles(painter)
        self._paint_buffer(painter)
        self._paint_pois(painter)
        self._paint_box(painter)
        self._paint_labels(painter)

    def _paint_tiles(self, painter: QPainter):
        if not self._source:
            return
        top = self._top_left_world()
        n = 2 ** self._zoom
        first_x, last_x = math.floor(top.x() / TILE_SIZE), math.floor((top.x() + self.width()) / TILE_SIZE)
        first_y, last_y = math.floor(top.y() / TILE_SIZE), math.floor((top.y() + self.height()) / TILE_SIZE)
        source_id = str(self._source.get("id"))
        for raw_x in range(first_x, last_x + 1):
            x = raw_x % n
            for y in range(first_y, last_y + 1):
                if y < 0 or y >= n:
                    continue
                target = QRectF(raw_x * TILE_SIZE - top.x(), y * TILE_SIZE - top.y(), TILE_SIZE + 1, TILE_SIZE + 1)
                for layer, template in enumerate((self._source.get("url"), self._source.get("overlay_url"))):
                    if not template:
                        continue
                    key = (source_id, layer, self._zoom, x, y)
                    pixmap = self._pixmaps.get(key)
                    if pixmap:
                        painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
                        self._pixmaps.move_to_end(key)
                    else:
                        self._request_tile(key, self._tile_url(str(template), self._zoom, x, y))

    def _paint_buffer(self, painter: QPainter):
        if not self._buffer:
            return
        lon, lat, radius = self._buffer
        center = self._lonlat_to_screen(lon, lat)
        meters_per_pixel = 156543.03392 * math.cos(math.radians(lat)) / (2 ** self._zoom)
        pixels = min(50000.0, radius / max(meters_per_pixel, 0.01))
        painter.setPen(QPen(QColor(9, 132, 227, 190), 2))
        painter.setBrush(QColor(9, 132, 227, 42))
        painter.drawEllipse(center, pixels, pixels)
        painter.setBrush(QColor("#0984e3"))
        painter.drawEllipse(center, 6, 6)
        painter.setPen(QPen(Qt.white, 2))
        painter.drawEllipse(center, 2, 2)

    def _paint_pois(self, painter: QPainter):
        buckets: dict[tuple[int, int], list[tuple[dict, QPointF]]] = {}
        for poi in self._pois:
            point = self._lonlat_to_screen(poi["lon"], poi["lat"])
            if -30 <= point.x() <= self.width() + 30 and -30 <= point.y() <= self.height() + 30:
                buckets.setdefault((int(point.x() // 46), int(point.y() // 46)), []).append((poi, point))
        self._clusters = []
        for entries in buckets.values():
            x = sum(p.x() for _, p in entries) / len(entries)
            y = sum(p.y() for _, p in entries) / len(entries)
            point = QPointF(x, y)
            self._clusters.append({"point": point, "items": entries})
            if len(entries) > 1:
                radius = 13 if len(entries) < 100 else 16
                painter.setPen(QPen(Qt.white, 3))
                painter.setBrush(QColor("#0984e3"))
                painter.drawEllipse(point, radius, radius)
                painter.setPen(Qt.white)
                font = QFont(self.font()); font.setBold(True); painter.setFont(font)
                painter.drawText(QRectF(x-radius, y-radius, radius*2, radius*2), Qt.AlignCenter, str(len(entries)))
            else:
                painter.setPen(QPen(Qt.white, 2))
                painter.setBrush(QColor("#0984e3"))
                painter.drawEllipse(point, 7, 7)

    def _paint_box(self, painter: QPainter):
        if self._box_rect and not self._box_rect.isNull():
            painter.setPen(QPen(QColor("#0984e3"), 2, Qt.DashLine))
            painter.setBrush(QColor(9, 132, 227, 35))
            painter.drawRect(self._box_rect.normalized())

    def _paint_labels(self, painter: QPainter):
        painter.setFont(self.font())
        if self._scope_text:
            width = min(self.width() - 30, painter.fontMetrics().horizontalAdvance(self._scope_text) + 28)
            rect = QRectF(12, 12, max(120, width), 32)
            painter.setPen(QPen(QColor("#d7dee7"), 1))
            painter.setBrush(QColor(255, 255, 255, 235))
            painter.drawRoundedRect(rect, 16, 16)
            painter.setPen(QColor("#2d3436"))
            painter.drawText(rect.adjusted(14, 0, -12, 0), Qt.AlignVCenter | Qt.AlignLeft, self._scope_text)
        attribution = str(self._source.get("attribution") or self._source.get("name") or "")
        if attribution:
            text = f"底图：{attribution}"
            width = painter.fontMetrics().horizontalAdvance(text) + 12
            rect = QRectF(max(4, self.width() - width - 6), self.height() - 23, width, 19)
            painter.fillRect(rect, QColor(255, 255, 255, 205))
            painter.setPen(QColor("#636e72"))
            painter.drawText(rect, Qt.AlignCenter, text)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        point = event.position().toPoint()
        if self._box_mode:
            self._box_start = point
            self._box_rect = QRect(point, point)
            self.setCursor(Qt.CrossCursor)
        else:
            self._drag_start = point
            self._drag_center_world = _lonlat_to_world(self._center_lon, self._center_lat, self._zoom)
            self._dragged = False
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QMouseEvent):
        point = event.position().toPoint()
        if self._box_mode and self._box_start is not None:
            self._box_rect = QRect(self._box_start, point).normalized()
            self.update()
        elif self._drag_start is not None and self._drag_center_world is not None:
            delta = point - self._drag_start
            self._dragged = self._dragged or delta.manhattanLength() > 3
            lon, lat = _world_to_lonlat(self._drag_center_world.x() - delta.x(), self._drag_center_world.y() - delta.y(), self._zoom)
            self._center_lon, self._center_lat = lon, lat
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        point = event.position().toPoint()
        if self._box_mode and self._box_start is not None:
            rect = QRect(self._box_start, point).normalized()
            self._box_start = None
            self._box_mode = False
            self._box.setChecked(False)
            self.setCursor(Qt.OpenHandCursor)
            if rect.width() >= 8 and rect.height() >= 8:
                west, north = self._screen_to_lonlat(rect.topLeft())
                east, south = self._screen_to_lonlat(rect.bottomRight())
                self._box_rect = rect
                self.bounds_selected.emit(min(west, east), min(south, north), max(west, east), max(south, north))
            else:
                self._box_rect = None
            self.update()
            return
        was_dragged = self._dragged
        self._drag_start = None
        self._drag_center_world = None
        self.setCursor(Qt.OpenHandCursor)
        if not was_dragged:
            if self._handle_poi_click(point):
                return
            lon, lat = self._screen_to_lonlat(point)
            self.map_clicked.emit(lon, lat)

    def _handle_poi_click(self, point: QPoint) -> bool:
        for cluster in self._clusters:
            center: QPointF = cluster["point"]
            if math.hypot(center.x() - point.x(), center.y() - point.y()) <= 17:
                entries = cluster["items"]
                if len(entries) > 1:
                    self._center_lon, self._center_lat = self._screen_to_lonlat(center)
                    self._change_zoom(1)
                else:
                    poi = entries[0][0]
                    self.poi_selected.emit(int(poi["index"]))
                    detail = f'<b>{poi.get("name") or "POI"}</b><br>{poi.get("address") or "暂无地址"}'
                    QToolTip.showText(self.mapToGlobal(point), detail, self)
                return True
        return False

    def wheelEvent(self, event: QWheelEvent):
        delta = 1 if event.angleDelta().y() > 0 else -1
        before = self._screen_to_lonlat(event.position())
        old_zoom = self._zoom
        self._change_zoom(delta)
        if self._zoom != old_zoom:
            after_world = _lonlat_to_world(*before, self._zoom)
            center_world = QPointF(after_world.x() - event.position().x() + self.width()/2,
                                   after_world.y() - event.position().y() + self.height()/2)
            self._center_lon, self._center_lat = _world_to_lonlat(center_world.x(), center_world.y(), self._zoom)
            self.update()

    def _change_zoom(self, delta: int):
        minimum = int(self._source.get("min_zoom", 0))
        maximum = int(self._source.get("max_zoom", 19))
        self._zoom = max(minimum, min(maximum, self._zoom + delta))
        self.update()

    def _begin_box_select(self):
        self._box_mode = True
        self._box_rect = None
        self._box.setCheckable(True)
        self._box.setChecked(True)
        self.setCursor(Qt.CrossCursor)

    def _request_center(self):
        lon, lat = (self._buffer[0], self._buffer[1]) if self._buffer else (self._center_lon, self._center_lat)
        self.set_center(lon, lat, self._zoom)
        self.center_requested.emit(lon, lat)

    def set_pois(self, rows: list[dict], limit: int = 3000):
        items = []
        for index, row in enumerate(rows[:limit]):
            try:
                lon = float(row.get("lon", row.get("经度(WGS84)")))
                lat = float(row.get("lat", row.get("纬度(WGS84)")))
            except (TypeError, ValueError):
                continue
            items.append({
                "lon": lon, "lat": lat,
                "name": str(row.get("name") or row.get("名称") or row.get("POI名称") or ""),
                "address": str(row.get("address") or row.get("POI地址") or row.get("政府驻地地址") or ""),
                "source": str(row.get("来源") or row.get("匹配源") or ""),
                "index": index,
            })
        self._pois = items
        if items:
            self._fit_all()
        else:
            self.update()

    def _fit_all(self):
        points = [(p["lon"], p["lat"]) for p in self._pois]
        if not points:
            if self._buffer:
                self.set_center(self._buffer[0], self._buffer[1], self._zoom)
            return
        west, east = min(p[0] for p in points), max(p[0] for p in points)
        south, north = min(p[1] for p in points), max(p[1] for p in points)
        self._center_lon, self._center_lat = (west + east) / 2, (south + north) / 2
        for zoom in range(int(self._source.get("max_zoom", 19)), int(self._source.get("min_zoom", 0)) - 1, -1):
            nw, se = _lonlat_to_world(west, north, zoom), _lonlat_to_world(east, south, zoom)
            if abs(se.x() - nw.x()) <= max(100, self.width() - 90) and abs(se.y() - nw.y()) <= max(100, self.height() - 90):
                self._zoom = zoom
                break
        self.update()

    def set_center(self, lon: float, lat: float, zoom: int = 15):
        self._center_lon, self._center_lat = float(lon), _clamp_lat(lat)
        self._zoom = max(int(self._source.get("min_zoom", 0)), min(int(zoom), int(self._source.get("max_zoom", 19))))
        self.update()

    def set_scope_text(self, text: str):
        self._scope_text = str(text)
        self.update()

    def show_buffer(self, lon: float, lat: float, radius: int):
        self._buffer = (float(lon), _clamp_lat(lat), max(1, int(radius)))
        self.set_center(lon, lat, max(self._zoom, 12))

    def clear_results(self):
        self._pois = []
        self._clusters = []
        self._buffer = None
        self._box_rect = None
        self.update()

    def diagnostic_state(self) -> dict:
        return {
            "engine": "pure-qt-xyz", "source": self._source.get("id", ""),
            "source_count": len(self._sources), "zoom": self._zoom,
            "center": [self._center_lon, self._center_lat],
            "poi_count": len(self._pois), "has_buffer": self._buffer is not None,
        }
