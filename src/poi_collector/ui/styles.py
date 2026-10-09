# -*- coding: utf-8 -*-
"""全局样式与色板（参考 PlanLayerCreator 界面设计规范，蓝色系）"""

# 基础色板
PRIMARY = '#0984e3'
PRIMARY_HOVER = '#0773c5'
PRIMARY_PRESSED = '#065ea8'
DISABLED = '#b2bec3'

# 中性色
WINDOW_BG = '#f5f6fa'
CONTENT_BG = '#ffffff'
BORDER = '#dcdde1'
TEXT = '#2d3436'
TEXT_SECONDARY = '#636e72'
TAB_BG = '#dfe6e9'

# 状态色
SUCCESS = '#00b894'
WARNING = '#f5a623'
ERROR = '#dc3545'

# 日志区（浅色底深字，等宽字体）
LOG_BG = '#F5F9FC'
LOG_TEXT = '#2d3436'
LOG_SUCCESS = '#18864b'
LOG_WARNING = '#b86b00'
LOG_ERROR = '#c0392b'

FONT_FAMILY = 'Microsoft YaHei UI'

QSS = f"""
QMainWindow {{ background: {WINDOW_BG}; }}
QWidget {{ font-family: {FONT_FAMILY}; font-size: 14px; color: {TEXT}; }}
QLabel[role="muted"] {{ color: {TEXT_SECONDARY}; font-size: 12px; }}
QLabel[role="section"] {{ color: {TEXT}; font-size: 14px; font-weight: 700; padding-top: 2px; }}

QGroupBox {{
    font-weight: bold;
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 8px;
    padding-top: 16px;
    background-color: {CONTENT_BG};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {TEXT};
}}

QPushButton {{
    background: {PRIMARY};
    color: white;
    border: none;
    border-radius: 5px;
    min-height: 28px;
    max-height: 28px;
    padding: 0 13px;
}}
QPushButton:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton:pressed {{ background: {PRIMARY_PRESSED}; }}
QPushButton:disabled {{ background: {DISABLED}; }}
QPushButton[kind="secondary"] {{
    background: #ffffff;
    color: {PRIMARY};
    border: 1px solid {PRIMARY};
}}
QPushButton[kind="secondary"]:hover {{ background: #eef7ff; }}

QComboBox, QLineEdit, QSpinBox {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    min-height: 28px;
    max-height: 28px;
    padding: 0 8px;
    background: {CONTENT_BG};
    color: {TEXT};
}}
QTextEdit {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 8px;
    background: {CONTENT_BG};
    color: {TEXT};
}}
QComboBox::drop-down {{ width: 24px; border: none; }}
QComboBox:hover {{ border-color: {PRIMARY}; }}
QComboBox QAbstractItemView {{
    background: white;
    color: {TEXT};
    selection-background-color: {PRIMARY};
    selection-color: white;
    outline: none;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-top: none;
    border-bottom-left-radius: 7px;
    border-bottom-right-radius: 7px;
    background: {CONTENT_BG};
    top: 0;
}}
QTabBar::tab {{
    background: #eef2f6;
    min-height: 32px;
    padding: 0 18px;
    margin-right: 6px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
}}
QTabBar::tab:selected {{
    background: {CONTENT_BG};
    font-weight: bold;
    color: {PRIMARY};
    border-color: #b8d9f4;
}}
QTabBar::tab:hover:!selected {{ background: #e3edf6; color: {PRIMARY}; }}

QRadioButton[segment="true"] {{
    spacing: 0;
    min-height: 34px;
    padding: 0 14px;
    border: 1px solid {BORDER};
    background: #f8fafc;
}}
QRadioButton[segment="true"]::indicator {{ width: 0; height: 0; }}
QRadioButton[segment="true"]:checked {{
    color: white;
    background: {PRIMARY};
    border-color: {PRIMARY};
    font-weight: bold;
}}

QFrame[card="true"] {{
    background: {CONTENT_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ width: 8px; margin: 0; background: transparent; }}
QScrollBar:horizontal {{ height: 8px; margin: 0; background: transparent; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: #b8c2cc; border-radius: 4px; min-height: 24px; min-width: 24px;
}}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{ background: #8f9eab; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; background: none; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; background: none; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

QProgressBar {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
    height: 18px;
    background: {CONTENT_BG};
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 3px; }}

QStatusBar {{ background: {TAB_BG}; color: {TEXT}; font-size: 12px; }}
QSplitter::handle {{ background: #e8edf2; }}
QSplitter::handle:hover {{ background: {PRIMARY}; }}
QSplitter::handle:horizontal {{ width: 4px; }}
QSplitter::handle:vertical {{ height: 4px; }}
QToolTip {{ background:#ffffff; color:{TEXT}; border:1px solid {BORDER}; padding:5px; }}

QTableWidget, QTableView {{
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {CONTENT_BG};
    gridline-color: {BORDER};
}}
QTableView::item {{ padding: 4px; }}
QTableView::item:selected {{ background: #dbeeff; color: {TEXT}; }}
QHeaderView::section {{
    background: {TAB_BG};
    padding: 4px 8px;
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    font-weight: bold;
}}
"""


def fit_button(button, horizontal_padding=28):
    """按真实样式提示计算紧凑宽度，避免高 DPI 下文字被截断。"""
    from PySide6.QtWidgets import QSizePolicy
    if button.property('fill'):
        return
    text_width = button.fontMetrics().boundingRect(button.text()).width()
    icon_width = button.iconSize().width() + 6 if not button.icon().isNull() else 0
    required = max(58, text_width + icon_width + horizontal_padding,
                   button.sizeHint().width() + 6)
    button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    button.setMinimumWidth(required)
    button.setMaximumWidth(required)


def fit_all_buttons(root, horizontal_padding=28):
    """统一处理当前容器内全部按钮；动态改文案后应再次调用。"""
    from PySide6.QtWidgets import QPushButton
    for button in root.findChildren(QPushButton):
        fit_button(button, horizontal_padding)

# 日志区深色样式（等宽字体）
LOG_QSS = f"""
QTextEdit {{
    background: {LOG_BG};
    color: {LOG_TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    font-family: Consolas, 'Courier New', monospace;
    font-size: 12px;
    padding: 6px;
}}
"""
