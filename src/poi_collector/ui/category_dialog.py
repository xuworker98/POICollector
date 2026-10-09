# -*- coding: utf-8 -*-
"""分类树三栏选择器（模态弹窗）：大类 → 中类 → 小类（多选，跨中类累积）"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QPushButton,
)

from core import category


class CategoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('选择 POI 分类')
        self.resize(720, 460)
        self.categories = category.load_categories()
        self._selected = {}  # 累积选中的小类码 -> 名称
        self._init_ui()
        self._load_top_categories()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # 三栏
        columns = QHBoxLayout()
        columns.setSpacing(8)

        left = QVBoxLayout()
        left.addWidget(QLabel('① 大类（23）'))
        self.top_list = QListWidget()
        left.addWidget(self.top_list)

        mid = QVBoxLayout()
        mid.addWidget(QLabel('② 中类'))
        self.mid_list = QListWidget()
        mid.addWidget(self.mid_list)

        right = QVBoxLayout()
        right.addWidget(QLabel('③ 小类（可多选）'))
        self.leaf_list = QListWidget()
        self.leaf_list.setSelectionMode(QListWidget.MultiSelection)
        right.addWidget(self.leaf_list)

        columns.addLayout(left, 1)
        columns.addLayout(mid, 1)
        columns.addLayout(right, 1)
        layout.addLayout(columns, 1)

        # 已选提示
        self.selected_label = QLabel('已选 0 个小类')
        self.selected_label.setWordWrap(True)
        layout.addWidget(self.selected_label)

        # 提示 + 按钮
        hint = QLabel('提示：可跨中类选择多个小类；系统会自动转换为各地图平台支持的查询参数。')
        hint.setStyleSheet('color:#636e72; font-size:12px;')
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        clear_btn = QPushButton('清空')
        clear_btn.clicked.connect(self._clear)
        ok_btn = QPushButton('确定选择')
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        # 联动
        self.top_list.currentItemChanged.connect(self._on_top_changed)
        self.mid_list.currentItemChanged.connect(self._on_mid_changed)
        self.leaf_list.itemSelectionChanged.connect(self._sync_selected)

    def _load_top_categories(self):
        for cat in self.categories:
            item = QListWidgetItem(cat['name'])
            item.setData(Qt.UserRole, cat['code'])
            self.top_list.addItem(item)

    def _on_top_changed(self, current, _prev):
        if not current:
            return
        node = category.find_node(self.categories, current.data(Qt.UserRole))
        self.mid_list.clear()
        self.leaf_list.clear()
        for child in node.get('children', []):
            item = QListWidgetItem(child['name'])
            item.setData(Qt.UserRole, child['code'])
            self.mid_list.addItem(item)

    def _on_mid_changed(self, current, _prev):
        if not current:
            return
        node = category.find_node(self.categories, current.data(Qt.UserRole))
        self.leaf_list.blockSignals(True)
        self.leaf_list.clear()
        for child in node.get('children', []):
            item = QListWidgetItem(child['name'])
            item.setData(Qt.UserRole, child['code'])
            if child['code'] in self._selected:
                item.setSelected(True)
            self.leaf_list.addItem(item)
        self.leaf_list.blockSignals(False)

    def _sync_selected(self):
        """同步当前小类列表的选择到累积集合（含取消）。"""
        for i in range(self.leaf_list.count()):
            item = self.leaf_list.item(i)
            code = item.data(Qt.UserRole)
            if item.isSelected():
                self._selected[code] = item.text()
            elif code in self._selected:
                del self._selected[code]
        self._update_label()

    def _update_label(self):
        codes = list(self._selected.keys())
        types = category.types_param(codes)
        self.selected_label.setText(f'已选 {len(codes)} 个小类 · 高德码：{types}')

    def _clear(self):
        self._selected.clear()
        self.leaf_list.blockSignals(True)
        self.leaf_list.clearSelection()
        self.leaf_list.blockSignals(False)
        self._update_label()

    def get_selected_codes(self):
        return list(self._selected.keys())

    def get_result(self):
        """返回已选择的小类编码。"""
        return self.get_selected_codes()
