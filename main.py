# -*- coding: utf-8 -*-
"""OCRA 程序入口

启动顺序刻意保持为：标准库原生自检 -> 真实导入 Qt/OpenCV -> 创建 QApplication -> 加载主窗口
这样即使打包后的 QtWidgets 底层 DLL 无法加载，也不会只出现 PyInstaller 英文异常框
"""
from __future__ import annotations

import multiprocessing
import sys

from core.startup_guard import (
    handle_unhandled_exception,
    install_exception_hook,
    run_startup_preflight,
    show_startup_failure,
)


def main() -> int:
    multiprocessing.freeze_support()
    install_exception_hook()

    preflight = run_startup_preflight()
    if preflight.has_errors:
        show_startup_failure(preflight)
        return 2

    try:
        from PyQt6.QtWidgets import QApplication
    except BaseException as exc:
        handle_unhandled_exception("导入 PyQt6.QtWidgets", exc)
        return 3

    try:
        app = QApplication(sys.argv)
    except BaseException as exc:
        handle_unhandled_exception("创建 Qt 图形界面", exc)
        return 4

    try:
        from ui.main_window import MainWindow

        window = MainWindow()
        window.show()
    except BaseException as exc:
        handle_unhandled_exception("加载 OCRA 主窗口", exc)
        return 5

    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
