# -*- coding: utf-8 -*-
"""通过 OpenCV 读取普通 USB 和 UVC 相机画面"""
from __future__ import annotations

import math
import platform
from typing import Optional, Tuple

import cv2
import numpy as np

from .base_camera import BaseCamera


class USBCamera(BaseCamera):
    """通过系统视频后端采集 USB/UVC 相机，输出 uint8 BGR 图像。

    Windows 优先 DirectShow，Linux 优先 V4L2；控制项由设备驱动决定，
    不支持的曝光、ISO/亮度、增益和对焦设置不会中断采集。
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
        """保存设备编号、请求尺寸及控制参数。"""
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
        self.last_error = ""
        self._backend = cv2.CAP_ANY
        self._v4l_raw_controls = False
        self._first_frame: Optional[np.ndarray] = None

    @staticmethod
    def capture_backends() -> Tuple[int, ...]:
        """返回枚举和采集共用的系统后端优先顺序。"""
        system = platform.system().lower()
        if system == "windows":
            return cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY
        if system == "linux":
            return cv2.CAP_V4L2, cv2.CAP_ANY
        if system == "darwin":
            return cv2.CAP_AVFOUNDATION, cv2.CAP_ANY
        return (cv2.CAP_ANY,)

    def open(self) -> bool:
        """协商视频模式并验证首帧，失败时释放连接并尝试下一后端。"""
        self.close()
        self.last_error = ""
        if self.camera_id < 0 or self.width <= 0 or self.height <= 0:
            self.last_error = "USB/UVC 设备编号必须非负，画面尺寸必须大于零"
            return False

        errors = []
        for backend in self.capture_backends():
            # 每次重新连接，避免不支持的分辨率或编码使驱动停留在错误状态。
            for mode in ("requested", "mjpeg", "default"):
                try:
                    cap = cv2.VideoCapture()
                    self.cap = cap
                    if not cap.open(self.camera_id, backend) or not cap.isOpened():
                        errors.append(f"backend={backend}: 无法打开设备")
                        break
                    self._backend = backend
                    try:
                        actual_backend = int(cap.get(cv2.CAP_PROP_BACKEND))
                        if actual_backend > 0:
                            self._backend = actual_backend
                    except Exception:
                        pass

                    if mode == "mjpeg":
                        self._set_property(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
                    if mode != "default":
                        self._set_property(cv2.CAP_PROP_FRAME_WIDTH, self.width)
                        self._set_property(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
                    self._set_property(cv2.CAP_PROP_CONVERT_RGB, 1.0)
                    self._set_property(cv2.CAP_PROP_BUFFERSIZE, 1.0)
                    # V4L2 关闭 OpenCV 的历史 [0, 1] 归一化，使用 UVC 原始量纲。
                    self._v4l_raw_controls = (
                        self._backend == cv2.CAP_V4L2
                        and self._set_property(cv2.CAP_PROP_MODE, 0.0)
                    )
                    self.apply_controls(
                        self.exposure_ms, self.iso_value, self.gain,
                        self.auto_exposure, self.auto_focus, self.focus,
                    )
                    # 某些 UVC 设备启动时会返回少量空帧。
                    for _ in range(5):
                        ok, frame = self.read_frame()
                        if ok and frame is not None:
                            self._first_frame = frame
                            self.last_error = ""
                            return True
                    errors.append(f"backend={backend}, mode={mode}: {self.last_error}")
                except Exception as exc:
                    errors.append(f"backend={backend}, mode={mode}: {exc}")
                finally:
                    if self._first_frame is None:
                        self.close()

        self.last_error = (
            f"USB/UVC 相机 {self.camera_id} 打开失败，请检查设备占用、相机权限和 USB 连接；"
            + "；".join(errors)
        )
        return False

    def _set_property(self, prop: int, value: float) -> bool:
        """尽力写入驱动属性，隔离不支持的控制项和驱动异常。"""
        if self.cap is None:
            return False
        try:
            return bool(self.cap.set(prop, float(value)))
        except Exception:
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
        """保存在线参数，并按实际后端量纲设置曝光和 UVC 控制项。"""
        exposure = float(exposure_ms)
        self.exposure_ms = max(0.01, exposure) if math.isfinite(exposure) else 50.0
        self.iso_value = max(0, int(iso_value))
        self.gain = max(0, int(gain))
        self.auto_exposure = bool(auto_exposure)
        self.auto_focus = bool(auto_focus)
        self.focus = max(0, int(focus))
        self._first_frame = None
        if self.cap is None:
            return
        try:
            if not self.cap.isOpened():
                return
        except Exception:
            return

        if self._backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF):
            auto_value = 1.0 if self.auto_exposure else 0.0
            exposure_value = float(round(math.log2(self.exposure_ms / 1000.0)))
        elif self._backend == cv2.CAP_V4L2:
            auto_value = (
                (3.0 if self.auto_exposure else 1.0) if self._v4l_raw_controls
                else (0.75 if self.auto_exposure else 0.25)
            )
            exposure_value = float(max(1, round(self.exposure_ms * 10.0)))
        else:
            auto_value = 1.0 if self.auto_exposure else 0.0
            exposure_value = self.exposure_ms
        self._set_property(cv2.CAP_PROP_AUTO_EXPOSURE, auto_value)
        # Windows 写入曝光值会同时切回手动模式，自动曝光时不写手动值。
        if not self.auto_exposure and (
            self._backend != cv2.CAP_V4L2 or self._v4l_raw_controls
        ):
            self._set_property(cv2.CAP_PROP_EXPOSURE, exposure_value)
        self._set_property(cv2.CAP_PROP_GAIN, self.gain)

        iso_prop = getattr(cv2, "CAP_PROP_ISO_SPEED", None)
        if iso_prop is None or not self._set_property(iso_prop, self.iso_value):
            self._set_property(cv2.CAP_PROP_BRIGHTNESS, self.iso_value)
        self._set_property(cv2.CAP_PROP_AUTOFOCUS, 1.0 if self.auto_focus else 0.0)
        if not self.auto_focus:
            self._set_property(cv2.CAP_PROP_FOCUS, self.focus)

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """读取 BGR 图像，将空帧、断连和驱动异常统一返回为失败。"""
        if self.cap is None:
            self.last_error = "USB/UVC 相机未打开"
            return False, None
        try:
            if not self.cap.isOpened():
                self.last_error = "USB/UVC 相机连接已关闭"
                return False, None
            if self._first_frame is not None:
                frame = self._first_frame
                self._first_frame = None
            else:
                ok, frame = self.cap.read()
                if not ok or not isinstance(frame, np.ndarray) or frame.size == 0:
                    self.last_error = "USB/UVC 相机未返回有效画面"
                    return False, None
            if frame.dtype != np.uint8:
                self.last_error = f"USB/UVC 不支持的图像数据类型：{frame.dtype}"
                return False, None
            if frame.ndim == 2 or (frame.ndim == 3 and frame.shape[2] == 1):
                frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
            elif frame.ndim == 3 and frame.shape[2] == 4:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
            elif frame.ndim != 3 or frame.shape[2] != 3:
                self.last_error = f"USB/UVC 不支持的图像格式：{frame.shape}"
                return False, None
            self.last_error = ""
            return True, np.ascontiguousarray(frame)
        except Exception as exc:
            self.last_error = f"USB/UVC 读取失败：{exc}"
            return False, None

    def close(self) -> None:
        """释放视频连接，重复关闭和驱动释放异常均不会影响退出。"""
        cap = self.cap
        self.cap = None
        self._first_frame = None
        self._backend = cv2.CAP_ANY
        self._v4l_raw_controls = False
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
