# -*- coding: utf-8 -*-
"""通过 OpenCV 读取普通 USB 和 UVC 相机画面"""
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
    曝光、ISO、亮度和增益采用尽力设置策略
    驱动支持时参数生效，不支持时安全忽略
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
        """保存设备编号、画面尺寸和相机控制参数"""
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
        """打开相机并应用分辨率及控制参数"""
        # Windows 使用 DirectShow，其他系统使用 OpenCV 默认后端
        backend = cv2.CAP_DSHOW if platform.system().lower() == "windows" else 0
        self.cap = cv2.VideoCapture(self.camera_id, backend)
        # 指定后端打开失败后再使用 OpenCV 默认方式重试
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

        OpenCV 对 UVC 控制项没有统一量纲，不同驱动的含义可能不同

        - 部分 DirectShow 驱动使用对数曝光值而非毫秒
        - 多数 USB 摄像头没有真实 ISO，不支持时改用亮度
        - 增益仅在驱动支持 ``CAP_PROP_GAIN`` 时生效
        """
        if not self.cap or not self.cap.isOpened():
            return
        self.exposure_ms = max(0.01, float(exposure_ms))
        self.iso_value = max(0, int(iso_value))
        self.gain = max(0, int(gain))
        self.auto_exposure = bool(auto_exposure)
        self.auto_focus = bool(auto_focus)
        self.focus = max(0, int(focus))

        # DirectShow 通常以 0.25 表示手动曝光，0.75 表示自动曝光
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

        # 驱动不支持 ISO 时改用亮度以保留独立调节路径
        try:
            iso_prop = getattr(cv2, "CAP_PROP_ISO_SPEED", None)
            ok = False
            if iso_prop is not None:
                ok = bool(self.cap.set(iso_prop, float(self.iso_value)))
            if not ok:
                self.cap.set(cv2.CAP_PROP_BRIGHTNESS, float(self.iso_value))
        except Exception:
            pass

        # USB 和 UVC 电子对焦仅受部分摄像头驱动支持
        # 普通 OCAL 自制模组通常仍需旋转镜头完成物理对焦
        # 此处的手动对焦仅在驱动暴露 CAP_PROP_FOCUS 时生效
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
        """读取一帧画面并将失败结果统一为 ``None``"""
        if not self.cap or not self.cap.isOpened():
            return False, None
        ok, frame = self.cap.read()
        return ok, frame if ok else None

    def close(self) -> None:
        """释放 OpenCV 视频捕获资源"""
        if self.cap:
            self.cap.release()
            self.cap = None
