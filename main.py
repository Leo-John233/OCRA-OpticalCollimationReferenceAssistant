# -*- coding: utf-8 -*-
"""OCRA 程序入口

启动顺序保持为标准库原生自检、导入 Qt 和 OpenCV、创建 QApplication、加载主窗口
这样即使打包后的 QtWidgets 底层 DLL 无法加载，也不会只出现 PyInstaller 英文异常框
"""
from __future__ import annotations

import multiprocessing
import sys

from core.startup_guard import (
    handle_unhandled_exception,
    install_exception_hook,
    resource_root,
    run_startup_preflight,
    show_startup_failure,
)


def configure_windows_app_identity() -> None:
    """设置 Windows 任务栏分组使用的应用标识"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("OCRA.PythonPro")
    except (AttributeError, OSError):
        pass


def main() -> int:
    """完成启动前检查并运行 Qt 应用事件循环"""
    multiprocessing.freeze_support()
    install_exception_hook()
    configure_windows_app_identity()

    preflight = run_startup_preflight()
    if preflight.has_errors:
        show_startup_failure(preflight)
        return 2

    try:
        from PyQt6.QtGui import QIcon
        from PyQt6.QtWidgets import QApplication
    except BaseException as exc:
        handle_unhandled_exception("导入 PyQt6", exc)
        return 3

    try:
        app = QApplication(sys.argv)
    except BaseException as exc:
        handle_unhandled_exception("创建 Qt 图形界面", exc)
        return 4

    app.setApplicationName("OCRA")
    app.setApplicationDisplayName("OCRA 光轴校准")

    application_icon = QIcon()
    for icon_path in [
        resource_root() / "OCRA_icon.png",
        resource_root() / "py_build" / "OCRA_icon.png",
    ]:
        if not icon_path.is_file():
            continue
        candidate_icon = QIcon(str(icon_path))
        if candidate_icon.isNull():
            continue
        application_icon = candidate_icon
        app.setWindowIcon(application_icon)
        break

    try:
        from ui.main_window import MainWindow

        window = MainWindow()
        if not application_icon.isNull():
            window.setWindowIcon(application_icon)
        window.show()
    except BaseException as exc:
        handle_unhandled_exception("加载 OCRA 主窗口", exc)
        return 5

    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
