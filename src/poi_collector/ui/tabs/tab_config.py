# -*- coding: utf-8 -*-
"""Settings: query credentials, display credentials, basemaps and defaults."""
from __future__ import annotations

import os
import uuid

from PySide6.QtCore import Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGroupBox, QGridLayout, QLabel, QLineEdit,
    QPushButton, QHBoxLayout, QButtonGroup, QRadioButton, QMessageBox,
    QComboBox, QSpinBox, QFileDialog, QTabWidget, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView,
)

from core.china_cities import CHINA_CITIES
from core.config import load_config, save_config, build_sources, PROJECT_ROOT
from core.tile_sources import available_tile_sources, validate_tile_source, source_by_id
from ui import styles
from ui.workers import KeyTestWorker, MapKeyTestWorker, TileTestWorker


class TabConfig(QWidget):
    keys_changed = Signal()
    SOURCES = [('tianditu', '天地图'), ('amap', '高德'), ('baidu', '百度'), ('tencent', '腾讯')]
    APPLY_URLS = {
        'tianditu': 'https://console.tianditu.gov.cn/',
        'amap': 'https://console.amap.com/dev/key/app',
        'baidu': 'https://lbsyun.baidu.com/apiconsole/key',
        'tencent': 'https://lbs.qq.com/dev/console/application/mine',
    }
    # 纯 Qt 地图只直接请求 XYZ/WMTS 瓦片，不加载浏览器 JavaScript SDK。
    MAP_FIELDS = [('tianditu', '天地图地图服务KEY')]

    def __init__(self):
        super().__init__()
        self.query_key_edits, self.query_key_status = {}, {}
        # Backwards-compatible aliases used by existing integrations/tests.
        self.key_edits, self.key_status = self.query_key_edits, self.query_key_status
        self.map_key_edits, self.map_key_status = {}, {}
        self._workers, self._custom_sources, self._editing_source = [], [], None
        self._init_ui()
        self._load_config()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16); root.setSpacing(10); root.setAlignment(Qt.AlignTop)
        self.sections = QTabWidget()
        self.keys_page, self.basemap_page, self.defaults_page = QWidget(), QWidget(), QWidget()
        self.sections.addTab(self.keys_page, '服务KEY')
        self.sections.addTab(self.basemap_page, '底图与XYZ')
        self.sections.addTab(self.defaults_page, '运行与输出')
        root.addWidget(self.sections, 1)
        self._build_keys_page(); self._build_basemap_page(); self._build_defaults_page()
        buttons = QHBoxLayout(); buttons.addStretch()
        self.reset_btn = QPushButton('重置'); self.reset_btn.clicked.connect(self._reset)
        self.save_btn = QPushButton('保存配置'); self.save_btn.clicked.connect(self._save_config)
        buttons.addWidget(self.reset_btn); buttons.addWidget(self.save_btn); buttons.addStretch(); root.addLayout(buttons)

    def _build_keys_page(self):
        layout = QVBoxLayout(self.keys_page); layout.setContentsMargins(12, 12, 12, 12); layout.setAlignment(Qt.AlignTop)
        query_group = QGroupBox('POI查询服务')
        grid = QGridLayout(query_group); grid.setHorizontalSpacing(10); grid.setVerticalSpacing(8)
        headers = ['来源', 'WebService KEY', '状态', '操作']
        for panel in range(2):
            base = panel * 5
            for col, header in enumerate(headers):
                label = QLabel(header); label.setProperty('role', 'muted'); grid.addWidget(label, 0, base + col)
        grid.setColumnMinimumWidth(4, 16); grid.setColumnStretch(1, 1); grid.setColumnStretch(6, 1)
        for index, (name, label) in enumerate(self.SOURCES):
            row, panel = divmod(index, 2); row += 1; base = panel * 5
            edit = self._secret_edit('请输入查询服务KEY'); status = self._status_label()
            test = QPushButton('测试'); test.clicked.connect(lambda _, n=name: self._test_query_key(n))
            apply_btn = QPushButton('申请'); apply_btn.setProperty('kind', 'secondary')
            apply_btn.clicked.connect(lambda _, n=name: self._open_apply(n))
            ops = QHBoxLayout(); ops.setContentsMargins(0, 0, 0, 0); ops.setSpacing(8); ops.addWidget(test); ops.addWidget(apply_btn)
            grid.addWidget(QLabel(label), row, base); grid.addWidget(edit, row, base + 1)
            grid.addWidget(status, row, base + 2); grid.addLayout(ops, row, base + 3)
            self.query_key_edits[name], self.query_key_status[name] = edit, status
        layout.addWidget(query_group)

        display_group = QGroupBox('地图显示服务')
        display = QGridLayout(display_group); display.setHorizontalSpacing(10); display.setVerticalSpacing(8)
        for col, text in enumerate(('服务', '显示KEY', '状态', '操作')):
            label = QLabel(text); label.setProperty('role', 'muted'); display.addWidget(label, 0, col)
        display.setColumnStretch(1, 1)
        for row, (name, label) in enumerate(self.MAP_FIELDS, 1):
            edit = self._secret_edit('请输入地图显示KEY'); status = self._status_label()
            display.addWidget(QLabel(label), row, 0); display.addWidget(edit, row, 1); display.addWidget(status, row, 2)
            provider = 'tianditu'
            ops = QHBoxLayout(); ops.setContentsMargins(0, 0, 0, 0); ops.setSpacing(8)
            test = QPushButton('测试底图'); test.clicked.connect(lambda _, n=name: self._test_map_key(n)); ops.addWidget(test)
            apply_btn = QPushButton('申请'); apply_btn.setProperty('kind', 'secondary')
            apply_btn.clicked.connect(lambda _, p=provider: self._open_apply(p)); ops.addWidget(apply_btn)
            display.addLayout(ops, row, 3)
            self.map_key_edits[name], self.map_key_status[name] = edit, status
        reuse = QHBoxLayout()
        self.reuse_tianditu = QCheckBox('天地图显示服务使用查询KEY')
        reuse.addWidget(self.reuse_tianditu); reuse.addStretch()
        display.addLayout(reuse, len(self.MAP_FIELDS) + 1, 0, 1, 4)
        note = QLabel('纯Qt地图直接读取XYZ/WMTS瓦片；高德、百度、腾讯KEY仅用于POI与地址查询。')
        note.setProperty('role', 'muted'); display.addWidget(note, len(self.MAP_FIELDS) + 2, 0, 1, 4)
        layout.addWidget(display_group)

    @staticmethod
    def _secret_edit(placeholder):
        edit = QLineEdit(); edit.setEchoMode(QLineEdit.Password); edit.setPlaceholderText(placeholder)
        edit.setMaximumWidth(250)
        return edit

    @staticmethod
    def _status_label():
        label = QLabel('未测试'); label.setProperty('role', 'muted'); label.setFixedWidth(68)
        label.setAlignment(Qt.AlignCenter); return label

    def _build_basemap_page(self):
        layout = QVBoxLayout(self.basemap_page); layout.setContentsMargins(12, 12, 12, 12); layout.setAlignment(Qt.AlignTop)
        default_group = QGroupBox('默认底图')
        row = QHBoxLayout(default_group); row.addWidget(QLabel('启动时显示：'))
        self.basemap_combo = QComboBox(); self.basemap_combo.setMinimumWidth(240); row.addWidget(self.basemap_combo, 1)
        self.test_basemap_btn = QPushButton('测试连接'); self.test_basemap_btn.clicked.connect(self._test_selected_basemap)
        self.basemap_status = self._status_label(); row.addWidget(self.test_basemap_btn); row.addWidget(self.basemap_status)
        layout.addWidget(default_group)

        list_group = QGroupBox('自定义XYZ/TMS图源')
        list_layout = QVBoxLayout(list_group)
        self.tile_table = QTableWidget(0, 5); self.tile_table.setHorizontalHeaderLabels(['名称', '类型', 'URL模板', '缩放级别', '署名'])
        self.tile_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tile_table.setSelectionBehavior(QTableWidget.SelectRows); self.tile_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tile_table.setMaximumHeight(150); list_layout.addWidget(self.tile_table)
        form = QGridLayout()
        self.tile_name = QLineEdit(); self.tile_name.setPlaceholderText('例如：单位卫星图')
        self.tile_url = QLineEdit(); self.tile_url.setPlaceholderText('必须包含 {z}、{x}、{y}')
        self.tile_kind = QComboBox(); self.tile_kind.addItems(['XYZ', 'TMS'])
        self.tile_min_zoom, self.tile_max_zoom = QSpinBox(), QSpinBox()
        self.tile_min_zoom.setRange(0, 24); self.tile_max_zoom.setRange(0, 24); self.tile_max_zoom.setValue(19)
        self.tile_min_zoom.setButtonSymbols(QSpinBox.NoButtons); self.tile_max_zoom.setButtonSymbols(QSpinBox.NoButtons)
        self.tile_attribution = QLineEdit(); self.tile_attribution.setPlaceholderText('地图版权与数据来源')
        form.addWidget(QLabel('图源名称：'), 0, 0); form.addWidget(self.tile_name, 0, 1)
        form.addWidget(QLabel('瓦片类型：'), 0, 2); form.addWidget(self.tile_kind, 0, 3)
        form.addWidget(QLabel('URL模板：'), 1, 0); form.addWidget(self.tile_url, 1, 1, 1, 3)
        form.addWidget(QLabel('最小级别：'), 2, 0); form.addWidget(self.tile_min_zoom, 2, 1)
        form.addWidget(QLabel('最大级别：'), 2, 2); form.addWidget(self.tile_max_zoom, 2, 3)
        form.addWidget(QLabel('署名信息：'), 3, 0); form.addWidget(self.tile_attribution, 3, 1, 1, 3)
        list_layout.addLayout(form)
        buttons = QHBoxLayout(); buttons.addStretch()
        self.add_tile_btn = QPushButton('添加图源'); self.add_tile_btn.clicked.connect(self._add_custom_source)
        edit = QPushButton('编辑所选'); edit.setProperty('kind', 'secondary'); edit.clicked.connect(self._edit_custom_source)
        remove = QPushButton('移除所选'); remove.setProperty('kind', 'secondary'); remove.clicked.connect(self._remove_custom_source)
        buttons.addWidget(self.add_tile_btn); buttons.addWidget(edit); buttons.addWidget(remove); buttons.addStretch(); list_layout.addLayout(buttons)
        layout.addWidget(list_group)
        warning = QLabel('XYZ底图只负责地图显示，不提供POI、地址或行政区划查询。含Token的自定义URL使用Windows DPAPI加密保存。')
        warning.setWordWrap(True); warning.setProperty('role', 'muted'); layout.addWidget(warning)

    def _build_defaults_page(self):
        layout = QVBoxLayout(self.defaults_page); layout.setContentsMargins(12, 12, 12, 12); layout.setAlignment(Qt.AlignTop)
        out_group = QGroupBox('输出设置'); out = QGridLayout(out_group); out.addWidget(QLabel('默认输出坐标系：'), 0, 0)
        self.rb_wgs, self.rb_cgcs, self.rb_gcj, self.rb_bd = [QRadioButton(x) for x in ('WGS84', 'CGCS2000', 'GCJ-02', 'BD-09')]
        self.rb_wgs.setChecked(True); self.crs_group = QButtonGroup(self); crs_row = QHBoxLayout()
        for button in (self.rb_wgs, self.rb_cgcs, self.rb_gcj, self.rb_bd): self.crs_group.addButton(button); crs_row.addWidget(button)
        crs_row.addStretch(); out.addLayout(crs_row, 0, 1); layout.addWidget(out_group)

        defaults = QGroupBox('默认参数'); grid = QGridLayout(defaults)
        self.province_combo = QComboBox(); self.province_combo.addItems(list(CHINA_CITIES)); self.province_combo.currentTextChanged.connect(self._on_province_changed)
        self.city_combo = QComboBox(); self.radius_spin = QSpinBox(); self.radius_spin.setRange(100, 50000); self.radius_spin.setValue(3000)
        self.provider_combo = QComboBox(); self.provider_combo.addItems(['天地图', '高德', '百度', '腾讯'])
        self.sample_spin = QSpinBox(); self.sample_spin.setRange(0, 5000); self.sample_spin.setSingleStep(50); self.sample_spin.setValue(500)
        self.radius_spin.setButtonSymbols(QSpinBox.NoButtons); self.sample_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.golden_edit = QLineEdit(); self.golden_edit.setReadOnly(True); self.golden_btn = QPushButton('浏览'); self.golden_btn.clicked.connect(self._browse_golden)
        grid.addWidget(QLabel('默认省份：'), 0, 0); grid.addWidget(self.province_combo, 0, 1)
        grid.addWidget(QLabel('默认地市：'), 0, 2); grid.addWidget(self.city_combo, 0, 3)
        grid.addWidget(QLabel('默认搜索半径：'), 1, 0); grid.addWidget(self.radius_spin, 1, 1)
        grid.addWidget(QLabel('POI优先平台：'), 1, 2); grid.addWidget(self.provider_combo, 1, 3)
        grid.addWidget(QLabel('质检抽验规模：'), 2, 0); grid.addWidget(self.sample_spin, 2, 1)
        browse = QHBoxLayout(); browse.addWidget(self.golden_edit); browse.addWidget(self.golden_btn)
        grid.addWidget(QLabel('参考点文件：'), 2, 2); grid.addLayout(browse, 2, 3); layout.addWidget(defaults)

        village_group = QGroupBox('五级区划离线数据'); village = QHBoxLayout(village_group)
        village.addWidget(QLabel('导入当前省份的12位村级区划CSV：')); self.village_status = self._status_label(); village.addWidget(self.village_status, 1)
        self.import_village_btn = QPushButton('校验并导入')
        self.import_village_btn.clicked.connect(self._import_villages)
        village.addWidget(self.import_village_btn)
        layout.addWidget(village_group)

    def _load_config(self):
        cfg = load_config(); query = cfg.get('keys') or {}; map_keys = cfg.get('map_keys') or {}
        for name, _ in self.SOURCES:
            value = query.get(name, ''); self.query_key_edits[name].setText(value)
            if value: self._set_status(self.query_key_status[name], True, '已保存')
        for name, _ in self.MAP_FIELDS:
            value = map_keys.get(name, ''); self.map_key_edits[name].setText(value)
            if value: self._set_status(self.map_key_status[name], True, '已保存')
        self.reuse_tianditu.setChecked(bool(query.get('tianditu')) and map_keys.get('tianditu') == query.get('tianditu'))
        self._custom_sources = list((cfg.get('basemap') or {}).get('custom_sources') or [])
        self._refresh_tile_table(); self._refresh_basemap_combo(cfg)
        defaults = cfg.get('defaults') or {}; self._set_crs(defaults.get('output_crs', 'WGS84'))
        self.province_combo.setCurrentText(defaults.get('province', '广西壮族自治区')); self._on_province_changed(self.province_combo.currentText())
        self.city_combo.setCurrentText(defaults.get('city', '南宁市')); self.radius_spin.setValue(int(defaults.get('search_radius', 3000)))
        names = {'tianditu': '天地图', 'amap': '高德', 'baidu': '百度', 'tencent': '腾讯'}
        self.provider_combo.setCurrentText(names.get(defaults.get('preferred_provider', 'tianditu'), '天地图'))
        self.sample_spin.setValue(int(defaults.get('qc_sample_count', 500))); self.golden_edit.setText(defaults.get('golden_file', ''))

    def _current_cfg(self):
        cfg = load_config(); cfg['keys'] = {name: edit.text().strip() for name, edit in self.query_key_edits.items()}
        # 旧版浏览器端 Key 原样保留，避免升级时静默丢失；纯 Qt 地图不读取它们。
        map_keys = dict(cfg.get('map_keys') or {})
        map_keys.update({name: edit.text().strip() for name, edit in self.map_key_edits.items()})
        cfg['map_keys'] = map_keys
        if self.reuse_tianditu.isChecked(): cfg['map_keys']['tianditu'] = cfg['keys'].get('tianditu', '')
        cfg.setdefault('basemap', {})['custom_sources'] = list(self._custom_sources)
        active = self.basemap_combo.currentData()
        if active: cfg['basemap']['active_source'] = active
        return cfg

    def _save_config(self):
        cfg = self._current_cfg(); defaults = cfg.setdefault('defaults', {})
        defaults.update({'output_crs': self._selected_crs(), 'province': self.province_combo.currentText(),
                         'city': self.city_combo.currentText(), 'search_radius': self.radius_spin.value(),
                         'qc_sample_count': self.sample_spin.value(), 'golden_file': self.golden_edit.text().strip()})
        codes = {'天地图': 'tianditu', '高德': 'amap', '百度': 'baidu', '腾讯': 'tencent'}
        preferred = codes.get(self.provider_combo.currentText(), 'tianditu'); defaults['preferred_provider'] = preferred
        cfg['source_priority'] = [preferred] + [name for name, _ in self.SOURCES if name != preferred]
        save_config(cfg)
        from core.geo_service import clear_source_cache
        clear_source_cache(); self.keys_changed.emit()
        QMessageBox.information(self, '已保存', '查询KEY、地图KEY及含Token的自定义图源已使用Windows DPAPI加密保存。')

    def _refresh_basemap_combo(self, cfg=None):
        cfg = cfg or self._current_cfg(); current = (cfg.get('basemap') or {}).get('active_source', 'arcgis_hybrid')
        self.basemap_combo.clear()
        for source in available_tile_sources(cfg): self.basemap_combo.addItem(source['name'], source['id'])
        index = self.basemap_combo.findData(current); self.basemap_combo.setCurrentIndex(max(index, 0))

    def _refresh_tile_table(self):
        self.tile_table.setRowCount(len(self._custom_sources))
        for row, source in enumerate(self._custom_sources):
            values = [source.get('name', ''), source.get('kind', 'xyz').upper(), source.get('url', ''),
                      f"{source.get('min_zoom', 0)}–{source.get('max_zoom', 19)}", source.get('attribution', '')]
            for col, value in enumerate(values): self.tile_table.setItem(row, col, QTableWidgetItem(str(value)))

    def _add_custom_source(self):
        try:
            source = validate_tile_source({'id': f'custom_{uuid.uuid4().hex[:10]}', 'name': self.tile_name.text(),
                'url': self.tile_url.text(), 'kind': self.tile_kind.currentText().lower(),
                'min_zoom': self.tile_min_zoom.value(), 'max_zoom': self.tile_max_zoom.value(),
                'attribution': self.tile_attribution.text()})
        except ValueError as exc:
            QMessageBox.warning(self, '图源配置错误', str(exc)); return
        if self._editing_source is None:
            self._custom_sources.append(source)
        else:
            source['id'] = self._custom_sources[self._editing_source].get('id', source['id'])
            self._custom_sources[self._editing_source] = source
            self._editing_source = None; self.add_tile_btn.setText('添加图源'); styles.fit_button(self.add_tile_btn)
        self._refresh_tile_table(); self._refresh_basemap_combo()
        self.tile_name.clear(); self.tile_url.clear(); self.tile_attribution.clear()

    def _edit_custom_source(self):
        row = self.tile_table.currentRow()
        if row < 0: return
        source = self._custom_sources[row]; self._editing_source = row
        self.tile_name.setText(source.get('name', '')); self.tile_url.setText(source.get('url', ''))
        self.tile_kind.setCurrentText(source.get('kind', 'xyz').upper())
        self.tile_min_zoom.setValue(int(source.get('min_zoom', 0))); self.tile_max_zoom.setValue(int(source.get('max_zoom', 19)))
        self.tile_attribution.setText(source.get('attribution', '')); self.add_tile_btn.setText('保存修改'); styles.fit_button(self.add_tile_btn)

    def _remove_custom_source(self):
        row = self.tile_table.currentRow()
        if row < 0: return
        self._custom_sources.pop(row); self._editing_source = None; self.add_tile_btn.setText('添加图源'); styles.fit_button(self.add_tile_btn)
        self._refresh_tile_table(); self._refresh_basemap_combo()

    def _test_selected_basemap(self):
        source = source_by_id(self._current_cfg(), self.basemap_combo.currentData())
        if not source: self._set_status(self.basemap_status, False, '图源不存在'); return
        self.basemap_status.setText('测试中…'); worker = TileTestWorker(source)
        worker.result.connect(lambda ok, msg: self._set_status(self.basemap_status, ok, msg)); self._hold_worker(worker); worker.start()

    def _test_query_key(self, name):
        key = self.query_key_edits[name].text().strip()
        if not key: self._set_status(self.query_key_status[name], False, '请填写KEY'); return
        sources = build_sources(self._current_cfg()); self.query_key_status[name].setText('测试中…')
        worker = KeyTestWorker(name, sources[name]); worker.result.connect(self._on_query_test); self._hold_worker(worker); worker.start()

    def _test_map_key(self, name):
        key = self.map_key_edits[name].text().strip()
        if name == 'tianditu' and self.reuse_tianditu.isChecked(): key = self.query_key_edits['tianditu'].text().strip()
        if not key: self._set_status(self.map_key_status[name], False, '请填写KEY'); return
        self.map_key_status[name].setText('测试中…'); worker = MapKeyTestWorker(name, key, '')
        worker.result.connect(lambda _, ok, msg, n=name: self._set_status(self.map_key_status[n], ok, msg)); self._hold_worker(worker); worker.start()

    def _hold_worker(self, worker):
        self._workers.append(worker); worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)

    def _on_query_test(self, source_name, ok, message): self._set_status(self.query_key_status[source_name], ok, message)

    @staticmethod
    def _set_status(label, ok, message):
        detail = str(message or '')
        lower = detail.lower()
        if ok:
            short = '已保存' if '保存' in detail else '已导入' if '导入' in detail else '可用'
        elif '测试中' in detail:
            short = '测试中'
        elif any(token in lower for token in ('cloudwaf', 'http 418', 'http418', '网络', '连接失败', '域名')):
            short = '网络受限'
        elif any(token in detail for token in ('配额', '限流')):
            short = '配额不足'
        elif any(token in lower for token in ('key', '鉴权', '签名')) and '请填写' not in detail:
            short = 'KEY无效'
        elif '请填写' in detail:
            short = '未填写'
        else:
            short = '失败'
        label.setText(short); label.setToolTip(detail)
        label.setStyleSheet(f'color:{styles.SUCCESS if ok else styles.ERROR};font-size:12px;')

    def _open_apply(self, provider): QDesktopServices.openUrl(QUrl(self.APPLY_URLS[provider]))

    def _on_province_changed(self, province):
        current = self.city_combo.currentText(); self.city_combo.clear(); self.city_combo.addItems(CHINA_CITIES.get(province, []))
        if current: self.city_combo.setCurrentText(current)

    def _browse_golden(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择参考点文件', '', 'CSV文件 (*.csv)')
        if path: self.golden_edit.setText(path)

    def _import_villages(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择五级村级区划CSV', '', 'CSV文件 (*.csv)')
        if not path: return
        try:
            from core.village_import import import_village_csv
            result = import_village_csv(path, self.province_combo.currentText(), os.path.join(PROJECT_ROOT, 'data'))
        except Exception as exc:
            self._set_status(self.village_status, False, '导入失败'); QMessageBox.critical(self, '导入失败', str(exc)); return
        self._set_status(self.village_status, True, f'已导入 {result["count"]:,} 条')

    def _selected_crs(self):
        return 'CGCS2000' if self.rb_cgcs.isChecked() else 'GCJ-02' if self.rb_gcj.isChecked() else 'BD-09' if self.rb_bd.isChecked() else 'WGS84'

    def _set_crs(self, crs):
        {'CGCS2000': self.rb_cgcs, 'GCJ-02': self.rb_gcj, 'BD-09': self.rb_bd}.get(crs, self.rb_wgs).setChecked(True)

    def _reset(self):
        for edit in (*self.query_key_edits.values(), *self.map_key_edits.values()): edit.clear()
        self._custom_sources = []; self._refresh_tile_table(); self.rb_wgs.setChecked(True)
        self.province_combo.setCurrentText('广西壮族自治区'); self.city_combo.setCurrentText('南宁市')
        self.radius_spin.setValue(3000); self.provider_combo.setCurrentText('天地图'); self.sample_spin.setValue(500)
        self.golden_edit.clear()
        cfg = load_config(); cfg.setdefault('basemap', {})['custom_sources'] = []
        self._refresh_basemap_combo(cfg)
