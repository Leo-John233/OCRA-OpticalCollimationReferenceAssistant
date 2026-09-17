"""验证 USB 手动对焦滑条与配置和自动对焦状态的联动"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from core.app_state import AppConfig
from ui.main_window import DampedSlider, MainWindow


class ManualFocusControlTests(unittest.TestCase):
    """不连接硬件，检查真实窗口中的焦点控件"""

    @classmethod
    def setUpClass(cls) -> None:
        """整个测试进程只创建一个 Qt 应用"""
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        """隔离配置文件读写和相机探测，避免修改用户参数"""
        config = AppConfig(camera_type="usb", camera_auto_focus=False, camera_focus=100)
        patches = [
            patch("ui.main_window.ConfigManager.load", return_value=config),
            patch("ui.main_window.ConfigManager.save"),
            patch.object(MainWindow, "refresh_camera_devices"),
            patch.object(MainWindow, "start_camera"),
            patch.object(MainWindow, "_collect_environment_report", return_value=MagicMock(has_errors=False)),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.close)

    def test_style_range_and_initial_value(self) -> None:
        """沿用现有滑条样式和整数焦点范围"""
        self.assertIsInstance(self.window.focus_slider, DampedSlider)
        self.assertEqual(self.window.focus_slider.orientation(), Qt.Orientation.Horizontal)
        for control in (self.window.focus_slider, self.window.focus_spin):
            self.assertEqual((control.minimum(), control.maximum(), control.value()), (0, 1023, 100))
        self.assertEqual(self.window.focus_spin.width(), self.window.h_offset_value.width())
        self.assertEqual(self.window.focus_label.text(), "手动焦点")

    def test_slider_updates_input_and_config(self) -> None:
        """拖动滑条后同步数值输入框和业务参数"""
        self.window.focus_slider.setValue(420)
        self.assertEqual(self.window.focus_spin.value(), 420)
        self.assertEqual(self.window.config.camera_focus, 420)

    def test_input_updates_slider_and_config(self) -> None:
        """输入整数时同步滑条并保持取值边界"""
        self.window.focus_spin.setValue(1023)
        self.assertEqual(self.window.focus_slider.value(), 1023)
        self.assertEqual(self.window.config.camera_focus, 1023)
        self.window.focus_spin.setValue(-1)
        self.assertEqual(self.window.focus_slider.value(), 0)
        self.assertEqual(self.window.config.camera_focus, 0)

    def test_autofocus_disables_both_controls(self) -> None:
        """自动对焦切换时两个手动控件同时禁用或恢复"""
        self.window.auto_focus_check.setChecked(True)
        self.assertTrue(self.window.config.camera_auto_focus)
        self.assertFalse(self.window.focus_slider.isEnabled())
        self.assertFalse(self.window.focus_spin.isEnabled())
        self.window.auto_focus_check.setChecked(False)
        self.assertTrue(self.window.focus_slider.isEnabled())
        self.assertTrue(self.window.focus_spin.isEnabled())
        self.assertEqual(self.window.focus_slider.value(), 100)

    def test_reload_updates_both_controls_and_autofocus(self) -> None:
        """重载配置不会遗留旧的滑条值或禁用状态"""
        config = AppConfig(camera_type="usb", camera_auto_focus=True, camera_focus=600)
        with patch.object(self.window.config_manager, "load", return_value=config):
            self.window.load_parameters()
        self.assertEqual(self.window.focus_spin.value(), 600)
        self.assertEqual(self.window.focus_slider.value(), 600)
        self.assertFalse(self.window.focus_slider.isEnabled())
        self.assertFalse(self.window.focus_spin.isEnabled())

    def test_slider_reuses_debounced_camera_update(self) -> None:
        """手动焦点变动沿用防抖更新，不重新启动相机"""
        thread = MagicMock()
        thread.isRunning.return_value = True
        self.window.thread = thread
        self.window.focus_slider.setValue(350)
        self.assertTrue(self.window._camera_param_timer.isActive())
        self.window._apply_camera_params_debounced()
        thread.request_camera_controls.assert_called_once_with(50.0, 100, 400, False, False, 350)
        thread.stop.assert_not_called()

    def test_save_parameters_uses_slider_value(self) -> None:
        """保存配置时仍保存标准整数 camera_focus 字段"""
        self.window.focus_slider.setValue(750)
        self.window.save_parameters()
        self.window.config_manager.save.assert_called_once_with(self.window.config)
        self.assertEqual(self.window.config.camera_focus, 750)


if __name__ == "__main__":
    unittest.main()
