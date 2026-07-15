# -*- coding: utf-8 -*-
# 文件说明：相机工厂根据配置选择模拟相机、普通 USB 相机、ZWO 或 QHY 后端
# 同时提供设备枚举函数，把“相机编号”改为“识别到的相机下拉选择”
from __future__ import annotations

import cv2

from core.app_state import AppConfig

from .base_camera import BaseCamera
from .qhy_camera import QHYCamera
from .synthetic_camera import SyntheticCamera
from .usb_camera import USBCamera
from .zwo_camera import ZWOCamera


def create_camera(config: AppConfig) -> BaseCamera:
    """根据配置创建具体相机对象

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
    """枚举当前相机类型下可选择的设备

    返回值格式为 [(device_id, display_name), ...]
    UI 直接把 display_name 显示在下拉框里，把 device_id 存为 itemData
    """
    kind = (camera_type or "synthetic").lower()
    if kind == "synthetic":
        return [(0, "0 - Synthetic test camera")]

    if kind == "zwo":
        # 这里不传 dll_path，由 ZWOCamera 按常见路径自动搜索
        # 如果用户在 UI 中手动指定了 DLL，MainWindow 会直接调用 ZWOCamera.discover(dll_path)
        return ZWOCamera.discover()

    if kind == "usb":
        devices: list[tuple[int, str]] = []
        # 只扫前几个编号，避免部分 Windows 机器扫描过慢
        for idx in range(max_usb_index + 1):
            cap = cv2.VideoCapture(idx)
            ok = cap.isOpened()
            cap.release()
            if ok:
                devices.append((idx, f"{idx} - USB / DirectShow camera"))
        if not devices:
            # 没扫到时保留当前编号，用户仍然可以尝试打开
            devices.append((int(current_id), f"{int(current_id)} - USB camera (manual)"))
        return devices

    if kind == "qhy":
        # QHY 后端目前是占位接口保留一个选项，避免 UI 为空
        return [(0, "0 - QHY camera")]

    return [(0, "0 - Unknown camera")]
