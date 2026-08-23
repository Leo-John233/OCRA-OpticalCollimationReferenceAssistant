# -*- coding: utf-8 -*-
"""生成仿 OCAL 光轴画面以支持无硬件测试"""
from __future__ import annotations

import math
import time
from typing import Optional, Tuple

import cv2
import numpy as np

from .base_camera import BaseCamera


class SyntheticCamera(BaseCamera):
    """无硬件测试用模拟相机

    用黑底、同心圆、中心亮斑和十字遮挡模拟 OCAL 画面
    这样没有接入真实导星相机时，也能测试界面、保存参数和自动吸附算法
    """

    def __init__(self, width: int = 1280, height: int = 720) -> None:
        """初始化模拟画面尺寸和动画时钟"""
        self.width = int(width)
        self.height = int(height)
        self._opened = False
        self._t0 = time.time()

    def open(self) -> bool:
        """启用模拟画面生成"""
        self._opened = True
        return True

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """生成包含动态圆环、亮斑、支架阴影和噪声的测试帧"""
        if not self._opened:
            return False, None
        t = time.time() - self._t0
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        center = (self.width // 2 + int(math.sin(t * 0.45) * 26), self.height // 2 + int(math.cos(t * 0.37) * 18))
        # 用柔和圆环和中心亮斑模拟真实准直画面
        cv2.circle(frame, center, min(self.width, self.height) // 4, (45, 45, 45), 4, cv2.LINE_AA)
        cv2.circle(frame, center, min(self.width, self.height) // 8, (80, 80, 80), 2, cv2.LINE_AA)
        cv2.circle(frame, center, 10, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, center, 22, (180, 180, 180), 1, cv2.LINE_AA)
        # 模拟牛顿反射式望远镜的十字副镜支架阴影
        cv2.line(frame, (center[0], 0), (center[0], self.height), (25, 25, 25), 3)
        cv2.line(frame, (0, center[1]), (self.width, center[1]), (25, 25, 25), 3)
        noise = np.random.default_rng().normal(0, 3, frame.shape).astype(np.int16)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        time.sleep(0.015)
        return True, frame

    def close(self) -> None:
        """停止生成模拟画面"""
        self._opened = False
