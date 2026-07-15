# -*- coding: utf-8 -*-
# 文件说明：普通 USB/UVC 相机后端通过 OpenCV VideoCapture 读取免驱摄像头画面
from __future__ import annotations

import platform
from typing import Optional, Tuple

import cv2
import numpy as np

from .base_camera import BaseCamera


class USBCamera(BaseCamera):
    """通用 USB/UVC 相机后端

    普通免驱摄像头、部分导星相机、电脑摄像头一般都可以通过这个后端读取
    Windows 下优先使用 DirectShow，通常能减少打开相机时的等待时间

    注意：不同 USB 摄像头驱动暴露的控制项不完全一致
    这里对曝光、ISO/亮度、增益采用“尽力设置”：驱动支持就生效，不支持则安全忽略
    """

    def __init__(
        self,
        camera_id: int = 0,
        width: int = 1280,
        height: int = 720,
        exposure_ms: float = 50.0,
        iso_value: int = 100,
        gain: int = 400,
        auto_exposure: bool = False,
        auto_focus: bool = True,
        focus: int = 0,
    ) -> None:
        self.camera_id = int(camera_id)
        self.width = int(width)
        self.height = int(height)
        self.exposure_ms = float(exposure_ms)
        self.iso_value = int(iso_value)
        self.gain = int(gain)
        self.auto_exposure = bool(auto_exposure)
        self.auto_focus = bool(auto_focus)
        self.focus = int(focus)
        self.cap: Optional[cv2.VideoCapture] = None

    def open(self) -> bool:
        # Windows 使用 DirectShow；其他系统使用 OpenCV 默认后端
        backend = cv2.CAP_DSHOW if platform.system().lower() == "windows" else 0
        self.cap = cv2.VideoCapture(self.camera_id, backend)
        # 如果指定后端打开失败，再用 OpenCV 默认方式重试一次
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.camera_id)
        if self.cap and self.cap.isOpened():
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.apply_controls(self.exposure_ms, self.iso_value, self.gain, self.auto_exposure, self.auto_focus, self.focus)
            return True
        return False

    def apply_controls(
        self,
        exposure_ms: float,
        iso_value: int = 100,
        gain: int = 400,
        auto_exposure: bool = False,
        auto_focus: bool = True,
        focus: int = 0,
    ) -> None:
        """在线写入 USB 摄像头参数

        OpenCV 对 UVC 控制项没有统一量纲，不同驱动含义可能不同：
        - 曝光：部分 Windows DirectShow 驱动使用对数曝光值，不是真正的毫秒
        - ISO：多数 USB 摄像头没有真实 ISO，CAP_PROP_ISO_SPEED 不支持时自动改写亮度
        - 增益：驱动支持 CAP_PROP_GAIN 时生效
        """
        if not self.cap or not self.cap.isOpened():
            return
        self.exposure_ms = max(0.01, float(exposure_ms))
        self.iso_value = max(0, int(iso_value))
        self.gain = max(0, int(gain))
        self.auto_exposure = bool(auto_exposure)
        self.auto_focus = bool(auto_focus)
        self.focus = max(0, int(focus))

        # 自动曝光在不同后端取值不同DirectShow 常见：0.25=手动，0.75=自动
        try:
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.75 if self.auto_exposure else 0.25)
        except Exception:
            pass
        try:
            self.cap.set(cv2.CAP_PROP_EXPOSURE, float(self.exposure_ms))
        except Exception:
            pass
        try:
            self.cap.set(cv2.CAP_PROP_GAIN, float(self.gain))
        except Exception:
            pass

        # ISO 如果驱动不支持，退而求其次调整亮度，保证“ISO/亮度”这个独立项有可用路径
        try:
            iso_prop = getattr(cv2, "CAP_PROP_ISO_SPEED", None)
            ok = False
            if iso_prop is not None:
                ok = bool(self.cap.set(iso_prop, float(self.iso_value)))
            if not ok:
                self.cap.set(cv2.CAP_PROP_BRIGHTNESS, float(self.iso_value))
        except Exception:
            pass

        # USB/UVC 电子对焦：只有部分摄像头驱动支持
        # 普通 OCAL 自制模组多数仍需手动旋转镜头完成物理对焦；
        # 这里的“手动对焦”只在驱动暴露 CAP_PROP_FOCUS 时生效
        try:
            auto_focus_prop = getattr(cv2, "CAP_PROP_AUTOFOCUS", None)
            if auto_focus_prop is not None:
                self.cap.set(auto_focus_prop, 1.0 if self.auto_focus else 0.0)
        except Exception:
            pass
        if not self.auto_focus:
            try:
                self.cap.set(cv2.CAP_PROP_FOCUS, float(self.focus))
            except Exception:
                pass

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        if not self.cap or not self.cap.isOpened():
            return False, None
        ok, frame = self.cap.read()
        return ok, frame if ok else None

    def close(self) -> None:
        if self.cap:
            self.cap.release()
            self.cap = None
