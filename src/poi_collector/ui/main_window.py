# -*- coding: utf-8 -*-
"""主窗口：五个工作页 + 底部状态栏。"""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QTabWidget, QLabel, QStatusBar

from core.config import resource_path
from ui import styles
from ui.tabs.tab_collect import TabCollect
from ui.tabs.tab_coord import TabCoord
from ui.tabs.tab_addr_geocode import TabAddrGeocode
from ui.tabs.tab_config import TabConfig
from ui.tabs.tab_help import TabHelp


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('通信工程POI数据采集器（POICollector）V2.0')
        self.setMinimumSize(1024, 630)
        self.resize(1024, 630)
        self._set_app_icon()

        # 中央选项卡容器
        self.tabs = QTabWidget()
        self.tab_collect = TabCollect()
        self.tab_coord = TabCoord()
        self.tab_addr_geocode = TabAddrGeocode()
        self.tab_config = TabConfig()
        self.tab_help = TabHelp()

        self.tabs.addTab(self.tab_collect, 'POI数据查询')
        self.tabs.addTab(self.tab_coord, '坐标系转换')
        self.tabs.addTab(self.tab_addr_geocode, '地址坐标互转')
        self.tabs.addTab(self.tab_config, '基本设置')
        self.tabs.addTab(self.tab_help, '使用帮助')

        self.setCentralWidget(self.tabs)

        # 底部状态栏：左 = 状态灯 + 进度文字，右 = 公开版本反馈入口
        self._build_status_bar()

        # 跨选项卡信号：基本配置保存 KEY 后，采集中心可感知
        self.tab_config.keys_changed.connect(self.tab_collect.on_keys_changed)
        # 样式加载后统一按文字自动定宽；覆盖“校验并导入”等所有页面按钮。
        styles.fit_all_buttons(self)

    def _set_app_icon(self):
        icon_path = resource_path('icon.ico')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def _build_status_bar(self):
        status = QStatusBar()
        self.status_light = QLabel('●')
        self.status_light.setStyleSheet(f'color: {styles.TEXT_SECONDARY}; font-size: 14px;')
        self.status_text = QLabel('空闲')
        self.status_text.setStyleSheet(f'color: {styles.TEXT};')

        status.addWidget(self.status_light)
        status.addWidget(self.status_text, 1)  # 1 = 占满剩余空间

        self.contact_label = QLabel('POICollector V2.0 | 问题请通过 GitHub Issues 反馈')
        self.contact_label.setStyleSheet(f'color: {styles.PRIMARY}; font-weight: 500;')
        status.addPermanentWidget(self.contact_label)  # 右侧固定

        self.setStatusBar(status)

    # ---- 状态栏更新接口（供 workers / tabs 调用）----
    def set_status(self, text, light='idle'):
        """light: idle(灰) / running(绿) / retry(黄) / error(红)"""
        color = {
            'idle': styles.TEXT_SECONDARY,
            'running': styles.SUCCESS,
            'retry': styles.WARNING,
            'error': styles.ERROR,
        }.get(light, styles.TEXT_SECONDARY)
        self.status_light.setStyleSheet(f'color: {color}; font-size: 14px;')
        self.status_text.setText(text)
