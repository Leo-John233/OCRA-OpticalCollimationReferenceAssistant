# -*- coding: utf-8 -*-
# 文件说明：可交互视频画布负责把鼠标点击/拖拽位置映射回原始相机坐标
# 设计逻辑：
# 1. QLabel 显示的是缩放后的图像，鼠标坐标不能直接当作相机像素坐标
# 2. 当启用画面放大时，屏幕上显示的是原始画面的一个裁剪区域，因此还要把鼠标坐标反算回裁剪前的原始坐标
from __future__ import annotations

from typing import Optional, Tuple

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QMouseEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QLabel, QSizePolicy


class InteractiveVideoLabel(QLabel):
    """支持鼠标交互的视频显示控件

    鼠标拖动后会发出原始相机坐标，主窗口再用这个坐标移动参考中心
    这里不直接修改 config，是为了让 UI 控件只负责交互，不参与业务逻辑
    """

    # 鼠标拖动后发出新的原始画面坐标
    center_changed = pyqtSignal(int, int)
    # 鼠标滚轮缩放信号参数为 +1 或 -1，由主窗口去调整 zoom_slider，避免控件直接改业务参数
    zoom_wheel_delta = pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(860, 560)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._dragging = False
        self._frame_size: Optional[Tuple[int, int]] = None  # 原始相机画面 width, height
        self._view_rect: Optional[Tuple[int, int, int, int]] = None  # 当前显示内容对应的原始裁剪区域 x,y,w,h
        self._pixmap_rect = QRect()  # pixmap 在 QLabel 中实际占用的矩形

    def set_frame_pixmap(self, pixmap: QPixmap, frame_width: int, frame_height: int,
                         view_rect: Optional[Tuple[int, int, int, int]] = None) -> None:
        """更新画面，并记录原始帧尺寸和放大裁剪区域

        view_rect=None 表示当前显示的是完整原始画面
        view_rect=(x,y,w,h) 表示当前显示的是原始画面的这个裁剪区域，例如 2 倍放大时只显示中心附近一半宽高
        """
        self._frame_size = (frame_width, frame_height)
        self._view_rect = view_rect or (0, 0, frame_width, frame_height)

        # 保持原始比例缩放，避免画面被拉伸后圆形变成椭圆
        # 性能优化：实时视频刷新时不要使用 SmoothTransformation，否则高分辨率下会明显增加 UI 绘制开销
        # 主窗口通常已经按 QLabel 的实际显示尺寸生成了 pixmap尺寸吻合时直接复用，
        # 避免每帧再做一次 Qt 缩放和临时图像分配；窗口刚调整大小时才执行兜底缩放
        fits_now = (
            pixmap.width() <= self.width()
            and pixmap.height() <= self.height()
            and (abs(pixmap.width() - self.width()) <= 2 or abs(pixmap.height() - self.height()) <= 2)
        )
        if fits_now:
            scaled = pixmap
        else:
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation,
            )

        # 计算缩放后图像在 QLabel 中的真实显示矩形
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self._pixmap_rect = QRect(x, y, scaled.width(), scaled.height())
        self.setPixmap(scaled)

    def _pos_to_frame_xy(self, pos: QPoint) -> Optional[Tuple[int, int]]:
        """把 QLabel 内的鼠标位置转换成原始相机画面的像素坐标"""
        if self._frame_size is None or self._view_rect is None:
            return None
        if self._pixmap_rect.width() <= 0 or self._pixmap_rect.height() <= 0:
            return None
        if not self._pixmap_rect.contains(pos):
            return None

        frame_w, frame_h = self._frame_size
        view_x, view_y, view_w, view_h = self._view_rect

        # 第一步：控件坐标 -> 当前显示图像内部的比例坐标
        nx = (pos.x() - self._pixmap_rect.x()) / self._pixmap_rect.width()
        ny = (pos.y() - self._pixmap_rect.y()) / self._pixmap_rect.height()

        # 第二步：比例坐标 -> 原始相机坐标如果启用了放大，就映射回裁剪区域
        x = view_x + nx * view_w
        y = view_y + ny * view_h

        # 做边界裁剪，防止鼠标拖到边缘时产生负数或超出图像范围
        return int(max(0, min(frame_w - 1, round(x)))), int(max(0, min(frame_h - 1, round(y))))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            xy = self._pos_to_frame_xy(event.pos())
            if xy:
                self.center_changed.emit(*xy)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._dragging:
            xy = self._pos_to_frame_xy(event.pos())
            if xy:
                self.center_changed.emit(*xy)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False


    def wheelEvent(self, event: QWheelEvent) -> None:
        """鼠标位于画面上时，滚动滚轮直接控制放大倍率

        向上滚动放大，向下滚动缩小这里仅发信号，真正修改 zoom_slider 的逻辑放在 MainWindow 中，
        这样可以保证滚轮、右侧滑条和配置状态始终同步
        """
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            event.ignore()
            return
        self.zoom_wheel_delta.emit(1 if delta_y > 0 else -1)
        event.accept()
