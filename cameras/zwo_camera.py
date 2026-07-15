# -*- coding: utf-8 -*-
# 文件说明：ZWO ASI 相机后端直接通过 ctypes 调用 ZWO 官方 SDK 的 ASICamera2.dll
# 设计逻辑：
# 1. 不依赖第三方 Python wrapper（例如 zwoasi）只要系统里能找到正确位数的 ASICamera2.dll 即可
# 2. 枚举真实插入的 ASI 相机，UI 显示“相机设备”下拉框，避免让用户手填编号
# 3. 支持曝光、增益和自动曝光参数，并在打开相机时写入 SDK
# 4. 对常见错误给出明确提示：64 位 Python 不能加载 SysWOW64 里的 32 位 DLL
from __future__ import annotations

import ctypes
import glob
import os
import platform
import struct
from pathlib import Path
from typing import ClassVar, Optional, Tuple

import cv2
import numpy as np

from .base_camera import BaseCamera


# ZWO SDK 常用返回值/枚举这里只声明本程序需要用到的最小集合
ASI_SUCCESS = 0
ASI_IMG_RAW8 = 0
ASI_IMG_RGB24 = 1
ASI_IMG_RAW16 = 2
ASI_IMG_Y8 = 3

ASI_GAIN = 0
ASI_EXPOSURE = 1
ASI_OFFSET = 5  # ZWO SDK 里的亮度偏置；ASI 相机没有传统 ISO，本程序把 ISO/亮度映射到这里


class ASICameraInfo(ctypes.Structure):
    """ZWO SDK 的 ASI_CAMERA_INFO 结构体

    字段顺序按照 ASICamera2.h 的公开结构声明保留
    本程序主要使用 Name、CameraID、MaxWidth、MaxHeight、IsColorCam 和 SupportedVideoFormat
    """

    _fields_ = [
        ("Name", ctypes.c_char * 64),
        ("CameraID", ctypes.c_int),
        ("MaxHeight", ctypes.c_long),
        ("MaxWidth", ctypes.c_long),
        ("IsColorCam", ctypes.c_int),
        ("BayerPattern", ctypes.c_int),
        ("SupportedBins", ctypes.c_int * 16),
        ("SupportedVideoFormat", ctypes.c_int * 8),
        ("PixelSize", ctypes.c_double),
        ("MechanicalShutter", ctypes.c_int),
        ("ST4Port", ctypes.c_int),
        ("IsCoolerCam", ctypes.c_int),
        ("IsUSB3Host", ctypes.c_int),
        ("IsUSB3Camera", ctypes.c_int),
        ("ElecPerADU", ctypes.c_float),
        ("BitDepth", ctypes.c_int),
        ("IsTriggerCam", ctypes.c_int),
        ("Unused", ctypes.c_char * 16),
    ]


class ZWOCamera(BaseCamera):
    """ZWO ASI 相机后端"""

    _sdk = None
    _sdk_path: ClassVar[str] = ""
    _sdk_error: ClassVar[str] = ""
    _dll_dirs: ClassVar[list[object]] = []  # 保存 add_dll_directory 句柄，防止被 GC 释放

    def __init__(
        self,
        camera_id: int = 0,
        dll_path: str = "",
        width: int = 1280,
        height: int = 720,
        exposure_ms: float = 50.0,
        iso_value: int = 100,
        gain: int = 400,
        auto_exposure: bool = False,
    ) -> None:
        self.camera_id = int(camera_id)
        self.dll_path = dll_path.strip()
        self.width = int(width)
        self.height = int(height)
        self.exposure_ms = float(exposure_ms)
        self.iso_value = int(iso_value)
        self.gain = int(gain)
        self.auto_exposure = bool(auto_exposure)
        self.opened = False
        self.capture_started = False
        self.last_error = ""
        self._frame_width = self.width
        self._frame_height = self.height
        self._image_type = ASI_IMG_RGB24
        self._channels = 3
        self._buffer: Optional[np.ndarray] = None

    # ------------------------------------------------------------------
    # SDK 加载与设备枚举
    # ------------------------------------------------------------------
    @classmethod
    def _python_bits(cls) -> int:
        return struct.calcsize("P") * 8



    @classmethod
    def _is_asicamera2(cls, path: str) -> bool:
        """判断用户提供的文件是不是 SDK 入口 DLL

        注意：ZWO 安装目录里会出现很多相机型号 DLL，例如 ASI662MM-Pro.dll、ASI120MM.dll
        这些通常是 DirectShow/WDM 驱动模块，不是 SDK 入口，不能用于 ASIGetNumOfConnectedCameras
        Python/ctypes 只能加载 ASICamera2.dll 作为 SDK 入口
        """
        return Path(str(path).strip().strip('"')).name.lower() == "asicamera2.dll"

    @classmethod
    def _search_asicamera2_near(cls, explicit_path: str) -> list[str]:
        """从用户给的路径附近搜索 ASICamera2.dll

        用户经常会误选 ZWO_USB_Cameras_DS/DX_x86/ASI662MM-Pro.dll 这种型号 DLL
        这里不会直接加载这个型号 DLL，而是沿着它的父目录和祖先目录查找真正的 ASICamera2.dll
        """
        raw = str(explicit_path or "").strip().strip('"')
        if not raw:
            return []
        p = Path(raw)
        roots: list[Path] = []
        if p.is_dir():
            roots.append(p)
        else:
            if p.parent:
                roots.append(p.parent)
        try:
            roots.extend(list(p.parents)[:4])
        except Exception:
            pass

        found: list[str] = []
        seen: set[str] = set()
        for root in roots:
            if not root.exists():
                continue
            for item in root.glob("**/ASICamera2.dll"):
                key = str(item).lower()
                if key not in seen:
                    seen.add(key)
                    found.append(str(item))
        return found

    @classmethod
    def _score_dll_candidate(cls, path: str) -> int:
        """给候选 DLL 打分，优先选择和 Python 位数匹配的 SDK DLL"""
        text = str(path).replace("\\", "/").lower()
        score = 0
        if "asicamera2.dll" in text:
            score += 100
        bits = cls._python_bits()
        if bits == 64:
            if any(x in text for x in ["/x64/", "amd64", "win64", "system32", "program files/"]):
                score += 30
            if any(x in text for x in ["/x86/", "win32", "syswow64", "program files (x86)"]):
                score -= 40
        else:
            if any(x in text for x in ["/x86/", "win32", "syswow64", "program files (x86)"]):
                score += 30
            if any(x in text for x in ["/x64/", "amd64", "win64", "system32", "program files/"]):
                score -= 40
        if "sdk" in text:
            score += 10
        if "directshow" in text or "_ds" in text or "/dx_" in text or "/dshow" in text:
            score -= 20
        return score

    @classmethod
    def _candidate_dll_paths(cls, explicit_path: str = "") -> list[str]:
        """生成 ASICamera2.dll 候选路径

        关键逻辑：
        1. 只加载名为 ASICamera2.dll 的 SDK 入口 DLL
        2. 如果用户误选了 ASI662MM-Pro.dll 这类型号/DirectShow DLL，就在附近搜索 ASICamera2.dll，绝不直接加载误选文件
        3. 根据当前 Python 位数排序，64 位 Python 优先 x64/System32，避免误加载 x86/SysWOW64
        """
        candidates: list[str] = []
        explicit = str(explicit_path or "").strip().strip('"')
        if explicit:
            p = Path(explicit)
            if p.is_dir():
                candidates.extend(cls._search_asicamera2_near(explicit))
                candidates.append(str(p / "ASICamera2.dll"))
            elif cls._is_asicamera2(explicit):
                candidates.append(explicit)
            else:
                # 用户选了型号 DLL 或其他 DLL不要直接加载它，只在附近找真正的 SDK DLL
                candidates.extend(cls._search_asicamera2_near(explicit))

        for env_name in ["ZWO_ASI_DLL", "ASICAMERA2_DLL", "ASI_CAMERA_DLL"]:
            value = os.environ.get(env_name)
            if value:
                if cls._is_asicamera2(value):
                    candidates.append(value)
                else:
                    candidates.extend(cls._search_asicamera2_near(value))

        cwd = Path.cwd()
        here = Path(__file__).resolve()
        project_root = here.parents[1]
        for base in [cwd, project_root, project_root / "drivers", project_root / "drivers" / "zwo", project_root / "cameras"]:
            candidates.append(str(base / "ASICamera2.dll"))

        # 在 PATH 中查找 ASICamera2.dll
        for path_env in os.environ.get("PATH", "").split(os.pathsep):
            if path_env:
                candidates.append(str(Path(path_env) / "ASICamera2.dll"))

        # 常见 ZWO/ASI 安装目录不同安装包目录名不同，所以使用 glob
        for env_name in ["ProgramFiles", "ProgramFiles(x86)"]:
            base = os.environ.get(env_name)
            if not base:
                continue
            patterns = [
                str(Path(base) / "ZWO*" / "**" / "ASICamera2.dll"),
                str(Path(base) / "ASI*" / "**" / "ASICamera2.dll"),
                str(Path(base) / "ZWO Design" / "**" / "ASICamera2.dll"),
                str(Path(base) / "ZWO" / "**" / "ASICamera2.dll"),
            ]
            for pattern in patterns:
                candidates.extend(glob.glob(pattern, recursive=True))

        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        if cls._python_bits() == 64:
            candidates.append(str(Path(system_root) / "System32" / "ASICamera2.dll"))
            # SysWOW64 是 32 位 DLL 目录，64 位 Python 默认不加入候选
        else:
            candidates.append(str(Path(system_root) / "SysWOW64" / "ASICamera2.dll"))

        # 最后才尝试裸文件名，只有 DLL 已在系统搜索路径时才可能成功
        candidates.append("ASICamera2.dll")

        # 去重、过滤不存在的绝对路径、确保只保留 ASICamera2.dll
        seen: set[str] = set()
        result: list[str] = []
        for item in candidates:
            item = str(item).strip().strip('"')
            if not item or not cls._is_asicamera2(item):
                continue
            p = Path(item)
            if p.is_absolute() and not p.exists():
                continue
            key = item.lower()
            if key not in seen:
                seen.add(key)
                result.append(item)

        result.sort(key=cls._score_dll_candidate, reverse=True)
        return result

    @classmethod
    def _load_sdk(cls, explicit_path: str = "") -> bool:
        """加载 ASICamera2.dll 并绑定函数原型"""
        if cls._sdk is not None:
            return True

        if platform.system().lower() != "windows":
            cls._sdk_error = "ZWO ASI SDK 当前仅在 Windows 环境下按 DLL 方式加载"
            return False

        explicit = str(explicit_path or "").strip().strip('"')
        wrong_explicit_msg = ""
        if explicit and Path(explicit).suffix.lower() == ".dll" and not cls._is_asicamera2(explicit):
            wrong_explicit_msg = (
                f"你选择的是 {Path(explicit).name}，这不是 ZWO SDK 入口 DLL"
                "请不要选择 ASI662MM-Pro.dll / ASIxxx.dll 这类型号或 DirectShow DLL，"
                "必须选择 ASICamera2.dll"
            )

        last_error = ""
        tried: list[str] = []
        candidates = cls._candidate_dll_paths(explicit_path)
        if wrong_explicit_msg and not candidates:
            cls._sdk_error = wrong_explicit_msg + " 程序已在该路径附近搜索，但没有找到 ASICamera2.dll"
            return False

        for dll in candidates:
            tried.append(dll)
            try:
                p = Path(dll)
                if p.is_absolute() and p.parent.exists() and hasattr(os, "add_dll_directory"):
                    cls._dll_dirs.append(os.add_dll_directory(str(p.parent)))
                lib = ctypes.WinDLL(str(p) if p.is_absolute() else dll)
                cls._bind_sdk_functions(lib)
                cls._sdk = lib
                cls._sdk_path = str(p) if p.is_absolute() else dll
                cls._sdk_error = ""
                print(f"[ZWO] ASICamera2.dll 加载成功: {cls._sdk_path}")
                return True
            except Exception as exc:
                last_error = f"{dll}: {exc}"

        bit_msg = ""
        if cls._python_bits() == 64:
            bit_msg = "当前是 64 位 Python，请不要使用 C:\\Windows\\SysWOW64 里的 32 位 ASICamera2.dll；请使用 ZWO 安装目录或 C:\\Windows\\System32 中的 64 位 DLL"
        prefix = "无法加载 ZWO SDK 的 ASICamera2.dll"
        if wrong_explicit_msg:
            prefix += " " + wrong_explicit_msg
        cls._sdk_error = (
            f"{prefix} {bit_msg} 最后错误: {last_error}已尝试: {', '.join(tried) if tried else '无'}"
        )
        return False

    @staticmethod
    def _bind_sdk_functions(lib) -> None:  # noqa: ANN001
        """为 ctypes 函数设置参数类型，避免调用时栈参数错位"""
        lib.ASIGetNumOfConnectedCameras.restype = ctypes.c_int

        lib.ASIGetCameraProperty.argtypes = [ctypes.POINTER(ASICameraInfo), ctypes.c_int]
        lib.ASIGetCameraProperty.restype = ctypes.c_int

        lib.ASIOpenCamera.argtypes = [ctypes.c_int]
        lib.ASIOpenCamera.restype = ctypes.c_int
        lib.ASIInitCamera.argtypes = [ctypes.c_int]
        lib.ASIInitCamera.restype = ctypes.c_int
        lib.ASICloseCamera.argtypes = [ctypes.c_int]
        lib.ASICloseCamera.restype = ctypes.c_int

        lib.ASISetROIFormat.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        lib.ASISetROIFormat.restype = ctypes.c_int
        lib.ASISetControlValue.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_long, ctypes.c_int]
        lib.ASISetControlValue.restype = ctypes.c_int

        lib.ASIStartVideoCapture.argtypes = [ctypes.c_int]
        lib.ASIStartVideoCapture.restype = ctypes.c_int
        lib.ASIStopVideoCapture.argtypes = [ctypes.c_int]
        lib.ASIStopVideoCapture.restype = ctypes.c_int
        lib.ASIGetVideoData.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_long, ctypes.c_int]
        lib.ASIGetVideoData.restype = ctypes.c_int

    @classmethod
    def _camera_info_by_index(cls, index: int) -> Optional[ASICameraInfo]:
        if cls._sdk is None:
            return None
        info = ASICameraInfo()
        ret = cls._sdk.ASIGetCameraProperty(ctypes.byref(info), int(index))
        if ret != ASI_SUCCESS:
            cls._sdk_error = f"读取 ZWO 相机属性失败，index={index}, ret={ret}"
            return None
        return info

    @classmethod
    def discover(cls, dll_path: str = "") -> list[Tuple[int, str]]:
        """返回已识别到的 ZWO 相机列表，格式为 [(CameraID, 显示名称), ...]"""
        if not cls._load_sdk(dll_path):
            print(f"[ZWO] 设备枚举失败: {cls._sdk_error}")
            return []
        try:
            num = int(cls._sdk.ASIGetNumOfConnectedCameras())
        except Exception as exc:
            cls._sdk_error = f"读取 ZWO 相机数量失败: {exc}"
            print(f"[ZWO] {cls._sdk_error}")
            return []

        devices: list[Tuple[int, str]] = []
        for idx in range(num):
            info = cls._camera_info_by_index(idx)
            if info is None:
                continue
            name = info.Name.split(b"\x00", 1)[0].decode("utf-8", errors="ignore") or f"ASI Camera {idx}"
            devices.append((int(info.CameraID), f"{idx} - {name}  ID:{int(info.CameraID)}"))
        return devices

    # ------------------------------------------------------------------
    # BaseCamera 接口实现
    # ------------------------------------------------------------------
    def open(self) -> bool:
        if not self._load_sdk(self.dll_path):
            self.last_error = self._sdk_error
            print(f"[ZWO] 初始化失败: {self.last_error}")
            return False

        sdk = self._sdk
        try:
            if sdk.ASIGetNumOfConnectedCameras() <= 0:
                self.last_error = "未检测到 ZWO ASI 相机"
                print(f"[ZWO] {self.last_error}")
                return False

            ret = sdk.ASIOpenCamera(self.camera_id)
            if ret != ASI_SUCCESS:
                self.last_error = f"打开 ZWO 相机失败，CameraID={self.camera_id}, ret={ret}请确认没有被 ASIStudio/SharpCap/NINA 占用"
                print(f"[ZWO] {self.last_error}")
                return False

            ret = sdk.ASIInitCamera(self.camera_id)
            if ret != ASI_SUCCESS:
                self.last_error = f"初始化 ZWO 相机失败，ret={ret}"
                print(f"[ZWO] {self.last_error}")
                self.close()
                return False

            self._configure_roi_and_controls()

            ret = sdk.ASIStartVideoCapture(self.camera_id)
            if ret != ASI_SUCCESS:
                self.last_error = f"启动 ZWO 视频采集失败，ret={ret}"
                print(f"[ZWO] {self.last_error}")
                self.close()
                return False

            self.capture_started = True
            self.opened = True
            self.last_error = ""
            print(
                f"[ZWO] 已打开 ASI 相机 CameraID={self.camera_id}, "
                f"ROI={self._frame_width}x{self._frame_height}, "
                f"曝光={self.exposure_ms:.1f}ms, ISO/偏置={self.iso_value}, 增益={self.gain}, 自动曝光={self.auto_exposure}"
            )
            return True
        except Exception as exc:
            self.last_error = f"打开 ZWO 相机异常: {exc}"
            print(f"[ZWO] {self.last_error}")
            self.close()
            return False

    def _configure_roi_and_controls(self) -> None:
        """设置 ROI、图像格式、曝光和增益"""
        sdk = self._sdk
        # 根据 CameraID 反查属性枚举函数按 index 读属性，打开函数按 CameraID 打开
        max_w, max_h = self.width, self.height
        supported: list[int] = []
        try:
            num = int(sdk.ASIGetNumOfConnectedCameras())
            for idx in range(num):
                info = self._camera_info_by_index(idx)
                if info is not None and int(info.CameraID) == int(self.camera_id):
                    max_w = int(info.MaxWidth) or self.width
                    max_h = int(info.MaxHeight) or self.height
                    supported = [int(x) for x in info.SupportedVideoFormat if int(x) >= 0]
                    break
        except Exception:
            pass

        if ASI_IMG_RGB24 in supported:
            self._image_type = ASI_IMG_RGB24
            self._channels = 3
        elif ASI_IMG_Y8 in supported:
            self._image_type = ASI_IMG_Y8
            self._channels = 1
        else:
            self._image_type = ASI_IMG_RAW8
            self._channels = 1

        self._frame_width = max(8, min(int(self.width), int(max_w)))
        self._frame_height = max(8, min(int(self.height), int(max_h)))
        ret = sdk.ASISetROIFormat(self.camera_id, self._frame_width, self._frame_height, 1, self._image_type)
        if ret != ASI_SUCCESS:
            # 如果请求分辨率失败，降级到相机最大尺寸
            self._frame_width = int(max_w)
            self._frame_height = int(max_h)
            sdk.ASISetROIFormat(self.camera_id, self._frame_width, self._frame_height, 1, self._image_type)

        self.apply_controls(self.exposure_ms, self.iso_value, self.gain, self.auto_exposure)
        self._buffer = np.empty((self._frame_height, self._frame_width, self._channels), dtype=np.uint8)

    def apply_controls(self, exposure_ms: float, iso_value: int = 100, gain: int = 400, auto_exposure: bool = False) -> None:
        """写入曝光、ISO/亮度偏置和增益

        ZWO ASI 相机没有传统单反/手机相机意义上的 ISO为了让 UI 中的
        “ISO / 曝光 / 增益”成为三个独立控制项，这里把 ISO/亮度项映射为
        ZWO SDK 的 ASI_OFFSET，也就是黑电平/亮度偏置；增益仍然单独写入 ASI_GAIN
        """
        if self._sdk is None:
            return
        self.exposure_ms = max(0.01, float(exposure_ms))
        self.iso_value = max(0, min(255, int(iso_value)))
        self.gain = max(0, int(gain))
        self.auto_exposure = bool(auto_exposure)
        exposure_us = int(self.exposure_ms * 1000.0)
        self._sdk.ASISetControlValue(self.camera_id, ASI_EXPOSURE, exposure_us, 1 if self.auto_exposure else 0)
        self._sdk.ASISetControlValue(self.camera_id, ASI_OFFSET, self.iso_value, 0)
        self._sdk.ASISetControlValue(self.camera_id, ASI_GAIN, self.gain, 0)

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.opened or self._sdk is None or self._buffer is None:
            return False, None
        try:
            # 性能关键点：不要把 ASIGetVideoData 的 timeout 设成曝光时间的数倍
            # 曝光时间变长时，如果这里阻塞 1-5 秒，UI 点击“停止/应用参数”会明显卡住
            # 使用短 timeout 轮询：曝光没完成时很快返回 timeout；有新帧时立即取出
            # 这样长曝光下画面刷新慢是正常的，但界面操作仍然保持响应
            wait_ms = 80
            size = int(self._buffer.size)
            ptr = self._buffer.ctypes.data_as(ctypes.POINTER(ctypes.c_ubyte))
            ret = self._sdk.ASIGetVideoData(self.camera_id, ptr, size, wait_ms)
            if ret != ASI_SUCCESS:
                # timeout 在长曝光下是正常现象，不持续弹窗，只把失败交给采集线程短暂 sleep 后重试
                self.last_error = f"采集画面暂未就绪，ret={ret}"
                return False, None

            if self._channels == 3:
                frame = cv2.cvtColor(self._buffer, cv2.COLOR_RGB2BGR)
            else:
                gray = self._buffer.reshape((self._frame_height, self._frame_width))
                frame = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            return True, frame.copy()
        except Exception as exc:
            self.last_error = f"采集画面异常: {exc}"
            print(f"[ZWO] {self.last_error}")
            return False, None

    def close(self) -> None:
        if self._sdk is not None:
            try:
                if self.capture_started:
                    self._sdk.ASIStopVideoCapture(self.camera_id)
            except Exception:
                pass
            try:
                self._sdk.ASICloseCamera(self.camera_id)
            except Exception:
                pass
        self.capture_started = False
        self.opened = False
