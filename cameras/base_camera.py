# -*- coding: utf-8 -*-
"""定义所有相机后端必须实现的统一采集接口"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

import numpy as np


class BaseCamera(ABC):
    """导星相机和行星相机后端的统一接口

    UI 层只依赖这个抽象类，不直接依赖具体品牌 SDK
    这样后续新增 ZWO、QHY、ToupTek 等相机时，只需要新增一个子类
    """

    @abstractmethod
    def open(self) -> bool:
        """打开相机并返回初始化是否成功"""
        pass

    @abstractmethod
    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """读取一帧图像并返回成功状态及 BGR 图像矩阵"""
        pass

    @abstractmethod
    def close(self) -> None:
        """停止采集并释放 SDK 连接或视频捕获资源"""
        pass

    def name(self) -> str:
        """返回用于日志和状态显示的相机后端名称"""
        return self.__class__.__name__
