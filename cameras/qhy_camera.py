# -*- coding: utf-8 -*-
# 文件说明：QHY 相机预留后端后续接入 QHYCCD SDK 时只需要完善这个文件
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .base_camera import BaseCamera


class QHYCamera(BaseCamera):
    """QHY 相机的安全占位实现

    真正接入 QHY 时通常需要安装 QHYCCD SDK，并通过 Python/ctypes 包装调用
    现在先保留统一接口，保证文件树稳定后续只改本文件，不需要改 UI 和算法层
    """

    def open(self) -> bool:
        print("[QHY] 当前只是占位后端请安装 QHY SDK 后在 qhy_camera.py 中实现真实采集逻辑")
        return False

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        return False, None

    def close(self) -> None:
        pass
