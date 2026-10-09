from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QGroupBox, QPushButton, QVBoxLayout

from ui.main_window import MainWindow


def make_window():
    app = QApplication.instance() or QApplication([])
    return MainWindow()


def test_main_window_size_and_version():
    window = make_window()
    assert window.minimumWidth() == 1024
    assert window.minimumHeight() == 630
    assert 'V2.0' in window.windowTitle()
    window.close()


def test_key_grid_is_two_rows_by_two_panels():
    window = make_window()
    grid = window.tab_config.key_edits['tianditu'].parentWidget().layout()
    positions = {name: grid.getItemPosition(grid.indexOf(edit))[:2]
                 for name, edit in window.tab_config.key_edits.items()}
    assert positions == {'tianditu': (1, 1), 'amap': (1, 6),
                         'baidu': (2, 1), 'tencent': (2, 6)}
    window.close()


def test_main_window_has_five_tabs_and_single_poi_workspace():
    window = make_window()
    assert window.tabs.count() == 5
    assert [window.tabs.tabText(i) for i in range(5)] == [
        'POI数据查询', '坐标系转换', '地址坐标互转', '基本设置', '使用帮助']
    collect = window.tab_collect
    assert not hasattr(collect, 'preview')
    assert not hasattr(collect, 'content_tabs')
    assert collect.workspace_splitter.count() == 2
    assert collect.map_widget is not None
    assert collect.btn_export.text() == '导出结果'
    window.close()


def test_query_modes_have_no_keyword_controls():
    window = make_window()
    collect = window.tab_collect
    assert collect.rb_text.text() == '分类搜索'
    assert not hasattr(collect, 'text_keyword')
    assert not hasattr(collect, 'around_keyword')
    collect.rb_text.setChecked(True)
    assert collect.advanced_title.text() == '4. 高级选项'
    collect.rb_around.setChecked(True)
    assert collect.advanced_title.text() == '5. 高级选项'
    assert collect.around_center.isReadOnly()
    window.close()


def test_successful_result_stays_on_map_and_enables_export():
    window = make_window()
    result = {'mode': 'poi', 'province': '广西壮族自治区', 'matched': 1, 'nodes': [
        {'省份': '广西壮族自治区', '地市': '南宁市', '区县': '青秀区', 'name': '测试点',
         'type': '测试', 'lon': 108.3, 'lat': 22.8, 'address': '测试地址', '来源': '测试',
         '置信度': '高', 'adcode': '450103', 'typecode': '000000'}], 'qc': {}}
    window.tab_collect._on_finished(result)
    assert window.tab_collect.last_result is result
    assert window.tab_collect.btn_export.isEnabled()
    assert '1' in window.tab_collect.queried_label.text()
    window.close()


def test_map_bounds_fill_around_inputs(monkeypatch):
    window = make_window()
    collect = window.tab_collect
    monkeypatch.setattr(collect, '_reverse_center', lambda *_args: None)
    collect._accept_map_bounds(108.30, 22.80, 108.40, 22.90)
    assert collect.rb_around.isChecked()
    assert collect.center_lon.text() == '108.350000'
    assert collect.center_lat.text() == '22.850000'
    assert int(collect.around_radius.text()) > 100
    window.close()


def test_native_map_center_button_and_bounds_signal_reach_query_form(monkeypatch):
    window = make_window()
    collect = window.tab_collect
    calls = []
    monkeypatch.setattr(collect, '_reverse_center', lambda lon, lat: calls.append((lon, lat)))
    collect.map_widget.set_center(108.366, 22.817, 13)
    collect.map_widget._request_center()
    assert collect.center_lon.text() == '108.366000'
    assert collect.center_lat.text() == '22.817000'
    assert calls[-1] == (108.366, 22.817)
    collect.map_widget.bounds_selected.emit(108.30, 22.80, 108.40, 22.90)
    assert collect.center_lon.text() == '108.350000'
    assert collect.center_lat.text() == '22.850000'
    assert len(calls) == 2
    window.close()


def test_compact_control_rhythm_and_scrollbars():
    window = make_window()
    from ui import styles
    assert 'min-height: 28px' in styles.QSS
    assert 'max-height: 28px' in styles.QSS
    assert 'QScrollBar:vertical { width: 8px' in styles.QSS
    assert 'QScrollBar::add-line:vertical' in styles.QSS
    window.close()


def test_help_content_indent_and_feedback_card():
    window = make_window()
    html = window.tab_help.browser.toHtml()
    assert 'V2.0' in html and '分类搜索' in html
    assert 'POI数据预览' not in html and '关键字搜索' not in html
    source_html = window.tab_help._html()
    assert '<h2>软件名称</h2>' not in source_html
    assert '中文名称：通信工程POI数据采集器' not in source_html
    for title in ('软件简介', '功能特点', 'KEY申请', '操作说明', '注意事项', '问题反馈'):
        assert f'<h2>{title}</h2>' in source_html
    assert '行政区划查询示例' not in source_html
    assert '输出、网络与质量说明' not in source_html
    assert all(link in source_html for link in (
        'cloudcenter.tianditu.gov.cn', 'console.amap.com',
        'lbsyun.baidu.com/apiconsole/key', 'lbs.qq.com/dev/console',
    ))
    assert not hasattr(window.tab_help, 'qr_label')
    indented = []
    block = window.tab_help.browser.document().begin()
    while block.isValid():
        if block.text().startswith((
            '通信工程POI数据采集器面向',
            '软件将查询服务与地图底图分开管理',
            '本软件使用的是服务端查询接口',
        )):
            indented.append(block.blockFormat().textIndent())
        block = block.next()
    assert indented == [28.0, 28.0, 28.0]
    table_indents = []
    block = window.tab_help.browser.document().begin()
    while block.isValid():
        cursor = window.tab_help.browser.textCursor()
        cursor.setPosition(block.position())
        if cursor.currentTable() is not None and block.text().strip():
            table_indents.append(block.blockFormat().textIndent())
        block = block.next()
    assert table_indents and set(table_indents) == {0.0}
    assert 'github.com/xuworker98/POICollector/issues' in window.tab_help.contact_info.text()
    window.close()


def test_map_toolbar_buttons_show_complete_text():
    window = make_window()
    window.resize(1400, 800)
    window.show()
    QApplication.processEvents()
    map_widget = window.tab_collect.map_widget
    for button in (map_widget._locate, map_widget._box, map_widget._layers, map_widget._fit):
        assert button.property('mapAction') is True
        assert button.size().width() == 92 and button.size().height() == 58
        assert button.toolButtonStyle() == Qt.ToolButtonTextUnderIcon
        assert not button.icon().isNull(), button.text()
        assert button.sizeHint().width() <= button.width(), button.text()
        assert '\n' not in button.text()
    for button in (map_widget._zoom_in, map_widget._zoom_out):
        assert button.property('mapCompact') is True
        assert button.size().width() == 40 and button.size().height() == 30
        assert button.toolButtonStyle() == Qt.ToolButtonIconOnly
        assert button.iconSize().width() == 16 and button.iconSize().height() == 16
        assert not button.icon().isNull(), button.text()
        left_space = button.x()
        right_space = map_widget._toolbar.width() - button.geometry().right() - 1
        assert abs(left_space - right_space) <= 1, (left_space, right_space)
    assert map_widget._toolbar.sizeHint().width() >= map_widget._locate.width() + 10
    window.close()


def test_config_labels_are_clean_and_network_hint_removed():
    window = make_window()
    text = ' '.join(label.text() for label in window.tab_config.findChildren(QLabel))
    assert '两行两列' not in window.tab_config.findChild(QGroupBox).title()
    assert '掩码显示' not in text and '连接提示' not in text
    assert window.tab_config.sections.count() == 3
    window.close()


def test_buttons_fit_text_without_clipping():
    window = make_window()
    for button in window.findChildren(QPushButton):
        if not button.property('fill'):
            required = button.fontMetrics().boundingRect(button.text()).width() + 28
            assert button.minimumWidth() >= required, button.text()
    assert window.tab_collect.status_card.height() == 56
    window.close()


def test_map_uses_pure_qt_and_native_selection_signals():
    window = make_window()
    map_widget = window.tab_collect.map_widget
    state = map_widget.diagnostic_state()
    assert state['engine'] == 'pure-qt-xyz'
    assert map_widget.metaObject().className() == 'LeafletMapWidget'
    assert not hasattr(map_widget, 'page')
    assert len(window.tab_config.map_key_edits) == 1
    assert 'tianditu' in window.tab_config.map_key_edits
    assert isinstance(map_widget._toolbar.layout(), QVBoxLayout)
    assert [map_widget._toolbar.layout().itemAt(i).widget().text() for i in range(6)] == [
        '+', '−', '定位中心', '框选范围', '地图切换', '显示全部']
    window.close()


def test_long_around_categories_expand_inside_scrollable_parameter_panel():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    collect = window.tab_collect
    collect.rb_around.setChecked(True)
    app.processEvents()
    short_height = collect.task_stack.height()
    collect.around_cat_label.setText('、'.join(f'分类{i}' for i in range(80)))
    collect._refresh_task_stack_height()
    app.processEvents()
    assert collect.task_stack.height() > short_height
    assert collect.side_scroll.verticalScrollBarPolicy().name == 'ScrollBarAsNeeded'
    window.close()
