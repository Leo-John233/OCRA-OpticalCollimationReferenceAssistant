# -*- coding: utf-8 -*-
# 程序入口先执行最小依赖检查，再创建 QApplication 和主窗口
from __future__ import annotations

import sys

from core.environment_check import bootstrap_dependency_errors, format_bootstrap_error, show_bootstrap_error


def main() -> int:
    """程序启动入口。"""
    dependency_errors = bootstrap_dependency_errors()
    if dependency_errors:
        show_bootstrap_error(format_bootstrap_error(dependency_errors))
        return 2

    # 依赖检查通过后再导入第三方 GUI 与完整业务模块。
    from PyQt6.QtWidgets import QApplication

    from ui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    # 用 SystemExit 返回 Qt 事件循环的退出码，方便命令行或打包程序识别退出状态
    raise SystemExit(main())
