# -*- coding: utf-8 -*-
"""OCRA 运行环境与相机环境自检。

该模块只在函数内部导入第三方包，因此 main.py 可以在加载 PyQt6/OpenCV 前先检查
缺失依赖，并在 GUI 无法启动时给出明确提示。
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import struct
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from importlib import metadata
from pathlib import Path
from typing import Any, Iterable


_DEPENDENCY_PACKAGES = (
    # module, distribution, minimum version, blocks startup
    ("PyQt6", "PyQt6", "6.6", True),
    ("cv2", "opencv-python", "4.8", True),
    ("numpy", "numpy", "1.24", True),
    # Pillow is preferred for Chinese HUD text, but vision_engine.py has an OpenCV fallback.
    ("PIL", "Pillow", "10.0", False),
)

_STATUS_RANK = {"pass": 0, "info": 1, "warning": 2, "error": 3}
_STATUS_LABELS = {
    "zh": {"pass": "通过", "info": "信息", "warning": "警告", "error": "失败"},
    "en": {"pass": "PASS", "info": "INFO", "warning": "WARN", "error": "FAIL"},
}
_STATUS_ICONS = {"pass": "[PASS]", "info": "[INFO]", "warning": "[WARN]", "error": "[FAIL]"}


@dataclass(frozen=True)
class EnvironmentCheckItem:
    """单项检测结果。"""

    key: str
    title: str
    status: str
    summary: str
    detail: str = ""
    action: str = ""


@dataclass
class EnvironmentReport:
    """一次完整环境检测报告。"""

    language: str = "zh"
    generated_at: datetime = field(default_factory=datetime.now)
    items: list[EnvironmentCheckItem] = field(default_factory=list)

    def add(
        self,
        key: str,
        title: str,
        status: str,
        summary: str,
        detail: str = "",
        action: str = "",
    ) -> None:
        status = status if status in _STATUS_RANK else "info"
        self.items.append(EnvironmentCheckItem(key, title, status, summary, detail, action))

    @property
    def error_count(self) -> int:
        return sum(item.status == "error" for item in self.items)

    @property
    def warning_count(self) -> int:
        return sum(item.status == "warning" for item in self.items)

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def worst_status(self) -> str:
        if not self.items:
            return "info"
        return max(self.items, key=lambda item: _STATUS_RANK[item.status]).status

    def summary_text(self) -> str:
        passed = sum(item.status == "pass" for item in self.items)
        info = sum(item.status == "info" for item in self.items)
        if self.language == "en":
            return f"{passed} passed, {self.warning_count} warnings, {self.error_count} failures, {info} informational"
        return f"通过 {passed} 项，警告 {self.warning_count} 项，失败 {self.error_count} 项，信息 {info} 项"

    def to_text(self) -> str:
        is_en = self.language == "en"
        lines = [
            "OCRA Environment Check Report" if is_en else "OCRA 环境检测报告",
            ("Generated: " if is_en else "生成时间：") + self.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
            ("Summary: " if is_en else "汇总：") + self.summary_text(),
            "=" * 72,
        ]
        labels = _STATUS_LABELS["en" if is_en else "zh"]
        for index, item in enumerate(self.items, 1):
            lines.append(f"{index:02d}. {_STATUS_ICONS[item.status]} {item.title}")
            lines.append(f"    {labels[item.status]}: {item.summary}")
            if item.detail:
                lines.append(("    Detail: " if is_en else "    详情：") + item.detail)
            if item.action:
                lines.append(("    Action: " if is_en else "    建议：") + item.action)
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


def _version_tuple(value: str) -> tuple[int, ...]:
    """把版本号转换成可比较的数字元组，忽略 rc/post 等非数字后缀。"""
    parts: list[int] = []
    for raw in str(value).replace("-", ".").split("."):
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _version_at_least(actual: str, required: str) -> bool:
    actual_tuple = _version_tuple(actual)
    required_tuple = _version_tuple(required)
    width = max(len(actual_tuple), len(required_tuple))
    return actual_tuple + (0,) * (width - len(actual_tuple)) >= required_tuple + (0,) * (width - len(required_tuple))


def bootstrap_dependency_errors() -> list[str]:
    """在导入 GUI 前检测启动所需的第三方依赖。"""
    errors: list[str] = []
    if sys.version_info < (3, 10):
        errors.append(f"Python {platform.python_version()} is too old; OCRA requires Python 3.10 or newer.")

    for module_name, distribution_name, minimum, blocks_startup in _DEPENDENCY_PACKAGES:
        if not blocks_startup:
            continue
        if importlib.util.find_spec(module_name) is None:
            errors.append(f"Missing dependency: {distribution_name}>={minimum}")
            continue
        try:
            actual = metadata.version(distribution_name)
        except metadata.PackageNotFoundError:
            # 某些打包环境保留模块但移除了 dist-info；模块能导入时不作为阻断错误。
            continue
        if not _version_at_least(actual, minimum):
            errors.append(f"Dependency too old: {distribution_name} {actual}; requires >= {minimum}")
    return errors


def format_bootstrap_error(errors: Iterable[str]) -> str:
    body = "\n".join(f"• {item}" for item in errors)
    return (
        "OCRA cannot start because the Python environment is incomplete.\n\n"
        f"{body}\n\n"
        "Run: pip install -r requirements.txt\n\n"
        "OCRA 无法启动，因为 Python 运行环境不完整。\n"
        "请执行：pip install -r requirements.txt"
    )


def show_bootstrap_error(message: str) -> None:
    """PyQt6 不可用时，优先使用 Windows 原生消息框，否则写入 stderr。"""
    if platform.system().lower() == "windows":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "OCRA - Environment Error", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr)


def application_resource_root() -> Path:
    """返回程序资源目录；兼容源码运行与 PyInstaller。"""
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root).resolve()
    return Path(__file__).resolve().parents[1]


def application_executable_root() -> Path:
    """返回用户可见程序目录；打包后为 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return application_resource_root()


def _check_write_access(directory: Path) -> tuple[bool, str]:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(prefix="ocra_env_", suffix=".tmp", dir=directory, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(b"OCRA")
        temp_path.unlink(missing_ok=True)
        return True, str(directory)
    except Exception as exc:
        return False, f"{directory}: {exc}"


def _read_pe_architecture(path: Path) -> str:
    """读取 Windows PE 文件机器类型，不加载 DLL。"""
    try:
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                return "not-pe"
            handle.seek(0x3C)
            pe_offset_raw = handle.read(4)
            if len(pe_offset_raw) != 4:
                return "unknown"
            pe_offset = struct.unpack("<I", pe_offset_raw)[0]
            handle.seek(pe_offset)
            if handle.read(4) != b"PE\x00\x00":
                return "unknown"
            machine_raw = handle.read(2)
            if len(machine_raw) != 2:
                return "unknown"
            machine = struct.unpack("<H", machine_raw)[0]
    except Exception:
        return "unknown"
    return {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64"}.get(machine, f"machine-0x{machine:04X}")


def _dependency_version(distribution_name: str) -> str:
    try:
        return metadata.version(distribution_name)
    except metadata.PackageNotFoundError:
        return "unknown"


def _add_system_checks(report: EnvironmentReport) -> None:
    is_en = report.language == "en"
    bits = struct.calcsize("P") * 8
    system_summary = f"{platform.system()} {platform.release()} / {platform.machine()} / {bits}-bit"
    report.add(
        "system",
        "Operating system and process" if is_en else "操作系统与进程位数",
        "pass",
        system_summary,
        f"platform={platform.platform()} | executable={sys.executable}",
    )

    py_ok = sys.version_info >= (3, 10)
    report.add(
        "python",
        "Python runtime" if is_en else "Python 运行时",
        "pass" if py_ok else "error",
        f"Python {platform.python_version()}",
        "OCRA source uses Python 3.10+ syntax." if is_en else "OCRA 源代码使用 Python 3.10 及以上版本语法",
        "Install 64-bit Python 3.10 or newer." if (is_en and not py_ok) else ("安装 64 位 Python 3.10 或更高版本" if not py_ok else ""),
    )

    frozen = bool(getattr(sys, "frozen", False))
    report.add(
        "runtime_mode",
        "Runtime mode" if is_en else "运行模式",
        "info",
        "Packaged executable" if (is_en and frozen) else ("打包版 EXE" if frozen else ("Source / Python" if is_en else "Python 源码模式")),
        f"resource_root={application_resource_root()} | executable_root={application_executable_root()} | cwd={Path.cwd()}",
    )


def _add_dependency_checks(report: EnvironmentReport) -> None:
    is_en = report.language == "en"
    for module_name, distribution_name, minimum, blocks_startup in _DEPENDENCY_PACKAGES:
        present = importlib.util.find_spec(module_name) is not None
        actual = _dependency_version(distribution_name) if present else "not installed"
        valid = present and (actual == "unknown" or _version_at_least(actual, minimum))
        if not present:
            status = "error" if blocks_startup else "warning"
            summary = f"{distribution_name} is missing" if is_en else f"缺少 {distribution_name}"
        elif not valid:
            status = "error" if blocks_startup else "warning"
            summary = f"{distribution_name} {actual} < {minimum}" if is_en else f"{distribution_name} {actual} 低于要求 {minimum}"
        else:
            status = "pass"
            summary = f"{distribution_name} {actual} (required >= {minimum})" if is_en else f"{distribution_name} {actual}（要求 >= {minimum}）"
        report.add(
            f"dependency_{distribution_name.lower()}",
            f"Dependency: {distribution_name}" if is_en else f"依赖：{distribution_name}",
            status,
            summary,
            f"module={module_name}",
            (f"Run: pip install -U {distribution_name}>={minimum}" if is_en else f"执行：pip install -U {distribution_name}>={minimum}") if status in {"error", "warning"} else "",
        )


def _add_storage_checks(report: EnvironmentReport, config_path: str) -> None:
    is_en = report.language == "en"
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = (Path.cwd() / config_file).resolve()
    ok, detail = _check_write_access(config_file.parent)
    report.add(
        "config_write",
        "Configuration write access" if is_en else "配置目录写入权限",
        "pass" if ok else "error",
        str(config_file) if ok else ("Configuration directory is not writable" if is_en else "配置目录不可写"),
        detail,
        ("Move OCRA to a user-writable folder or run it with appropriate permissions." if is_en else "请将 OCRA 放到用户可写目录，或为当前目录授予写入权限") if not ok else "",
    )

    root = application_executable_root()
    try:
        free = shutil.disk_usage(root).free
        free_mb = free / (1024 * 1024)
        status = "pass" if free_mb >= 100 else "warning"
        report.add(
            "disk_space",
            "Free disk space" if is_en else "可用磁盘空间",
            status,
            f"{free_mb:.0f} MB free on {root}",
            "OCRA itself needs little space, but captures/logs may need more." if is_en else "OCRA 本体占用很小，但截图或后续日志可能需要更多空间",
            ("Keep at least 100 MB free." if is_en else "建议至少保留 100 MB 可用空间") if status == "warning" else "",
        )
    except Exception as exc:
        report.add("disk_space", "Free disk space" if is_en else "可用磁盘空间", "warning", "Unable to read disk usage" if is_en else "无法读取磁盘空间", str(exc))


def _add_camera_check(report: EnvironmentReport, config: Any, probe_hardware: bool, camera_is_running: bool) -> None:
    is_en = report.language == "en"
    camera_type = str(getattr(config, "camera_type", "synthetic") or "synthetic").lower()
    camera_id = int(getattr(config, "camera_id", 0) or 0)

    if camera_type == "synthetic":
        report.add(
            "camera",
            "Selected camera backend" if is_en else "当前相机后端",
            "pass",
            "Synthetic test camera requires no driver" if is_en else "模拟测试相机无需驱动或硬件",
        )
        return

    if camera_type == "qhy":
        report.add(
            "camera",
            "Selected camera backend" if is_en else "当前相机后端",
            "warning",
            "QHY backend is currently a placeholder" if is_en else "QHY 后端目前仍为占位接口",
            "The current qhy_camera.py does not implement real SDK capture." if is_en else "当前 qhy_camera.py 尚未实现真实 SDK 采集",
            "Use USB/DirectShow when the camera exposes a UVC device, or implement the QHY SDK backend." if is_en else "若相机提供 UVC/DirectShow 接口可先选择 USB，否则需要接入 QHY SDK 后端",
        )
        return

    if camera_type == "usb":
        if camera_is_running:
            report.add(
                "camera_usb",
                "USB camera" if is_en else "USB 相机",
                "pass",
                f"Camera index {camera_id} is currently running" if is_en else f"相机编号 {camera_id} 当前正在采集",
                "The checker does not reopen a device already used by OCRA." if is_en else "环境检测不会重复打开已被 OCRA 占用的设备",
            )
            return
        if not probe_hardware:
            report.add("camera_usb", "USB camera" if is_en else "USB 相机", "info", "Hardware probe skipped" if is_en else "已跳过硬件探测")
            return
        try:
            import cv2

            backend = cv2.CAP_DSHOW if platform.system().lower() == "windows" else cv2.CAP_ANY
            cap = cv2.VideoCapture(camera_id, backend)
            opened = bool(cap.isOpened())
            backend_name = ""
            if opened and hasattr(cap, "getBackendName"):
                try:
                    backend_name = cap.getBackendName()
                except Exception:
                    backend_name = ""
            cap.release()
            report.add(
                "camera_usb",
                "USB camera" if is_en else "USB 相机",
                "pass" if opened else "error",
                (f"Camera index {camera_id} opened successfully" if is_en else f"相机编号 {camera_id} 可正常打开") if opened else (f"Camera index {camera_id} cannot be opened" if is_en else f"无法打开相机编号 {camera_id}"),
                f"OpenCV backend={backend_name or 'unknown'}",
                ("Check the USB cable, Windows privacy permission, camera driver, and whether another application is using it." if is_en else "请检查 USB 连接、Windows 相机隐私权限、设备驱动，以及相机是否被其他软件占用") if not opened else "",
            )
        except Exception as exc:
            report.add("camera_usb", "USB camera" if is_en else "USB 相机", "error", "USB camera probe failed" if is_en else "USB 相机探测异常", str(exc))
        return

    if camera_type != "zwo":
        report.add("camera", "Selected camera backend" if is_en else "当前相机后端", "error", f"Unknown camera type: {camera_type}" if is_en else f"未知相机类型：{camera_type}")
        return

    bits = struct.calcsize("P") * 8
    if platform.system().lower() != "windows":
        report.add(
            "zwo_os",
            "ZWO SDK platform" if is_en else "ZWO SDK 平台",
            "error",
            "The current ctypes backend requires Windows" if is_en else "当前 ctypes ZWO 后端需要 Windows",
            platform.platform(),
        )
        return

    report.add(
        "zwo_process_bits",
        "ZWO process architecture" if is_en else "ZWO 进程位数",
        "pass" if bits == 64 else "warning",
        f"Python process: {bits}-bit",
        "64-bit Python is recommended for current ASIStudio/ZWO SDK installations." if is_en else "当前 ASIStudio/ZWO SDK 通常建议配合 64 位 Python 使用",
        ("Use 64-bit Python and x64 ASICamera2.dll." if is_en else "建议使用 64 位 Python 与 x64 ASICamera2.dll") if bits != 64 else "",
    )

    explicit = str(getattr(config, "zwo_dll_path", "") or "").strip().strip('"')
    if explicit and Path(explicit).name.lower() != "asicamera2.dll":
        report.add(
            "zwo_explicit_path",
            "Configured ZWO DLL" if is_en else "已配置的 ZWO DLL",
            "warning",
            f"{Path(explicit).name} is not the SDK entry DLL" if is_en else f"{Path(explicit).name} 不是 SDK 入口 DLL",
            explicit,
            "Select ASICamera2.dll, not ASIxxx.dll or a DirectShow model DLL." if is_en else "请选择 ASICamera2.dll，不要选择 ASIxxx.dll 或型号专用 DirectShow DLL",
        )

    if not probe_hardware:
        report.add("zwo_probe", "ZWO SDK and camera" if is_en else "ZWO SDK 与相机", "info", "Hardware probe skipped" if is_en else "已跳过硬件探测")
        return

    try:
        from cameras.zwo_camera import ZWOCamera

        devices = ZWOCamera.discover(explicit)
        sdk_path = str(getattr(ZWOCamera, "_sdk_path", "") or "")
        sdk_error = str(getattr(ZWOCamera, "_sdk_error", "") or "")

        if sdk_path:
            dll_file = Path(sdk_path)
            arch = _read_pe_architecture(dll_file) if dll_file.exists() else "unknown"
            expected = "x64" if bits == 64 else "x86"
            arch_ok = arch in {"unknown", expected}
            report.add(
                "zwo_dll",
                "ASICamera2.dll" if is_en else "ASICamera2.dll",
                "pass" if arch_ok else "error",
                f"Loaded: {sdk_path}",
                f"DLL architecture={arch}; Python process={bits}-bit",
                (f"Use the {expected} build of ASICamera2.dll." if is_en else f"请改用 {expected} 版本的 ASICamera2.dll") if not arch_ok else "",
            )
        else:
            report.add(
                "zwo_dll",
                "ASICamera2.dll",
                "error",
                "ZWO SDK DLL could not be loaded" if is_en else "无法加载 ZWO SDK DLL",
                sdk_error,
                "Install ASIStudio/ZWO SDK or place the matching 64-bit ASICamera2.dll next to OCRA." if is_en else "请安装 ASIStudio/ZWO SDK，或将位数匹配的 64 位 ASICamera2.dll 放到 OCRA 程序目录",
            )

        if devices:
            names = "; ".join(name for _device_id, name in devices)
            selected_found = any(int(device_id) == camera_id for device_id, _name in devices)
            report.add(
                "zwo_camera",
                "Connected ZWO cameras" if is_en else "已连接的 ZWO 相机",
                "pass" if selected_found else "warning",
                f"Detected {len(devices)} camera(s): {names}" if is_en else f"识别到 {len(devices)} 台相机：{names}",
                f"configured_camera_id={camera_id}",
                ("Select a detected camera ID and apply the camera settings." if is_en else "请在设备下拉框选择已识别的相机并应用相机设置") if not selected_found else "",
            )
        elif sdk_path:
            report.add(
                "zwo_camera",
                "Connected ZWO cameras" if is_en else "已连接的 ZWO 相机",
                "error",
                "SDK loaded, but no ASI camera was detected" if is_en else "SDK 已加载，但未识别到 ASI 相机",
                sdk_error,
                "Reconnect the USB cable, check Device Manager/ASIStudio, and close software that may occupy the camera." if is_en else "请重新连接 USB，在设备管理器或 ASIStudio 中确认设备，并关闭可能占用相机的软件",
            )
    except Exception as exc:
        report.add(
            "zwo_probe",
            "ZWO SDK and camera" if is_en else "ZWO SDK 与相机",
            "error",
            "ZWO environment probe failed" if is_en else "ZWO 环境探测异常",
            str(exc),
        )


def run_environment_check(
    config: Any,
    config_path: str = "config/config.txt",
    *,
    language: str = "zh",
    probe_hardware: bool = True,
    camera_is_running: bool = False,
) -> EnvironmentReport:
    """执行一次 OCRA 环境检测。

    probe_hardware=False 适合只做软件环境巡检；启动时或用户点击检测按钮时可设为 True。
    """
    language = "en" if language == "en" else "zh"
    report = EnvironmentReport(language=language)
    _add_system_checks(report)
    _add_dependency_checks(report)
    _add_storage_checks(report, config_path)
    _add_camera_check(report, config, probe_hardware, camera_is_running)
    return report
