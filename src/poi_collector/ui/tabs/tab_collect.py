# -*- coding: utf-8 -*-
"""POI查询单工作台：左侧条件、右侧地图、底部紧凑进度。"""
import json
import os
import re
import subprocess
from datetime import datetime

from PySide6.QtCore import Qt, Signal, QThread, QTimer
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QFrame, QLabel, QComboBox,
    QLineEdit, QCheckBox, QPushButton, QProgressBar, QTextEdit, QButtonGroup,
    QRadioButton, QMessageBox, QFileDialog, QStackedWidget, QTabWidget,
    QSplitter, QDialog, QScrollArea, QSizePolicy,
)

from core.config import PROJECT_ROOT, load_config
from core.region import PROVINCES
from core.engine import DivisionEngine
from core.search import PoiSearchEngine
from core import geo_service
from core.category import load_categories, find_node, flatten_names, types_param
from core.china_cities import CHINA_CITIES
from core.coords import haversine_m
from core.store import PoiStore
from core.qc import QcEngine
from core.tile_sources import available_tile_sources
from ui import styles
from ui.workers import CollectWorker
from ui.category_dialog import CategoryDialog
from ui.map_widget import LeafletMapWidget


def quality_status(row):
    try:
        lon = float(row.get('lon', row.get('经度(WGS84)')))
        lat = float(row.get('lat', row.get('纬度(WGS84)')))
    except (TypeError, ValueError):
        return '异常'
    if not (73 <= lon <= 135 and 3 <= lat <= 54):
        return '异常'
    return '有效' if row.get('置信度') in ('高', '中') or row.get('匹配源') not in ('', '未匹配') else '待复核'


class ReverseGeocodeWorker(QThread):
    resolved = Signal(float, float, dict)
    failed = Signal(float, float)

    def __init__(self, lon, lat, preferred):
        super().__init__()
        self.lon, self.lat, self.preferred = lon, lat, preferred

    def run(self):
        result = geo_service.reverse_full(self.lon, self.lat, self.preferred)
        if result:
            self.resolved.emit(self.lon, self.lat, result)
        else:
            self.failed.emit(self.lon, self.lat)


class QcWorker(QThread):
    """结果就绪后独立执行联网交叉质检，不阻塞地图呈现和导出。"""
    completed = Signal(str, dict)
    failed = Signal(str, str)
    log = Signal(str)

    def __init__(self, token, cfg, result, parent=None):
        super().__init__(parent)
        self.token = token
        self.cfg = cfg
        self.result = dict(result)

    def run(self):
        try:
            report = QcEngine(self.cfg).run_all(
                self.result, log_cb=lambda line: self.log.emit(line))
            self.completed.emit(self.token, report)
        except Exception as exc:
            self.failed.emit(self.token, str(exc))


class TabCollect(QWidget):
    result_ready = Signal(dict)
    LEVELS = [('province', '省级'), ('city', '地市'), ('district', '区县'), ('town', '乡镇'), ('village', '村级')]

    def __init__(self):
        super().__init__()
        self.worker = None
        self.reverse_worker = None
        self._qc_workers = set()
        self._qc_token = ''
        self._pending_reverse_center = None
        self.category_codes = []
        self.last_result = None
        self._district_map = {}
        self._init_ui()
        self._load_provinces()
        self._on_mode_changed()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        body = QSplitter(Qt.Horizontal)
        body.setObjectName('poiWorkspaceSplitter')
        body.setChildrenCollapsible(False)
        body.setHandleWidth(5)

        self.left_panel = QFrame()
        self.left_panel.setProperty('card', True)
        self.left_panel.setMinimumWidth(390)
        left = QVBoxLayout(self.left_panel)
        left.setContentsMargins(8, 8, 8, 8)
        left.setSpacing(6)
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setMinimumWidth(330)
        self.side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        side = QWidget()
        form = QVBoxLayout(side)
        form.setContentsMargins(8, 4, 8, 4)
        form.setSpacing(8)
        form.setAlignment(Qt.AlignTop)

        form.addWidget(self._section('1. 选择查询模式'))
        modes = QHBoxLayout()
        modes.setSpacing(0)
        self.rb_division = self._mode_button('行政区划')
        self.rb_text = self._mode_button('分类搜索')
        self.rb_around = self._mode_button('周边搜索')
        self.rb_division.setChecked(True)
        self.mode_group = QButtonGroup(self)
        for button in (self.rb_division, self.rb_text, self.rb_around):
            self.mode_group.addButton(button)
            button.toggled.connect(self._on_mode_changed)
            modes.addWidget(button)
        form.addLayout(modes)

        form.addWidget(self._section('2. 选择区域范围'))
        region = QGridLayout()
        region.setHorizontalSpacing(8)
        region.setVerticalSpacing(6)
        self.province_combo, self.region_city, self.region_district = self._combo(), self._combo(), self._combo()
        self.province_combo.currentTextChanged.connect(self._on_province_changed)
        self.region_city.currentTextChanged.connect(lambda city: self._fill_districts(self.region_district, city))
        for row, (label, widget) in enumerate((('目标省份', self.province_combo), ('目标地市', self.region_city), ('目标区县', self.region_district))):
            region.addWidget(QLabel(label), row, 0)
            region.addWidget(widget, row, 1)
        region.setColumnStretch(1, 1)
        form.addLayout(region)

        self.task_stack = QStackedWidget()
        self.task_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.task_stack.addWidget(self._build_division_options())
        self.task_stack.addWidget(self._build_category_options())
        self.task_stack.addWidget(self._build_around_options())
        form.addWidget(self.task_stack)
        self.advanced_title = self._section('4. 高级选项')
        form.addWidget(self.advanced_title)
        advanced = QGridLayout()
        advanced.setHorizontalSpacing(8)
        advanced.setVerticalSpacing(6)
        self.provider_combo = QComboBox()
        self.provider_combo.addItem('自动优选', '')
        for name, code in (('天地图', 'tianditu'), ('高德', 'amap'), ('百度', 'baidu'), ('腾讯', 'tencent')):
            self.provider_combo.addItem(name, code)
        self.output_crs = QComboBox()
        self.output_crs.addItems(['WGS84', 'CGCS2000', 'GCJ-02', 'BD-09'])
        self.output_crs.setCurrentText(load_config().get('defaults', {}).get('output_crs', 'WGS84'))
        advanced.addWidget(QLabel('数据来源'), 0, 0)
        advanced.addWidget(self.provider_combo, 0, 1)
        advanced.addWidget(QLabel('坐标系'), 0, 2)
        advanced.addWidget(self.output_crs, 0, 3)
        form.addLayout(advanced)
        form.addStretch(1)
        self.side_scroll.setWidget(side)
        left.addWidget(self.side_scroll, 1)

        action_bar = QFrame()
        actions = QHBoxLayout(action_bar)
        actions.setContentsMargins(8, 6, 8, 2)
        actions.setSpacing(10)
        self.btn_start = QPushButton('▶ 开始查询')
        self.btn_cancel = QPushButton('取消')
        self.btn_reset = QPushButton('重置')
        self.btn_cancel.setProperty('kind', 'secondary')
        self.btn_reset.setProperty('kind', 'secondary')
        self.btn_cancel.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_cancel.clicked.connect(self._on_cancel)
        self.btn_reset.clicked.connect(self._reset_form)
        for button in (self.btn_start, self.btn_cancel, self.btn_reset):
            actions.addWidget(button)
        actions.addStretch(1)
        left.addWidget(action_bar)
        body.addWidget(self.left_panel)

        self.right_panel = QWidget()
        right = QVBoxLayout(self.right_panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)
        map_card = QFrame()
        map_card.setProperty('card', True)
        map_layout = QVBoxLayout(map_card)
        map_layout.setContentsMargins(6, 6, 6, 6)
        self.basemap_quick = QComboBox()
        self.basemap_quick.hide()
        self._reload_basemap_combo()
        self.basemap_quick.currentIndexChanged.connect(self._select_basemap)
        self.map_widget = LeafletMapWidget()
        self.map_widget.setMinimumSize(420, 320)
        self.map_widget.map_clicked.connect(self._accept_map_center)
        self.map_widget.center_requested.connect(self._accept_map_center)
        self.map_widget.bounds_selected.connect(self._accept_map_bounds)
        self.map_widget.source_changed.connect(self._on_map_source_changed)
        map_layout.addWidget(self.map_widget, 1)
        right.addWidget(map_card, 1)

        self.status_card = QFrame()
        self.status_card.setProperty('card', True)
        self.status_card.setFixedHeight(56)
        status = QHBoxLayout(self.status_card)
        status.setContentsMargins(12, 8, 12, 8)
        status.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setMinimumWidth(110)
        status.addWidget(self.progress_bar, 1)
        self.queried_label = QLabel('已查询 0')
        self.valid_label = QLabel('有效 0')
        self.review_label = QLabel('待复核 0')
        self.valid_label.setStyleSheet(f'color:{styles.SUCCESS};font-weight:600;')
        self.review_label.setStyleSheet(f'color:{styles.WARNING};font-weight:600;')
        for label in (self.queried_label, self.valid_label, self.review_label):
            status.addWidget(label)
        self.btn_log = QPushButton('运行日志')
        self.btn_export = QPushButton('导出结果')
        self.btn_collect_open = QPushButton('打开文件夹')
        self.btn_log.setProperty('kind', 'secondary')
        self.btn_collect_open.setProperty('kind', 'secondary')
        self.btn_export.setEnabled(False)
        self.btn_log.clicked.connect(self._show_log)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_collect_open.clicked.connect(self._on_open_folder)
        for button in (self.btn_log, self.btn_export, self.btn_collect_open):
            status.addWidget(button)
        right.addWidget(self.status_card)
        body.addWidget(self.right_panel)
        body.setStretchFactor(0, 0)
        body.setStretchFactor(1, 1)
        body.setSizes([390, 1000])
        root.addWidget(body, 1)
        self.workspace_splitter = body

        self.log_dialog = QDialog(self)
        self.log_dialog.setWindowTitle('运行日志')
        self.log_dialog.resize(760, 320)
        log_layout = QVBoxLayout(self.log_dialog)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setStyleSheet(styles.LOG_QSS)
        log_layout.addWidget(self.log_edit)
        close_log = QPushButton('关闭')
        close_log.setProperty('kind', 'secondary')
        close_log.clicked.connect(self.log_dialog.hide)
        log_layout.addWidget(close_log, 0, Qt.AlignRight)

    @staticmethod
    def _mode_button(text):
        button = QRadioButton(text)
        button.setProperty('segment', True)
        return button

    @staticmethod
    def _section(text):
        label = QLabel(text)
        label.setProperty('role', 'section')
        return label

    @staticmethod
    def _combo():
        combo = QComboBox()
        combo.setEditable(True)
        return combo

    def _build_division_options(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(self._section('3. 采集级别'))
        row = QHBoxLayout()
        self.level_checks = {}
        for key, label in self.LEVELS:
            box = QCheckBox(label)
            box.setChecked(key in ('city', 'district', 'town'))
            self.level_checks[key] = box
            row.addWidget(box)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _build_category_options(self):
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(self._section('3. POI分类'), 0, 0, 1, 3)
        self.text_cat_label = QLabel('尚未选择')
        self.text_cat_label.setWordWrap(True)
        self.btn_text_category = QPushButton('选择分类')
        self.btn_text_category.setProperty('kind', 'secondary')
        self.btn_text_category.clicked.connect(self._choose_category)
        layout.addWidget(QLabel('目标分类'), 1, 0)
        layout.addWidget(self.text_cat_label, 1, 1)
        layout.addWidget(self.btn_text_category, 1, 2)
        return page

    def _build_around_options(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignTop)
        layout.addWidget(self._section('3. 中心点'))
        self.center_tabs = QTabWidget()
        self.center_tabs.setDocumentMode(True)
        addr_page = QWidget()
        addr = QHBoxLayout(addr_page)
        addr.setContentsMargins(0, 4, 0, 4)
        addr.setSpacing(8)
        self.around_center = QLineEdit()
        self.around_center.setReadOnly(True)
        self.around_center.setPlaceholderText('在地图选点后自动识别地址')
        choose = QPushButton('地图选点')
        choose.setProperty('kind', 'secondary')
        choose.clicked.connect(lambda: self._set_task_status('请在右侧地图单击目标中心点', 'idle'))
        addr.addWidget(self.around_center, 1)
        addr.addWidget(choose)
        coord_page = QWidget()
        coord = QGridLayout(coord_page)
        coord.setContentsMargins(0, 4, 0, 4)
        coord.setSpacing(8)
        self.center_lon, self.center_lat = QLineEdit(), QLineEdit()
        self.center_lon.setPlaceholderText('经度')
        self.center_lat.setPlaceholderText('纬度')
        self.center_lon.setValidator(QDoubleValidator(-180, 180, 8, self))
        self.center_lat.setValidator(QDoubleValidator(-90, 90, 8, self))
        self.center_lon.editingFinished.connect(self._manual_center_changed)
        self.center_lat.editingFinished.connect(self._manual_center_changed)
        coord.addWidget(self.center_lon, 0, 0)
        coord.addWidget(self.center_lat, 0, 1)
        self.center_tabs.addTab(addr_page, '地址定位')
        self.center_tabs.addTab(coord_page, '坐标输入')
        layout.addWidget(self.center_tabs)
        radius = QHBoxLayout()
        radius.addWidget(QLabel('搜索半径'))
        self.around_radius = QLineEdit('3000')
        self.around_radius.setValidator(QIntValidator(100, 50000, self))
        self.around_radius.setMaximumWidth(110)
        self.around_radius.editingFinished.connect(self._refresh_buffer)
        radius.addWidget(self.around_radius)
        radius.addWidget(QLabel('米'))
        radius.addStretch(1)
        layout.addLayout(radius)
        layout.addWidget(self._section('4. 查询条件'))
        condition = QGridLayout()
        self.around_cat_label = QLabel('尚未选择')
        self.around_cat_label.setWordWrap(True)
        self.btn_around_category = QPushButton('选择分类')
        self.btn_around_category.setProperty('kind', 'secondary')
        self.btn_around_category.clicked.connect(self._choose_category)
        condition.addWidget(QLabel('POI分类'), 0, 0)
        condition.addWidget(self.around_cat_label, 0, 1)
        condition.addWidget(self.btn_around_category, 0, 2)
        layout.addLayout(condition)
        return page

    def _reload_basemap_combo(self):
        cfg = load_config()
        current = (cfg.get('basemap') or {}).get('active_source', 'arcgis_hybrid')
        self.basemap_quick.blockSignals(True)
        self.basemap_quick.clear()
        for source in available_tile_sources(cfg):
            self.basemap_quick.addItem(source['name'], source['id'])
        self.basemap_quick.setCurrentIndex(max(self.basemap_quick.findData(current), 0))
        self.basemap_quick.blockSignals(False)

    def _select_basemap(self):
        if self.basemap_quick.currentData():
            self.map_widget.select_source(self.basemap_quick.currentData())

    def _on_map_source_changed(self, source_id):
        index = self.basemap_quick.findData(source_id)
        if index >= 0:
            self.basemap_quick.blockSignals(True)
            self.basemap_quick.setCurrentIndex(index)
            self.basemap_quick.blockSignals(False)

    def _radius(self):
        try:
            return min(50000, max(100, int(self.around_radius.text())))
        except ValueError:
            return 3000

    def _accept_map_center(self, lon, lat):
        self.rb_around.setChecked(True)
        self.center_lon.setText(f'{lon:.6f}')
        self.center_lat.setText(f'{lat:.6f}')
        self.center_tabs.setCurrentIndex(0)
        self.map_widget.show_buffer(lon, lat, self._radius())
        self._reverse_center(lon, lat)

    def _accept_map_bounds(self, west, south, east, north):
        lon, lat = (west + east) / 2, (south + north) / 2
        radius = int(max(haversine_m(lon, lat, west, south), haversine_m(lon, lat, east, north)))
        radius = min(50000, max(100, radius))
        self.around_radius.setText(str(radius))
        self._accept_map_center(lon, lat)
        self._set_task_status(f'框选范围已回填 · 中心 {lon:.6f}, {lat:.6f} · 半径 {radius}米', 'idle')

    def _manual_center_changed(self):
        try:
            lon, lat = float(self.center_lon.text()), float(self.center_lat.text())
        except ValueError:
            return
        self.map_widget.show_buffer(lon, lat, self._radius())
        self._reverse_center(lon, lat)

    def _reverse_center(self, lon, lat):
        self._pending_reverse_center = (float(lon), float(lat))
        if self.reverse_worker and self.reverse_worker.isRunning():
            return
        self._start_pending_reverse()

    def _start_pending_reverse(self):
        if not self._pending_reverse_center:
            return
        lon, lat = self._pending_reverse_center
        self._pending_reverse_center = None
        self.around_center.setText('正在识别地址…')
        self.reverse_worker = ReverseGeocodeWorker(lon, lat, self._selected_preferred(load_config()))
        self.reverse_worker.resolved.connect(self._on_address_resolved)
        self.reverse_worker.failed.connect(self._on_address_failed)
        self.reverse_worker.finished.connect(self._on_reverse_finished)
        self.reverse_worker.start()

    def _on_reverse_finished(self):
        self.reverse_worker = None
        if self._pending_reverse_center:
            self._start_pending_reverse()

    def _on_address_failed(self, lon, lat):
        if self.center_lon.text() == f'{lon:.6f}' and self.center_lat.text() == f'{lat:.6f}':
            self.around_center.setText('未能识别地址（坐标仍可查询）')

    def _on_address_resolved(self, lon, lat, result):
        if self.center_lon.text() == f'{lon:.6f}' and self.center_lat.text() == f'{lat:.6f}':
            self.around_center.setText(result.get('formatted') or '地址信息不完整')
            self._set_task_status(f'中心地址已识别 · {result.get("provider", "")}', 'idle')

    def _refresh_buffer(self):
        self.around_radius.setText(str(self._radius()))
        try:
            self.map_widget.show_buffer(float(self.center_lon.text()), float(self.center_lat.text()), self._radius())
        except ValueError:
            pass

    def _load_provinces(self):
        self.province_combo.addItems(PROVINCES.keys())
        self.province_combo.setCurrentText(load_config()['defaults'].get('province', '广西壮族自治区'))
        self._on_province_changed(self.province_combo.currentText())

    def _on_province_changed(self, province):
        cities = CHINA_CITIES.get(province, [])
        self._district_map = self._load_local_districts(province)
        default_city = load_config()['defaults'].get('city', '')
        self.region_city.blockSignals(True)
        self.region_city.clear()
        self.region_city.addItems(cities)
        self.region_city.setCurrentText(default_city if default_city in cities else (cities[0] if cities else ''))
        self.region_city.blockSignals(False)
        self._fill_districts(self.region_district, self.region_city.currentText())
        self._update_scope()

    def _load_local_districts(self, province):
        code = PROVINCES.get(province, '')
        base = os.path.join(PROJECT_ROOT, 'data', 'divisions')
        path = next((p for p in (os.path.join(base, f'{code}_reference_v1.json'), os.path.join(base, f'{code}.json')) if os.path.exists(p)), '')
        if not path:
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as stream:
                data = json.load(stream)
            nodes = data.get('nodes', data) if isinstance(data, dict) else data
            by_code, result = {str(n.get('code', '')): n for n in nodes}, {}
            for node in nodes:
                if node.get('level') == 3:
                    city = (by_code.get(str(node.get('parent', ''))) or {}).get('name', '')
                    result.setdefault(city, []).append(node.get('name', ''))
            return result
        except Exception:
            return {}

    def _fill_districts(self, combo, city):
        current = combo.currentText()
        combo.clear()
        combo.addItem('全部区县')
        combo.addItems(self._district_map.get(city, []))
        if current and combo.findText(current) >= 0:
            combo.setCurrentText(current)
        self._update_scope()

    def _on_mode_changed(self):
        if not hasattr(self, 'task_stack'):
            return
        index = 0 if self.rb_division.isChecked() else 1 if self.rb_text.isChecked() else 2
        self.task_stack.setCurrentIndex(index)
        self._refresh_task_stack_height()
        self.advanced_title.setText('5. 高级选项' if self.rb_around.isChecked() else '4. 高级选项')
        self._update_scope()

    def _refresh_task_stack_height(self):
        """让当前模式按内容增高；超出左栏时由外层滚动区承载。"""
        current = self.task_stack.currentWidget()
        if current is None:
            return
        label = self.around_cat_label if current is self.task_stack.widget(2) else (
            self.text_cat_label if current is self.task_stack.widget(1) else None)
        if label is not None:
            available = max(120, self.task_stack.width() - 150)
            label.setMinimumHeight(0)
            wrapped_height = label.heightForWidth(available)
            label.setMinimumHeight(max(20, wrapped_height + 4))
        current.adjustSize()
        if current.layout():
            current.layout().activate()
        current.updateGeometry()
        hint = current.layout().sizeHint().height() if current.layout() else current.sizeHint().height()
        self.task_stack.setFixedHeight(max(hint, 54))
        self.task_stack.updateGeometry()

    def _update_scope(self):
        if not hasattr(self, 'map_widget'):
            return
        mode = '行政区划' if self.rb_division.isChecked() else '分类搜索' if self.rb_text.isChecked() else f'周边搜索 · {self._radius()}米'
        self.map_widget.set_scope_text(' · '.join(filter(None, (self.province_combo.currentText(), self.region_city.currentText(), self.region_district.currentText(), mode))))

    def _choose_category(self):
        dialog = CategoryDialog(self)
        styles.fit_all_buttons(dialog)
        if dialog.exec():
            self.category_codes = dialog.get_result()
            text = flatten_names(self.category_codes, load_categories()) or '尚未选择'
            self.text_cat_label.setText(text)
            self.around_cat_label.setText(text)
            QTimer.singleShot(0, self._refresh_task_stack_height)

    def _category_names(self):
        categories = load_categories()
        return [(find_node(categories, code) or {}).get('name', code) for code in self.category_codes]

    def on_keys_changed(self):
        geo_service.clear_source_cache()
        self._reload_basemap_combo()
        self.map_widget.reload_config()

    def _selected_preferred(self, cfg):
        return self.provider_combo.currentData() or cfg.get('defaults', {}).get('preferred_provider', 'tianditu')

    def _on_start(self):
        if self.worker and self.worker.isRunning():
            return
        cfg = load_config()
        if not any(cfg.get('keys', {}).values()):
            QMessageBox.warning(self, '缺少KEY', '请先到“基本设置”填写至少一个地图API KEY并保存。')
            return
        province, city, district = self.province_combo.currentText(), self.region_city.currentText(), self.region_district.currentText()
        preferred = self._selected_preferred(cfg)
        if preferred:
            cfg['source_priority'] = [preferred] + [name for name in cfg.get('source_priority', []) if name != preferred]
        if self.rb_around.isChecked():
            if not self.category_codes:
                QMessageBox.warning(self, '参数不完整', '请选择需要搜索的POI分类。')
                return
            try:
                center = f'{float(self.center_lon.text())},{float(self.center_lat.text())}'
            except ValueError:
                QMessageBox.warning(self, '参数不完整', '请在地图选点，或在“坐标输入”中填写有效经纬度。')
                return
            self.worker = PoiAroundWorker(province, city, district, center, self._radius(), self.category_codes, self._category_names(), preferred)
        elif self.rb_text.isChecked():
            if not self.category_codes:
                QMessageBox.warning(self, '参数不完整', '请选择需要搜索的POI分类。')
                return
            self.worker = CollectWorker(PoiSearchEngine(
                cfg, province, self.category_codes, '', os.path.join(PROJECT_ROOT, 'data'),
                os.path.join(PROJECT_ROOT, 'output'), city_name=city, district_name=district))
        else:
            levels = [key for key, box in self.level_checks.items() if box.isChecked()]
            if not levels:
                QMessageBox.warning(self, '提示', '请至少选择一个采集级别。')
                return
            self.worker = CollectWorker(DivisionEngine(
                cfg, province, levels, os.path.join(PROJECT_ROOT, 'data'),
                os.path.join(PROJECT_ROOT, 'output'), city_name=city, district_name=district))
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self.log)
        if hasattr(self.worker, 'status'):
            self.worker.status.connect(self._set_task_status)
        self.worker.finished_ok.connect(self._on_finished)
        if hasattr(self.worker, 'failed'):
            self.worker.failed.connect(self._on_failed)
        self.worker.finished.connect(self._on_worker_done)
        self._start_worker('正在准备查询…')

    def _start_worker(self, text):
        self.last_result = None
        self.map_widget.clear_results()
        self.btn_export.setEnabled(False)
        self.log_edit.clear()
        self.progress_bar.setRange(0, 0)
        self._set_task_status(text, 'running')
        self.queried_label.setText('已查询 0')
        self.valid_label.setText('有效 0')
        self.review_label.setText('待复核 0')
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.worker.start()

    def _on_cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.log('用户请求取消，已完成结果将保留。')
            self._set_task_status('正在取消任务…', 'retry')

    def _on_failed(self, message):
        self._set_task_status(f'任务失败：{message}', 'error')
        QMessageBox.critical(self, '搜索失败', message)
        self.log(f'错误：{message}')

    def _set_task_status(self, text, light='idle'):
        window = self.window()
        if hasattr(window, 'set_status'):
            window.set_status(text, light)

    def _on_progress(self, done, total, message):
        self.progress_bar.setRange(0, max(total, 1))
        self.progress_bar.setValue(done)
        self._set_task_status(f'{message} · {done:,}/{total:,}', 'running')
        self.queried_label.setText(f'已查询 {done:,}')

    def log(self, line):
        self.log_edit.append(line)

    def _show_log(self):
        self.log_dialog.show()
        self.log_dialog.raise_()
        self.log_dialog.activateWindow()

    def _on_finished(self, result):
        self.last_result = result
        self.result_ready.emit(result)
        if 'error' in result:
            self.btn_export.setEnabled(False)
            QMessageBox.warning(self, '错误', result['error'])
            return
        rows = result.get('nodes') or []
        self.map_widget.set_pois(rows)
        center = result.get('center')
        if center:
            self.map_widget.show_buffer(center[0], center[1], int(result.get('radius') or 0))
        matched = int(result.get('matched', len(rows)))
        if result.get('store_path'):
            store = PoiStore(result['store_path'])
            total, valid, review, abnormal = store.quality_counts()
            store.close()
        else:
            states = [quality_status(row) for row in rows]
            total, valid = matched, states.count('有效')
            review, abnormal = states.count('待复核'), states.count('异常')
        self.queried_label.setText(f'已查询 {total:,}')
        self.valid_label.setText(f'有效 {valid:,}')
        self.review_label.setText(f'待复核 {review + abnormal:,}')
        self.btn_export.setEnabled(True)
        self.progress_bar.setRange(0, max(matched, 1))
        self.progress_bar.setValue(matched)
        if result.get('mode') == 'poi' and matched and result.get('qc_pending'):
            self._set_task_status(
                f'查询完成 · {matched:,} 条结果已上图并可导出 · 后台质检中', 'running')
            self._start_background_qc(result)
        else:
            self._set_task_status(f'查询完成 · 地图已呈现结果 · 共 {matched:,} 条', 'idle')

    def _start_background_qc(self, result):
        token = f'{id(result)}:{result.get("store_path", "memory")}'
        self._qc_token = token
        result['qc_pending'] = True
        worker = QcWorker(token, load_config(), result, self)
        self._qc_workers.add(worker)
        worker.log.connect(self.log)
        worker.completed.connect(self._on_qc_completed)
        worker.failed.connect(self._on_qc_failed)
        worker.finished.connect(lambda w=worker: self._release_qc_worker(w))
        worker.start()

    def _release_qc_worker(self, worker):
        self._qc_workers.discard(worker)
        worker.deleteLater()

    def _on_qc_completed(self, token, report):
        if token != self._qc_token or not self.last_result:
            return
        self.last_result['qc'] = report
        self.last_result['qc_pending'] = False
        if self.last_result.get('store_path'):
            store = PoiStore(self.last_result['store_path'])
            total, valid, review, abnormal = store.quality_counts()
            store.close()
            self.queried_label.setText(f'已查询 {total:,}')
            self.valid_label.setText(f'有效 {valid:,}')
            self.review_label.setText(f'待复核 {review + abnormal:,}')
        self._set_task_status('后台质检完成 · 结果和质检报告可导出', 'idle')
        self.log('[质检] 后台质检完成，结果已纳入质检报告')

    def _on_qc_failed(self, token, message):
        if token != self._qc_token or not self.last_result:
            return
        self.last_result['qc_pending'] = False
        self._set_task_status('查询结果可用 · 后台质检未完成', 'retry')
        self.log(f'[质检] 后台质检异常（不影响地图和导出）：{message}')

    def _on_worker_done(self):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 1)

    def _reset_form(self):
        self.around_center.clear()
        self.center_lon.clear()
        self.center_lat.clear()
        self.category_codes = []
        self.text_cat_label.setText('尚未选择')
        self.around_cat_label.setText('尚未选择')
        self.around_radius.setText('3000')
        self.map_widget.clear_results()
        self.progress_bar.setValue(0)
        self._set_task_status('空闲', 'idle')
        QTimer.singleShot(0, self._refresh_task_stack_height)

    @staticmethod
    def _safe(value):
        return re.sub(r'[\\/:*?"<>|]+', '_', str(value)).strip('_')

    def _on_export(self):
        if not self.last_result:
            return
        from core import excel_out
        mode = '周边搜索' if self.rb_around.isChecked() else '分类搜索' if self.rb_text.isChecked() else '行政区划'
        detail = flatten_names(self.category_codes, load_categories()) if not self.rb_division.isChecked() else '全部'
        scope = '_'.join(filter(None, map(self._safe, (self.province_combo.currentText(), self.region_city.currentText(), self.region_district.currentText()))))
        if self.rb_around.isChecked():
            detail = f'{detail}_{self._radius()}米'
        default = f'{scope}_{mode}_{self._safe(detail or "全部")}_{datetime.now().strftime("%Y%m%d_%H%M%S")}_V2.0.xlsx'
        path, _ = QFileDialog.getSaveFileName(self, '导出Excel', os.path.join(PROJECT_ROOT, 'output', default), 'Excel (*.xlsx)')
        if path:
            excel_out.export_result(dict(self.last_result), path, self.output_crs.currentText())
            QMessageBox.information(self, '导出成功', f'已导出：\n{path}')

    def _on_open_folder(self):
        path = os.path.join(PROJECT_ROOT, 'output')
        os.makedirs(path, exist_ok=True)
        subprocess.Popen(['explorer', path])


class PoiAroundWorker(QThread):
    progress = Signal(int, int, str)
    log = Signal(str)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, province, city, district, center, radius, codes, names, preferred):
        super().__init__()
        self.province, self.city = province, city
        self.district = '' if district == '全部区县' else district
        self.center, self.radius = center, radius
        self.codes, self.names, self.preferred = codes, names, preferred
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            lon, lat = map(float, self.center.split(','))
            self.log.emit(f'周边分类搜索：{", ".join(self.names)} · 半径{self.radius}米')
            progress = lambda done, total, provider: self.progress.emit(done, total, f'{provider}搜索中')
            pois, total, provider = geo_service.around_search(
                lon, lat, self.radius, types=types_param(self.codes), category_names=self.names,
                preferred=self.preferred, progress_cb=progress, cancel_cb=lambda: self._stop)
            nodes = []
            for poi in pois:
                returned_district = str(poi.get('adname') or '')
                if self.district and returned_district and returned_district != self.district:
                    continue
                province = poi.get('pname') or self.province
                city = poi.get('cityname') or self.city
                district = returned_district or self.district
                address = str(poi.get('address') or '')
                for part in reversed((province, city, district)):
                    if part and part not in address:
                        address = str(part) + address
                nodes.append({'省份': province, '地市': city, '区县': district,
                              'name': poi.get('name', ''), 'type': poi.get('type', ''),
                              'lon': poi.get('lon'), 'lat': poi.get('lat'), 'address': address,
                              '来源': provider, '置信度': '中', 'adcode': poi.get('adcode', ''),
                              'typecode': poi.get('typecode', ''),
                              'distance': f'{haversine_m(lon, lat, poi.get("lon"), poi.get("lat")) / 1000:.1f} km'})
            self.finished_ok.emit({'mode': 'poi', 'province': self.province, 'nodes': nodes,
                                   'matched': len(nodes), 'total': total, 'center': (lon, lat),
                                   'radius': self.radius, 'qc': {}, 'qc_pending': True})
        except Exception as exc:
            self.failed.emit(str(exc))
