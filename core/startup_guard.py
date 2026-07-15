# -*- coding: utf-8 -*-
"""OCRA 启动前原生环境检测。

本模块只能依赖 Python 标准库。它会在导入 PyQt6、OpenCV、NumPy 和业务模块之前运行，
因此即使 Qt 的底层 DLL 无法加载，也能使用 Windows 原生 MessageBox 给出明确提示，
并把完整诊断报告写入磁盘。
"""
from __future__ import annotations

import ctypes
import importlib
import importlib.metadata
import os
import platform
import struct
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


_STATUS_RANK = {"pass": 0, "info": 1, "warning": 2, "error": 3}
_DLL_DIRECTORY_HANDLES: list[object] = []


@dataclass(frozen=True)
class StartupCheck:
    key: str
    status: str
    summary: str
    detail: str = ""
    action: str = ""


@dataclass
class StartupReport:
    generated_at: datetime = field(default_factory=datetime.now)
    checks: list[StartupCheck] = field(default_factory=list)
    report_path: str = ""

    def add(
        self,
        key: str,
        status: str,
        summary: str,
        detail: str = "",
        action: str = "",
    ) -> None:
        if status not in _STATUS_RANK:
            status = "info"
        self.checks.append(StartupCheck(key, status, summary, detail, action))

    @property
    def has_errors(self) -> bool:
        return any(item.status == "error" for item in self.checks)

    @property
    def errors(self) -> list[StartupCheck]:
        return [item for item in self.checks if item.status == "error"]

    def to_text(self) -> str:
        labels = {"pass": "PASS", "info": "INFO", "warning": "WARN", "error": "FAIL"}
        lines = [
            "OCRA Startup Diagnostics / OCRA 启动诊断",
            f"Generated / 生成时间: {self.generated_at:%Y-%m-%d %H:%M:%S}",
            f"Executable / 程序: {sys.executable}",
            f"Working directory / 工作目录: {Path.cwd()}",
            f"Frozen / 打包模式: {bool(getattr(sys, 'frozen', False))}",
            "=" * 80,
        ]
        for index, item in enumerate(self.checks, 1):
            lines.append(f"{index:02d}. [{labels[item.status]}] {item.summary}")
            if item.detail:
                lines.append(f"    Detail / 详情: {item.detail}")
            if item.action:
                lines.append(f"    Action / 建议: {item.action}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable_root() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).resolve()
    return Path(__file__).resolve().parents[1]


def normalize_working_directory() -> None:
    """打包版始终以 EXE 所在目录为工作目录。

    这可保证 config/config.txt、ASICamera2.dll 等外部文件不会因为快捷方式的
    “起始位置”不同而失效。
    """
    if not is_frozen():
        return
    try:
        os.chdir(executable_root())
    except OSError:
        pass


def _unique_existing_directories(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.is_dir():
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _candidate_runtime_roots() -> list[Path]:
    exe = executable_root()
    bundle = resource_root()
    return _unique_existing_directories(
        [
            exe,
            exe / "_internal",
            bundle,
            bundle / "_internal",
        ]
    )


def _discover_qt_directories() -> tuple[list[Path], list[Path]]:
    """返回 Qt DLL 目录与 Qt plugin 目录。"""
    dll_dirs: list[Path] = []
    plugin_dirs: list[Path] = []

    for root in _candidate_runtime_roots():
        dll_dirs.extend(
            [
                root,
                root / "PyQt6",
                root / "PyQt6" / "Qt6" / "bin",
                root / "PyQt6" / "Qt6",
            ]
        )
        plugin_dirs.extend(
            [
                root / "PyQt6" / "Qt6" / "plugins",
                root / "PyQt6" / "Qt6" / "plugins" / "platforms",
            ]
        )

    # 兼容不同 PyInstaller 版本或自定义 contents_directory。
    for root in _candidate_runtime_roots():
        try:
            for core_dll in root.rglob("Qt6Core.dll"):
                dll_dirs.append(core_dll.parent)
                qt6_root = core_dll.parent.parent
                plugin_dirs.extend([qt6_root / "plugins", qt6_root / "plugins" / "platforms"])
        except (OSError, PermissionError):
            continue

    return _unique_existing_directories(dll_dirs), _unique_existing_directories(plugin_dirs)


def configure_windows_dll_search() -> tuple[list[Path], list[Path]]:
    """显式注册打包目录中的 Qt DLL 和插件目录。

    Windows 10 的 DLL 搜索规则、快捷方式工作目录以及部分安全软件处理方式不同，
    显式注册目录可避免 QtWidgets.pyd 已存在但其依赖 DLL 无法定位的问题。
    """
    if platform.system().lower() != "windows":
        return [], []

    dll_dirs, plugin_dirs = _discover_qt_directories()

    current_path = os.environ.get("PATH", "")
    path_parts = [str(path) for path in dll_dirs]
    if current_path:
        path_parts.append(current_path)
    os.environ["PATH"] = os.pathsep.join(path_parts)

    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory is not None:
        for directory in dll_dirs:
            try:
                handle = add_dll_directory(str(directory))
                _DLL_DIRECTORY_HANDLES.append(handle)
            except OSError:
                continue

    plugin_root = next((path for path in plugin_dirs if path.name.lower() == "plugins"), None)
    platform_root = next((path for path in plugin_dirs if path.name.lower() == "platforms"), None)
    if plugin_root is not None:
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_root))
    if platform_root is not None:
        os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", str(platform_root))

    return dll_dirs, plugin_dirs


def _find_runtime_file(filename: str) -> Optional[Path]:
    wanted = filename.lower()
    for root in _candidate_runtime_roots():
        direct_candidates = [
            root / filename,
            root / "PyQt6" / "Qt6" / "bin" / filename,
            root / "PyQt6" / "Qt6" / "plugins" / "platforms" / filename,
        ]
        for candidate in direct_candidates:
            if candidate.is_file():
                return candidate.resolve()
        try:
            for candidate in root.rglob(filename):
                if candidate.is_file() and candidate.name.lower() == wanted:
                    return candidate.resolve()
        except (OSError, PermissionError):
            continue
    return None


def _windows_version_detail() -> tuple[str, Optional[int]]:
    if platform.system().lower() != "windows":
        return platform.platform(), None
    try:
        version = sys.getwindowsversion()  # type: ignore[attr-defined]
        build = int(version.build)
        return f"Windows {version.major}.{version.minor}, build {build}", build
    except Exception:
        return platform.platform(), None


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "bundled/unknown" if is_frozen() else "not installed"


def _format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()


def _check_windows_runtime(report: StartupReport) -> None:
    if platform.system().lower() != "windows":
        report.add(
            "os",
            "warning",
            f"当前系统为 {platform.system()}，此发布包主要面向 Windows 10/11 x64",
            platform.platform(),
        )
        return

    bits = struct.calcsize("P") * 8
    version_text, build = _windows_version_detail()
    if bits != 64:
        report.add(
            "architecture",
            "error",
            f"当前进程为 {bits} 位，OCRA 发布版要求 64 位环境",
            f"machine={platform.machine()} | executable={sys.executable}",
            "请使用 64 位 Python 3.12 和 x64 版本的 OCRA、Qt 与 ASICamera2.dll",
        )
    else:
        report.add("architecture", "pass", f"64 位进程：{platform.machine()}")

    if build is not None and build < 17763:
        report.add(
            "windows_build",
            "error",
            f"Windows 10 版本过旧：{version_text}",
            "Qt 6 发布包至少按 Windows 10 1809（build 17763）进行兼容处理",
            "请通过 Windows Update 更新到 Windows 10 22H2 或 Windows 11",
        )
    else:
        report.add("windows_build", "pass", version_text)

    runtime_names = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    missing: list[str] = []
    load_errors: list[str] = []
    for runtime_name in runtime_names:
        try:
            ctypes.WinDLL(runtime_name)
        except OSError as exc:
            missing.append(runtime_name)
            load_errors.append(f"{runtime_name}: {exc}")

    if missing:
        report.add(
            "vc_runtime",
            "warning",
            "Microsoft Visual C++ x64 运行库可能不完整",
            "; ".join(load_errors),
            "安装或修复 Microsoft Visual C++ 2015–2022 Redistributable x64，然后重启 OCRA",
        )
    else:
        report.add("vc_runtime", "pass", "Microsoft Visual C++ x64 运行库可加载")


def _check_packaged_qt_files(report: StartupReport) -> None:
    if not is_frozen():
        report.add("package_layout", "info", "当前为 Python 源码运行模式")
        return

    required_files = ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "qwindows.dll")
    found: dict[str, Path] = {}
    missing: list[str] = []
    for filename in required_files:
        path = _find_runtime_file(filename)
        if path is None:
            missing.append(filename)
        else:
            found[filename] = path

    if missing:
        report.add(
            "qt_files",
            "error",
            "打包目录缺少 Qt 运行文件",
            "missing=" + ", ".join(missing),
            "不要只发送 OCRA.exe；请完整发送 OCRA 文件夹，并使用项目中的 OCRA.spec 重新打包",
        )
        return

    report.add(
        "qt_files",
        "pass",
        "Qt6Core、Qt6Gui、Qt6Widgets 和 qwindows 平台插件均已找到",
        " | ".join(f"{name}={path}" for name, path in found.items()),
    )

    # 先通过 Windows Loader 检查 qwindows.dll 的依赖链，避免 QApplication 创建时直接中止。
    if platform.system().lower() == "windows":
        plugin = found.get("qwindows.dll")
        if plugin is not None:
            try:
                ctypes.WinDLL(str(plugin))
                report.add("qwindows_load", "pass", "qwindows.dll 及其依赖可由 Windows Loader 加载")
            except OSError as exc:
                report.add(
                    "qwindows_load",
                    "error",
                    "qwindows.dll 存在，但其底层依赖无法加载",
                    f"{plugin}: {exc}",
                    "请修复 VC++ x64 运行库，并确认 _internal 文件夹完整且 DLL 未被杀毒软件隔离",
                )


def _check_required_imports(report: StartupReport) -> None:
    # Qt 必须做真实导入，find_spec 无法发现 QtWidgets.pyd 的二级 DLL 缺失。
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets  # noqa: F401

        pyqt_version = getattr(QtCore, "PYQT_VERSION_STR", _package_version("PyQt6"))
        qt_version = getattr(QtCore, "QT_VERSION_STR", "unknown")
        report.add(
            "pyqt_import",
            "pass",
            f"PyQt6.QtWidgets 可正常导入：PyQt {pyqt_version} / Qt {qt_version}",
            f"QtCore={getattr(QtCore, '__file__', '')} | QtWidgets={getattr(QtWidgets, '__file__', '')}",
        )
    except BaseException as exc:
        report.add(
            "pyqt_import",
            "error",
            "PyQt6.QtWidgets 无法导入，图形界面无法启动",
            _format_exception(exc),
            "优先修复 VC++ x64 运行库；若仍失败，请用 OCRA.spec 重新打包并完整发送整个 OCRA 文件夹",
        )
        # Qt 已失败时仍继续检查其他模块，报告可一次性给出更多信息。

    required_modules = (
        ("numpy", "NumPy", True),
        ("cv2", "OpenCV", True),
        ("PIL", "Pillow", False),
    )
    for module_name, display_name, blocking in required_modules:
        try:
            module = importlib.import_module(module_name)
            version = getattr(module, "__version__", _package_version(display_name))
            report.add(
                f"import_{module_name}",
                "pass",
                f"{display_name} 可正常导入：{version}",
                str(getattr(module, "__file__", "")),
            )
        except BaseException as exc:
            report.add(
                f"import_{module_name}",
                "error" if blocking else "warning",
                f"{display_name} 无法导入",
                _format_exception(exc),
                f"源码环境执行：python -m pip install -U {display_name}",
            )


def run_startup_preflight() -> StartupReport:
    """执行不会依赖 Qt 界面的启动前检查。"""
    normalize_working_directory()
    report = StartupReport()

    report.add(
        "python",
        "pass" if sys.version_info >= (3, 10) else "error",
        f"Python {platform.python_version()} ({struct.calcsize('P') * 8}-bit)",
        f"executable={sys.executable}",
        "请使用 64 位 Python 3.12 重新构建" if sys.version_info < (3, 10) else "",
    )

    _check_windows_runtime(report)
    dll_dirs, plugin_dirs = configure_windows_dll_search()
    report.add(
        "dll_search",
        "info",
        "已配置 Windows DLL 与 Qt 插件搜索路径" if platform.system().lower() == "windows" else "非 Windows 系统，未配置 DLL 搜索路径",
        f"dll_dirs={[str(path) for path in dll_dirs]} | plugin_dirs={[str(path) for path in plugin_dirs]}",
    )
    _check_packaged_qt_files(report)
    _check_required_imports(report)
    return report


def _write_text_safely(filename: str, content: str) -> str:
    candidates = [executable_root() / filename, Path(tempfile.gettempdir()) / filename]
    for path in candidates:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return str(path)
        except OSError:
            continue
    return ""


def save_startup_report(report: StartupReport) -> str:
    report.report_path = _write_text_safely("OCRA_startup_diagnostics.txt", report.to_text())
    return report.report_path


def _native_message_box(title: str, message: str, error: bool = True) -> None:
    if platform.system().lower() == "windows":
        try:
            flags = 0x00000010 if error else 0x00000040  # MB_ICONERROR / MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(None, message, title, flags)
            return
        except Exception:
            pass
    print(f"{title}\n{message}", file=sys.stderr)


def show_startup_failure(report: StartupReport) -> None:
    report_path = save_startup_report(report)
    reasons = [item.summary for item in report.errors[:4]]
    reason_text = "\n".join(f"• {reason}" for reason in reasons) or "• 未知启动错误"
    message = (
        "OCRA 无法启动。\n\n"
        f"{reason_text}\n\n"
        "请依次检查：\n"
        "1. 安装或修复 Microsoft Visual C++ 2015–2022 Redistributable x64\n"
        "2. 使用 Windows 10 1809 以上版本，建议 Windows 10 22H2\n"
        "3. 不要单独复制 OCRA.exe，必须保留完整的 _internal 文件夹\n"
        "4. 检查 Windows 安全中心是否隔离了 Qt6*.dll 或 qwindows.dll\n"
    )
    if report_path:
        message += f"\n完整诊断报告：\n{report_path}\n"
    message += "\nOCRA could not start. The detailed diagnostics file can be sent to the developer."
    _native_message_box("OCRA - 启动环境错误", message, error=True)


def build_exception_report(stage: str, exc: BaseException) -> StartupReport:
    report = StartupReport()
    report.add(
        "unhandled_exception",
        "error",
        f"程序在“{stage}”阶段发生未处理异常",
        _format_exception(exc),
        "请将 OCRA_startup_diagnostics.txt 发给开发者",
    )
    return report


def handle_unhandled_exception(stage: str, exc: BaseException) -> None:
    show_startup_failure(build_exception_report(stage, exc))


def install_exception_hook() -> None:
    """避免窗口版 PyInstaller 仅显示英文 Unhandled exception 弹窗。"""

    def _hook(exc_type, exc_value, exc_traceback):  # noqa: ANN001
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        report = StartupReport()
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)).strip()
        report.add(
            "unhandled_exception",
            "error",
            "OCRA 发生未处理异常",
            detail,
            "请将 OCRA_startup_diagnostics.txt 发给开发者",
        )
        show_startup_failure(report)

    sys.excepthook = _hook
