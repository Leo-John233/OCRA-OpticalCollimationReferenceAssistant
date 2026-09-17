"""验证打包依赖检查能拦截漏收集和放错位置的 DLL"""
from __future__ import annotations

import unittest

from build_runtime import find_missing_dependencies, normalize_name


class RuntimeDependencyTests(unittest.TestCase):
    """覆盖 Conda 底层依赖及 Windows 和 Qt 的特殊搜索规则"""

    def check_missing(self, imports, bundled=(), system=(), private=()):
        """使用明确的文件集合隔离开发机环境影响"""
        return find_missing_dependencies(imports, set(bundled), set(system), set(private))

    def test_missing_ffi_is_rejected(self):
        """回归截图中的 ctypes 启动故障"""
        self.assertEqual(self.check_missing({"_ctypes.pyd": {"ffi-8.dll"}}), [("_ctypes.pyd", "ffi-8.dll")])

    def test_transitive_missing_dependency_is_rejected(self):
        """DLL 自身依赖的运行库也必须检查"""
        missing = self.check_missing(
            {"_ctypes.pyd": {"ffi-8.dll"}, "ffi-8.dll": {"VCRUNTIME140.dll"}},
            bundled={"_ctypes.pyd", "ffi-8.dll"}, system={"vcruntime140.dll"},
        )
        self.assertEqual(missing, [("ffi-8.dll", "VCRUNTIME140.dll")])

    def test_private_library_on_developer_system_is_not_enough(self):
        """开发机系统目录有私有 DLL 也不能掩盖漏打包"""
        self.assertTrue(self.check_missing(
            {"_ctypes.pyd": {"ffi-8.dll"}}, system={"ffi-8.dll"}, private={"ffi-8.dll"},
        ))

    def test_windows_system_and_api_set_are_allowed(self):
        """正常系统 DLL 和 API Set 不要求复制进包"""
        self.assertEqual(self.check_missing(
            {"_ctypes.pyd": {"KERNEL32.dll", "api-ms-win-crt-runtime-l1-1-0.dll"}},
            system={"kernel32.dll"},
        ), [])

    def test_case_insensitive_root_and_qt_search(self):
        """兼容归档分隔符和 Qt 平台插件的依赖位置"""
        self.assertEqual(self.check_missing(
            {"_ctypes.pyd": {"FFI-8.DLL"}, r"PyQt6\Qt6\plugins\platforms\qwindows.dll": {"Qt6Core.dll"}},
            bundled={"ffi-8.dll", r"PyQt6\Qt6\bin\Qt6Core.dll"},
        ), [])

    def test_unrelated_directory_is_not_a_valid_dependency(self):
        """不能因同名文件放在不参与搜索的目录而误判完整"""
        self.assertTrue(self.check_missing({"_ctypes.pyd": {"ffi-8.dll"}}, bundled={"unrelated/ffi-8.dll"}))

    def test_numpy_private_directory_is_only_allowed_for_numpy(self):
        """承认 NumPy 初始化注册的目录，但不放宽其他模块的检查"""
        bundled = {"numpy.libs/blas.dll"}
        self.assertEqual(self.check_missing({"numpy/_core/core.pyd": {"blas.dll"}}, bundled), [])
        self.assertTrue(self.check_missing({"_ctypes.pyd": {"blas.dll"}}, bundled))

    def test_normalize_path(self):
        """统一 Windows 归档文件名"""
        self.assertEqual(normalize_name(r"PyQt6\Qt6\bin\Qt6Core.DLL"), "pyqt6/qt6/bin/qt6core.dll")


if __name__ == "__main__":
    unittest.main()
