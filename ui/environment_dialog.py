# -*- coding: utf-8 -*-
"""OCRA 环境检测报告对话框。"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout

from core.environment_check import EnvironmentReport


class EnvironmentCheckDialog(QDialog):
    """显示、复制并重新运行环境检测。"""

    rerun_requested = pyqtSignal()

    def __init__(self, report: EnvironmentReport, parent=None) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._report = report
        self.setModal(False)
        self.resize(820, 620)

        root = QVBoxLayout(self)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.report_edit = QTextEdit()
        self.report_edit.setReadOnly(True)
        self.report_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.report_edit.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        root.addWidget(self.report_edit, stretch=1)

        row = QHBoxLayout()
        row.addStretch(1)
        self.copy_button = QPushButton()
        self.rerun_button = QPushButton()
        self.close_button = QPushButton()
        self.copy_button.clicked.connect(self._copy_report)
        self.rerun_button.clicked.connect(self.rerun_requested.emit)
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.copy_button)
        row.addWidget(self.rerun_button)
        row.addWidget(self.close_button)
        root.addLayout(row)

        self.set_report(report)

    def set_report(self, report: EnvironmentReport) -> None:
        self._report = report
        is_en = report.language == "en"
        self.setWindowTitle("OCRA Environment Check" if is_en else "OCRA 环境检测")
        self.summary_label.setText(
            ("Environment check completed: " if is_en else "环境检测完成：") + report.summary_text()
        )
        self.report_edit.setPlainText(report.to_text())
        self.copy_button.setText("Copy Report" if is_en else "复制报告")
        self.rerun_button.setText("Run Again" if is_en else "重新检测")
        self.close_button.setText("Close" if is_en else "关闭")

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(self._report.to_text())
        self.copy_button.setText("Copied" if self._report.language == "en" else "已复制")
