# -*- coding: utf-8 -*-
# 程序入口创建 QApplication，加载主窗口，并启动 PyQt6 事件循环
import sys

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    """程序启动入口"""
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    # 用 SystemExit 返回 Qt 事件循环的退出码，方便命令行或打包程序识别退出状态
    raise SystemExit(main())
