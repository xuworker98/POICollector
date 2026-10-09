# -*- coding: utf-8 -*-
"""选项卡② 坐标转换：批量 WGS84 / CGCS2000 / GCJ-02 / BD-09 经纬度互转。

功能参考 TeleCoord 的批量转换：Excel/CSV 导入（自动识别编码）、
源/目标坐标系选择、后台线程批量转换 + 进度条、结果表格、导出/复制/清空。
仅做大地坐标（经纬度）4 种坐标系互转，不含平面坐标与七参数。
"""
import os
import shutil
import csv

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QGridLayout,
    QLabel, QLineEdit, QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
    QFileDialog, QMessageBox, QProgressBar, QHeaderView, QApplication,
)

from openpyxl import Workbook
from core.batch_pipeline import inspect_table, stream_coordinate_conversion

CRS_LIST = ['WGS84', 'CGCS2000', 'GCJ-02', 'BD-09']
CSV_ENCODINGS = ['utf-8-sig', 'gbk', 'gb2312', 'utf-8']


class ConvertWorker(QThread):
    """后台流式转换线程，完整数据不进入 UI 内存。"""
    progress = Signal(int, int)
    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, input_path, output_path, src_cs, dst_cs):
        super().__init__()
        self.input_path = input_path
        self.output_path = output_path
        self.src_cs = src_cs
        self.dst_cs = dst_cs
        self._cancelled = False

    def stop(self):
        self._cancelled = True

    def run(self):
        try:
            summary = stream_coordinate_conversion(
                self.input_path, self.output_path, self.src_cs, self.dst_cs,
                progress_cb=lambda done, total: self.progress.emit(done, total),
                cancel_cb=lambda: self._cancelled,
            )
            self.finished_ok.emit(summary)
        except Exception as exc:
            self.failed.emit(str(exc))


class TabCoord(QWidget):
    def __init__(self):
        super().__init__()
        self.input_path = ''
        self.input_count = 0
        self.current_results = []
        self.current_output = ''
        self.worker = None
        self._init_ui()

    # ------------------------------------------------------------------ UI
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setAlignment(Qt.AlignTop)

        # ---- 第1步：数据导入 ----
        step1 = QGroupBox('第1步：数据导入')
        s1 = QGridLayout()
        s1.setHorizontalSpacing(8)
        s1.addWidget(QLabel('文件路径：'), 0, 0)
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText('请选择 Excel（.xlsx / .xls）或 CSV（.csv）文件')
        s1.addWidget(self.file_edit, 0, 1)
        browse_btn = QPushButton('浏览…')
        browse_btn.clicked.connect(self._browse)
        s1.addWidget(browse_btn, 0, 2)
        template_btn = QPushButton('下载模板')
        template_btn.clicked.connect(self._download_template)
        s1.addWidget(template_btn, 0, 3)
        self.preview_label = QLabel('未加载数据')
        self.preview_label.setStyleSheet('color:#636e72; font-size:12px;')
        s1.addWidget(self.preview_label, 1, 0, 1, 4)
        step1.setLayout(s1)
        layout.addWidget(step1)

        # ---- 第2步：转换设置 ----
        step2 = QGroupBox('第2步：转换设置')
        s2 = QGridLayout()
        s2.setHorizontalSpacing(12)
        s2.addWidget(QLabel('源坐标系：'), 0, 0)
        self.src_combo = QComboBox()
        self.src_combo.addItems(CRS_LIST)
        self.src_combo.setCurrentText('WGS84')
        s2.addWidget(self.src_combo, 0, 1)
        s2.addWidget(QLabel('目标坐标系：'), 0, 2)
        self.dst_combo = QComboBox()
        self.dst_combo.addItems(CRS_LIST)
        self.dst_combo.setCurrentText('GCJ-02')
        s2.addWidget(self.dst_combo, 0, 3)
        s2.setColumnStretch(1, 1)
        s2.setColumnStretch(3, 1)
        step2.setLayout(s2)
        layout.addWidget(step2)

        # ---- 第3步：执行与结果 ----
        step3 = QGroupBox('第3步：执行与结果')
        s3 = QVBoxLayout()
        top_row = QHBoxLayout()
        top_row.addStretch()
        self.start_btn = QPushButton('▶ 开始转换')
        self.start_btn.clicked.connect(self._start)
        top_row.addWidget(self.start_btn)
        self.cancel_btn = QPushButton('取消')
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel)
        top_row.addWidget(self.cancel_btn)
        self.open_btn = QPushButton('打开文件夹')
        self.open_btn.clicked.connect(self._open_folder)
        top_row.addWidget(self.open_btn)
        top_row.addStretch()
        s3.addLayout(top_row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        s3.addWidget(self.progress)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['点位名称', '源经度', '源纬度', '目标经度', '目标纬度', '状态'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        s3.addWidget(self.table)

        export_row = QHBoxLayout()
        export_row.addStretch()
        self.export_btn = QPushButton('导出结果')
        self.export_btn.clicked.connect(self._export)
        self.copy_btn = QPushButton('复制全部')
        self.copy_btn.clicked.connect(self._copy_all)
        self.clear_btn = QPushButton('清空表格')
        self.clear_btn.clicked.connect(self._clear)
        export_row.addWidget(self.export_btn)
        export_row.addWidget(self.copy_btn)
        export_row.addWidget(self.clear_btn)
        s3.addLayout(export_row)
        step3.setLayout(s3)
        layout.addWidget(step3, 1)

    # ------------------------------------------------------------- 数据导入
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, '选择文件', '',
            '表格文件 (*.xlsx *.xls *.csv);;Excel 文件 (*.xlsx *.xls);;CSV 文件 (*.csv)')
        if path:
            self.file_edit.setText(path)
            self._load_data()

    def _load_data(self):
        path = self.file_edit.text().strip()
        if not path:
            QMessageBox.warning(self, '提示', '请先选择文件')
            return
        ext = os.path.splitext(path)[1].lower()
        try:
            info = inspect_table(path)
        except Exception as e:
            QMessageBox.critical(self, '读取失败', str(e))
            return

        headers = [str(h).strip() for h in info['headers']]
        required = ['点位名称', '源经度', '源纬度']
        for col in required:
            if col not in headers:
                QMessageBox.critical(self, '格式错误', f'文件必须包含列：{", ".join(required)}')
                return
        self.input_path = path
        self.input_count = int(info['count'])
        self.preview_label.setText(f'已识别 {self.input_count:,} 条记录；转换时流式读取，不占用大内存')

    def _download_template(self):
        path, _ = QFileDialog.getSaveFileName(
            self, '保存模板', '坐标转换模板.xlsx',
            'Excel 文件 (*.xlsx);;CSV 文件 (*.csv)')
        if not path:
            return
        header = ['点位名称', '源经度', '源纬度']
        sample = [['基站A', 113.123456, 23.123456], ['基站B', 113.234567, 23.234567]]
        try:
            if path.lower().endswith('.csv'):
                with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                    w = csv.writer(f)
                    w.writerow(header)
                    w.writerows(sample)
            else:
                wb = Workbook()
                ws = wb.active
                ws.append(header)
                for s in sample:
                    ws.append(s)
                wb.save(path)
            QMessageBox.information(self, '成功', f'模板已保存：{path}')
        except Exception as e:
            QMessageBox.critical(self, '失败', str(e))

    # --------------------------------------------------------------- 转换
    def _start(self):
        if not self.input_path:
            QMessageBox.warning(self, '无数据', '请先选择并打开数据文件')
            return
        src = self.src_combo.currentText()
        dst = self.dst_combo.currentText()
        if src == dst:
            QMessageBox.information(self, '提示', '源坐标系与目标坐标系相同，无需转换')
            return

        output_path, _ = QFileDialog.getSaveFileName(
            self, '保存转换结果', f'坐标转换_{src}转{dst}_{__import__("datetime").datetime.now().strftime("%Y%m%d_%H%M%S")}_V2.0.xlsx',
            'Excel 文件 (*.xlsx);;CSV 文件 (*.csv)')
        if not output_path:
            return

        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self.worker = ConvertWorker(self.input_path, output_path, src, dst)
        self.worker.progress.connect(
            lambda done, total: self.progress.setValue(int(done / max(total, 1) * 100)))
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_finished(self, summary):
        results = summary['preview']
        self.current_results = results
        self.current_output = summary['output_path']
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(results))
        for i, row in enumerate(results):
            for column, value in enumerate(row):
                self.table.setItem(i, column, QTableWidgetItem('' if value is None else str(value)))
        self.table.setUpdatesEnabled(True)
        self.progress.setVisible(False)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.preview_label.setText(
            f'转换完成：成功 {summary["success"]:,} 条，失败 {summary["failed"]:,} 条；'
            f'界面仅预览前 {len(results)} 条')

    def _on_failed(self, message):
        self.progress.setVisible(False)
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        QMessageBox.critical(self, '转换失败', message)

    # --------------------------------------------------------------- 导出
    def _export(self):
        if not self.current_output or not os.path.exists(self.current_output):
            QMessageBox.warning(self, '无数据', '没有可导出的结果')
            return
        path, _ = QFileDialog.getSaveFileName(
            self, '另存结果', f'转换结果_导出{os.path.splitext(self.current_output)[1]}',
            'Excel 文件 (*.xlsx)' if self.current_output.lower().endswith('.xlsx') else 'CSV 文件 (*.csv)')
        if not path:
            return
        try:
            if os.path.abspath(path) == os.path.abspath(self.current_output):
                QMessageBox.information(self, '提示', '结果已保存在该路径，无需重复复制。')
                return
            shutil.copy2(self.current_output, path)
            QMessageBox.information(self, '成功', f'结果已导出：{path}')
        except Exception as e:
            QMessageBox.critical(self, '导出失败', str(e))

    def _copy_all(self):
        if not self.current_results:
            QMessageBox.information(self, '提示', '没有可复制的数据')
            return
        text = '\n'.join([','.join('' if r is None else str(r) for r in row)
                          for row in self.current_results])
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, '已复制', '表格全部内容已复制到剪贴板')

    def _clear(self):
        self.table.setRowCount(0)
        self.current_results.clear()
        self.current_output = ''
        self.preview_label.setText('已清空结果')

    def _cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.preview_label.setText('正在取消；已完成结果将保留')

    def _open_folder(self):
        path = os.path.dirname(self.current_output) if self.current_output else os.path.join(os.getcwd(), 'output')
        os.makedirs(path, exist_ok=True)
        subprocess = __import__('subprocess')
        subprocess.Popen(['explorer', path])
