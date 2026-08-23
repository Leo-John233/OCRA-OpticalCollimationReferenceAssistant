# -*- coding: utf-8 -*-
"""提供尚待接入 QHYCCD SDK 的 QHY 相机占位后端"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .base_camera import BaseCamera


class QHYCamera(BaseCamera):
    """QHY 相机的安全占位实现

    真正接入 QHY 时通常需要安装 QHYCCD SDK，并通过 Python/ctypes 包装调用
    当前实现保留统一接口，使后续接入 SDK 时无需修改界面和算法层
    """

    def open(self) -> bool:
        """报告后端尚未实现并返回打开失败"""
        print("[QHY] 当前只是占位后端请安装 QHY SDK 后在 qhy_camera.py 中实现真实采集逻辑")
        return False

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """返回无可用画面的占位结果"""
        return False, None

    def close(self) -> None:
        """结束占位后端且不执行资源释放操作"""
        pass
