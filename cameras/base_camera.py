# -*- coding: utf-8 -*-
# 文件说明：相机抽象基类不同品牌相机都实现同一组 open/read_frame/close 接口
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

import numpy as np


class BaseCamera(ABC):
    """所有导星相机/行星相机后端的统一接口

    UI 层只依赖这个抽象类，不直接依赖具体品牌 SDK
    这样后续新增 ZWO、QHY、ToupTek 等相机时，只需要新增一个子类
    """

    @abstractmethod
    def open(self) -> bool:
        """打开相机，成功返回 True，失败返回 False"""
        pass

    @abstractmethod
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """读取一帧图像，返回 (是否成功, BGR图像矩阵)"""
        pass

    @abstractmethod
    def close(self) -> None:
        """释放相机资源，关闭 SDK 连接或 VideoCapture"""
        pass

    def name(self) -> str:
        """返回当前相机后端名称，用于调试或状态显示"""
        return self.__class__.__name__
