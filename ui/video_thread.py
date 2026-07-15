# -*- coding: utf-8 -*-
# 视频采集线程后台读取相机画面并通过Qt信号发给主线程，避免界面卡顿
# 设计：
# 1. 真实相机打开失败时只报告错误，不自动切回 synthetic，避免误判 ZWO 已启动
# 2. 采集线程内部限制 UI 发帧频率，减少高分辨率/长曝光时主界面绘制压力
# 3. 曝光、增益这类参数优先在线写入相机，不再每次应用参数都重启相机
from __future__ import annotations

import copy
import time
from threading import Lock
from typing import Optional, Tuple

import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal

from cameras.factory import create_camera
from core.app_state import AppConfig


class VideoThread(QThread):
    """相机后台线程

    摄像头会持续输出画面，如果直接在主线程读取，PyQt界面会卡顿
    因此用QThread读相机，再通过frame_signal把画面发回主线程显示
    """

    # 成功读取到一帧画面时发送
    frame_signal = pyqtSignal(np.ndarray)
    # 相机状态通过这个信号通知 UI
    status_signal = pyqtSignal(str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = copy.deepcopy(config)
        self._running = True
        self.camera = None

        # 参数在线更新队列UI 线程只把新参数放进来，由采集线程在安全位置写入 SDK
        self._lock = Lock()
        self._pending_controls: Optional[Tuple[float, int, int, bool, bool, int]] = None
        # Qt queued signal 默认会把每一帧排队UI 在高倍率缩放下若暂时绘制不过来，
        # 队列会持续增长，最终表现为越来越卡、延迟越来越大这里使用单帧背压：
        # 上一帧尚未被 UI 消费时不再发送新帧，只保留相机的最新采集进度
        self._frame_in_flight = False

        # 发给 UI 的最大帧率相机可以继续按自己的速度采集，但界面没必要每帧都重绘
        fps = int(getattr(self.config, "ui_fps_limit", 20) or 20)
        self._emit_interval = 1.0 / max(1, min(60, fps))
        self._last_emit_time = 0.0


    def set_fps_limit(self, fps: int) -> None:
        """在线调整发给 UI 的最大帧率

        这个选项只影响界面刷新频率，不改变相机真实曝光或采集参数
        长曝光或高分辨率时可以调低，例如 5-15 FPS；需要更流畅拖动时可以调高
        """
        fps = max(1, min(60, int(fps)))
        self.config.ui_fps_limit = fps
        self._emit_interval = 1.0 / fps

    def run(self) -> None:
        """线程入口：创建相机、循环读取画面、退出时释放资源"""
        self.camera = create_camera(self.config)
        if not self.camera.open():
            # 不自动降级到模拟相机，否则选择 ZWO 失败后 UI 会像“跳回 synthetic”
            # 同时把底层错误带回 UI，方便判断是 DLL 路径、位数、依赖还是设备被占用
            detail = getattr(self.camera, "last_error", "") or "camera_open_fail"
            self.status_signal.emit(f"camera_open_fail::{detail}")
            return

        self.status_signal.emit("camera_opened")
        while self._running:
            self._apply_pending_controls_if_needed()

            ok, frame = self.camera.read_frame()
            if ok and frame is not None:
                now = time.monotonic()
                if now - self._last_emit_time >= self._emit_interval:
                    should_emit = False
                    with self._lock:
                        if not self._frame_in_flight:
                            self._frame_in_flight = True
                            should_emit = True
                    if should_emit:
                        self._last_emit_time = now
                        self.frame_signal.emit(frame)
            else:
                # 不能sleep太久ZWO 长曝光时可能多次 timeout，短sleep能保证停止/改参数响应快
                self.msleep(5)

        if self.camera:
            self.camera.close()


    def mark_frame_consumed(self) -> None:
        """由 UI 在线程安全地确认上一帧已完成绘制
        该确认把事件队列中的视频帧数量限制为最多 1 帧，避免长时间运行后因积压
        旧帧造成内存增长、画面延迟和整个界面无法操作
        """
        with self._lock:
            self._frame_in_flight = False

    def request_camera_controls(
        self,
        exposure_ms: float,
        iso_value: int,
        gain: int,
        auto_exposure: bool,
        auto_focus: bool = True,
        focus: int = 0,
    ) -> None:
        """请求在线写入相机参数
        USB 后端会额外使用 auto_focus/focus；ZWO/QHY 后端没有该参数时会被安全忽略
        这个函数由 UI 线程调用，只记录参数，不直接跨线程操作 SDK
        """
        with self._lock:
            self._pending_controls = (
                float(exposure_ms),
                int(iso_value),
                int(gain),
                bool(auto_exposure),
                bool(auto_focus),
                int(focus),
            )

    def _apply_pending_controls_if_needed(self) -> None:
        """在采集线程内安全应用待写入的相机参数"""
        with self._lock:
            pending = self._pending_controls
            self._pending_controls = None
        if pending is None or self.camera is None:
            return
        if hasattr(self.camera, "apply_controls"):
            try:
                try:
                    self.camera.apply_controls(*pending)
                except TypeError:
                    # ZWO 等后端只接收曝光/亮度/增益/自动曝光四项
                    self.camera.apply_controls(*pending[:4])
                self.status_signal.emit("params_applied")
            except Exception as exc:  # pragma: no cover - 真实硬件错误直接回传 UI
                self.status_signal.emit(f"params_apply_fail::{exc}")

    def stop(self) -> None:
        """请求线程停止，并等待最多 0.8 秒让资源正常释放"""
        self._running = False
        self.wait(800)
