# -*- coding: utf-8 -*-
"""根据应用配置创建相机后端并枚举可用设备"""
from __future__ import annotations

import cv2

from core.app_state import AppConfig

from .base_camera import BaseCamera
from .qhy_camera import QHYCamera
from .synthetic_camera import SyntheticCamera
from .usb_camera import USBCamera
from .zwo_camera import ZWOCamera


def create_camera(config: AppConfig) -> BaseCamera:
    """根据配置创建相机后端

    注意：这里是唯一需要判断相机类型的地方
    主窗口、视频线程和视觉算法都不需要知道底层是哪一种相机
    """
    camera_type = (config.camera_type or "synthetic").lower()
    if camera_type == "usb":
        return USBCamera(
            config.camera_id,
            config.frame_width,
            config.frame_height,
            exposure_ms=config.camera_exposure_ms,
            iso_value=config.camera_iso,
            gain=config.camera_gain,
            auto_exposure=config.camera_auto_exposure,
            auto_focus=config.camera_auto_focus,
            focus=config.camera_focus,
        )
    if camera_type == "zwo":
        return ZWOCamera(
            camera_id=config.camera_id,
            dll_path=config.zwo_dll_path,
            width=config.frame_width,
            height=config.frame_height,
            exposure_ms=config.camera_exposure_ms,
            iso_value=config.camera_iso,
            gain=config.camera_gain,
            auto_exposure=config.camera_auto_exposure,
        )
    if camera_type == "qhy":
        return QHYCamera()
    return SyntheticCamera(config.frame_width, config.frame_height)


def list_camera_devices(camera_type: str, current_id: int = 0, max_usb_index: int = 8) -> list[tuple[int, str]]:
    """枚举指定相机类型下可选择的设备

    返回 ``[(device_id, display_name), ...]``
    界面显示 ``display_name`` 并将 ``device_id`` 存入 ``itemData``
    """
    kind = (camera_type or "synthetic").lower()
    if kind == "synthetic":
        return [(0, "0 - Synthetic test camera")]

    if kind == "zwo":
        # 未指定 DLL 时由 ZWOCamera 搜索常见安装路径
        # 用户手动指定 DLL 后由 MainWindow 传入路径重新枚举
        return ZWOCamera.discover()

    if kind == "usb":
        devices: list[tuple[int, str]] = []
        # 限制探测范围以免部分 Windows 设备扫描过慢
        for idx in range(max_usb_index + 1):
            # 与 USBCamera 使用相同后端顺序，避免默认后端遗漏 UVC 设备。
            for backend in USBCamera.capture_backends():
                cap = None
                ok = False
                try:
                    cap = cv2.VideoCapture()
                    ok = bool(cap.open(idx, backend) and cap.isOpened())
                except Exception:
                    pass
                finally:
                    if cap is not None:
                        try:
                            cap.release()
                        except Exception:
                            pass
                if ok:
                    devices.append((idx, f"{idx} - USB / UVC camera"))
                    break
        if not devices:
            # 保留当前编号以支持无法被枚举但可以手动打开的设备
            devices.append((int(current_id), f"{int(current_id)} - USB camera (manual)"))
        return devices

    if kind == "qhy":
        # QHY 后端尚未接入 SDK，保留占位设备以维持界面状态
        return [(0, "0 - QHY camera")]

    return [(0, "0 - Unknown camera")]
