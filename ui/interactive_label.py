# -*- coding: utf-8 -*-
"""将视频画布上的鼠标操作映射到原始相机坐标

QLabel 显示缩放后的图像，鼠标坐标不能直接作为相机像素坐标
启用画面缩放时还需将显示区域坐标反算到裁剪前的原始画面
"""
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
    # 滚轮信号使用 +1 或 -1，由主窗口统一修改缩放状态
    zoom_wheel_delta = pyqtSignal(int)

    def __init__(self) -> None:
        """初始化画布尺寸、鼠标状态和坐标映射信息"""
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMinimumSize(860, 560)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._dragging = False
        self._frame_size: Optional[Tuple[int, int]] = None  # 原始相机画面宽度和高度
        self._view_rect: Optional[Tuple[int, int, int, int]] = None  # 当前显示内容对应的原始裁剪区域
        self._pixmap_rect = QRect()  # 图像在 QLabel 中实际占用的矩形

    def set_frame_pixmap(self, pixmap: QPixmap, frame_width: int, frame_height: int,
                         view_rect: Optional[Tuple[int, int, int, int]] = None) -> None:
        """更新画面，并记录原始帧尺寸和放大裁剪区域

        view_rect=None 表示当前显示的是完整原始画面
        ``view_rect=(x, y, w, h)`` 表示当前显示的原始画面裁剪区域
        """
        self._frame_size = (frame_width, frame_height)
        self._view_rect = view_rect or (0, 0, frame_width, frame_height)

        # 保持原始比例缩放，避免画面被拉伸后圆形变成椭圆
        # 实时视频不使用 SmoothTransformation 以控制高分辨率绘制开销
        # 主窗口通常已按 QLabel 实际尺寸生成图像，尺寸吻合时直接复用
        # 仅在窗口刚调整大小时执行兜底缩放
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

        # 将控件坐标转换为当前显示图像内部的比例坐标
        nx = (pos.x() - self._pixmap_rect.x()) / self._pixmap_rect.width()
        ny = (pos.y() - self._pixmap_rect.y()) / self._pixmap_rect.height()

        # 将比例坐标映射到原始画面或放大后的裁剪区域
        x = view_x + nx * view_w
        y = view_y + ny * view_h

        # 做边界裁剪，防止鼠标拖到边缘时产生负数或超出图像范围
        return int(max(0, min(frame_w - 1, round(x)))), int(max(0, min(frame_h - 1, round(y))))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """按下左键时开始拖动并发送当前原始画面坐标"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            xy = self._pos_to_frame_xy(event.pos())
            if xy:
                self.center_changed.emit(*xy)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """拖动期间持续发送原始画面坐标"""
        if self._dragging:
            xy = self._pos_to_frame_xy(event.pos())
            if xy:
                self.center_changed.emit(*xy)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """释放左键时结束拖动"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False


    def wheelEvent(self, event: QWheelEvent) -> None:
        """鼠标位于画面上时，滚动滚轮直接控制放大倍率

        向上滚动放大，向下滚动缩小
        此处仅发出信号，真正修改 ``zoom_slider`` 的逻辑位于主窗口
        这样可以保证滚轮、右侧滑条和配置状态始终同步
        """
        delta_y = event.angleDelta().y()
        if delta_y == 0:
            event.ignore()
            return
        self.zoom_wheel_delta.emit(1 if delta_y > 0 else -1)
        event.accept()
