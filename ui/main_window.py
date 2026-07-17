# -*- coding: utf-8 -*-
# 文件说明：主窗口和右侧控制面板负责 UI 布局、按钮事件、参数同步和状态显示
# 设计逻辑：
# 1. 左侧显示实时画面，右侧集中放置OCAL风格控制面板
# 2. Circle 1 外圈绑定镜筒边缘参考中心，Circle 2/3 和星标绑定吸附后的内圈中心
# 3. 三个圆和中心星标都可以独立启用、调半径/线宽/颜色颜色用短色块按钮选择
# 4. 画面放大采用“围绕参考中心裁剪后再放大显示”的方式，坐标映射仍保持准确
# 5. 设为零点后，后续检测中心会与该参考中心比较，并给出 RIGHT/DOWN 等调整提示
from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import cv2
import numpy as np
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QColor, QImage, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.app_state import AppConfig, CircleConfig
from core.config_manager import ConfigManager
from core.environment_check import EnvironmentReport, run_environment_check
from core.i18n import I18nManager
from core.vision_engine import VisionEngine
from cameras.factory import list_camera_devices
from cameras.zwo_camera import ZWOCamera
from ui.environment_dialog import EnvironmentCheckDialog
from ui.interactive_label import InteractiveVideoLabel
from ui.video_thread import VideoThread


# 颜色在配置文件中统一保存为 OpenCV 的 BGR 三元组
# UI 上不再显示 Green/Red/Blue 这种文字选项，而是用短小的纯色按钮直接表示当前颜色
def bgr_to_qcolor(color: Tuple[int, int, int]) -> QColor:
    """OpenCV BGR -> Qt RGB"""
    b, g, r = color
    return QColor(r, g, b)


def qcolor_to_bgr(color: QColor) -> Tuple[int, int, int]:
    """Qt RGB -> OpenCV BGR"""
    return int(color.blue()), int(color.green()), int(color.red())



class DampedSlider(QSlider):
    """带阻尼的滑块

    普通 QSlider 在范围很大时，鼠标轻微移动就会造成几十甚至上百像素变化
    这里把鼠标拖动量按 damping 系数缩小，保留键盘方向键和程序 setValue 的正常行为
    """

    def __init__(self, orientation: Qt.Orientation, damping: float = 0.28) -> None:
        super().__init__(orientation)
        self._damping = max(0.05, min(1.0, float(damping)))
        self._drag_start_pos: Optional[float] = None
        self._drag_start_value: int = 0
        self.setSingleStep(1)
        self.setPageStep(5)

    def mousePressEvent(self, event):  # noqa: ANN001, N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().x() if self.orientation() == Qt.Orientation.Horizontal else event.position().y()
            self._drag_start_value = self.value()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: ANN001, N802
        if self._drag_start_pos is not None:
            current_pos = event.position().x() if self.orientation() == Qt.Orientation.Horizontal else event.position().y()
            delta_px = current_pos - self._drag_start_pos
            if self.orientation() == Qt.Orientation.Vertical:
                delta_px = -delta_px
            span_px = max(1, self.width() if self.orientation() == Qt.Orientation.Horizontal else self.height())
            value_span = max(1, self.maximum() - self.minimum())
            delta_value = int(round(delta_px / span_px * value_span * self._damping))
            self.setValue(max(self.minimum(), min(self.maximum(), self._drag_start_value + delta_value)))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: ANN001, N802
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    """程序主窗口"""

    def __init__(self) -> None:
        super().__init__()
        self.config_manager = ConfigManager()
        self.config: AppConfig = self.config_manager.load()
        self.i18n = I18nManager(self.config.language)

        self.thread: Optional[VideoThread] = None
        self.current_frame: Optional[np.ndarray] = None
        self.environment_dialog: Optional[EnvironmentCheckDialog] = None
        self._startup_environment_report: Optional[EnvironmentReport] = None

        # 三圈使用不同圆心：外圈为参考中心；中圈/内圈为各自识别后的目标圆心
        self.middle_xy: Tuple[int, int] = (int(self.config.circle2_center_x), int(self.config.circle2_center_y))
        self.inner_xy: Tuple[int, int] = (int(self.config.circle3_center_x), int(self.config.circle3_center_y))
        self.secondary_xy: Tuple[int, int] = (int(self.config.circle4_center_x), int(self.config.circle4_center_y))
        self.active_target: str = self.config.active_target if self.config.active_target in {"middle", "inner", "secondary"} else "middle"
        self.detected_xy: Optional[Tuple[int, int]] = self._active_xy()
        self.last_score = 0.0
        # 分别记录中圈/内圈最近一次持续吸附或手动吸附的识别分数
        # HUD 会根据当前启用的持续吸附目标选择对应分数，避免中圈和内圈互相覆盖
        self._target_scores: Dict[str, float] = {"middle": 0.0, "inner": 0.0, "secondary": 0.0}
        self.last_source_key = "source_waiting"
        self.last_status_key = "waiting"
        self.last_status_detail = ""

        # 外圈为三次按钮吸附定圆：每次点击右侧吸附外圈边缘按钮，
        # 都调用源代码原有的自动外圈拟合并记录一次圆心/半径结果；第三次后
        # 对三次结果做一致性筛选和加权融合整个过程不需要鼠标点击外圆边缘
        self._outer_three_point_mode = False
        self._outer_snap_results: list[Tuple[int, int, int]] = []
        self._outer_snap_scores: list[float] = []
        # 每次按钮吸附保存本轮鲁棒拟合的原始内点第三次点击时不再平均三个圆，
        # 而是合并有效轮次的全部内点后做一次联合几何拟合
        self._outer_snap_point_sets: list[np.ndarray] = []
        self._outer_snap_infos: list[Dict[str, object]] = []
        self._outer_snap_start_geometry: Optional[Tuple[int, int, int]] = None
        # 第 3 次按钮吸附完成后，先让 UI 显示 3/3 和第三轮单独拟合结果，
        # 再在下一次事件循环中执行三轮联合拟合防止第三轮结果被最终结果
        # 在同一按钮回调内立刻覆盖，造成视觉上像只吸附了两次
        self._outer_finalize_pending = False

        # 自动跟踪不是每帧都跑，避免低性能机器卡顿
        self._frame_counter = 0
        self._render_counter = 0
        self._history: Dict[str, list[float]] = {"dx": [], "dy": [], "dist": [], "score": []}
        self._updating_ui = False

        # 相机参数实时更新采用“防抖”方式：用户输入曝光/增益后，等 250ms 没有继续输入再写入 SDK
        # 这样不用每次点“应用参数”，同时避免每敲一个数字就频繁调用相机 SDK
        self._camera_param_timer = QTimer(self)
        self._camera_param_timer.setSingleShot(True)
        self._camera_param_timer.setInterval(250)
        self._camera_param_timer.timeout.connect(self._apply_camera_params_debounced)

        self._build_ui()
        self._sync_all_controls_from_config()
        self._apply_language()

        # 在相机线程启动前做一次完整环境自检，避免 USB 探测与采集线程争抢设备。
        # 正常环境不弹窗；只有存在阻断性错误时，主窗口显示后自动打开详细报告。
        self._startup_environment_report = self._collect_environment_report(probe_hardware=True)
        if self._startup_environment_report.has_errors:
            QTimer.singleShot(0, self._show_startup_environment_issues)
        self.start_camera()


    def _fallback_target(self) -> str:
        """返回当前可作为调节对象的目标圆

        中圈/内圈/副镜如果启用了“与外圈同心”，就只是辅助同心圆，不再作为检测目标
        """
        if not self.config.middle_concentric_with_outer:
            return "middle"
        if not self.config.inner_concentric_with_outer:
            return "inner"
        if not self.config.secondary_concentric_with_outer:
            return "secondary"
        return "middle"

    def _active_xy(self) -> Tuple[int, int]:
        """返回当前 Guide 使用的目标圆心"""
        if self.active_target == "middle" and not self.config.middle_concentric_with_outer:
            return self.middle_xy
        if self.active_target == "inner" and not self.config.inner_concentric_with_outer:
            return self.inner_xy
        if self.active_target == "secondary" and not self.config.secondary_concentric_with_outer:
            return self.secondary_xy
        fallback = self._fallback_target()
        if fallback == "inner":
            return self.inner_xy
        if fallback == "secondary":
            return self.secondary_xy
        if not self.config.middle_concentric_with_outer:
            return self.middle_xy
        return (int(self.config.center_x), int(self.config.center_y))

    def _set_active_target(self, target: str) -> None:
        """切换当前调节目标"""
        if target == "middle" and self.config.middle_concentric_with_outer:
            target = self._fallback_target()
        if target == "inner" and self.config.inner_concentric_with_outer:
            target = self._fallback_target()
        if target == "secondary" and self.config.secondary_concentric_with_outer:
            target = self._fallback_target()
        self.active_target = target if target in {"middle", "inner", "secondary"} else self._fallback_target()
        self.config.active_target = self.active_target
        self.detected_xy = self._active_xy()

    def _set_target_xy(self, target: str, x: int, y: int) -> None:
        """更新中圈、内圈或副镜检测圆心，并同步到 config，便于保存和下次恢复"""
        x, y = int(x), int(y)
        if target == "middle" and self.config.middle_concentric_with_outer:
            return
        if target == "inner" and self.config.inner_concentric_with_outer:
            return
        if target == "secondary" and self.config.secondary_concentric_with_outer:
            return
        if target == "inner":
            self.inner_xy = (x, y)
            self.config.circle3_center_x = x
            self.config.circle3_center_y = y
        elif target == "secondary":
            self.secondary_xy = (x, y)
            self.config.circle4_center_x = x
            self.config.circle4_center_y = y
        else:
            self.middle_xy = (x, y)
            self.config.circle2_center_x = x
            self.config.circle2_center_y = y
        self._set_active_target(target)
        self._sync_target_sliders()

    def _hud_targets(self) -> list[dict]:
        """根据“持续吸附”开关生成 HUD 目标列表

        逻辑说明：
        1. 如果只勾选中圈持续吸附，HUD 的检测目标和 dx/dy/dist/Guide 都显示中圈
        2. 如果只勾选内圈持续吸附，HUD 的检测目标和 dx/dy/dist/Guide 都显示内圈
        3. 如果中圈和内圈都勾选，HUD 同时显示两组偏移数据，避免单一 Guide 掩盖另一个圆的状态
        4. 如果没有持续吸附，则保持原来的当前调节目标逻辑
        """
        targets: list[dict] = []
        if bool(self.config.track_middle) and not self.config.middle_concentric_with_outer:
            targets.append({
                "kind": "middle",
                "name_key": "hud_target_middle",
                "source_key": "source_middle_tracking",
                "xy": self.middle_xy,
                "score": self._target_scores.get("middle", self.last_score),
            })
        if bool(self.config.track_inner) and not self.config.inner_concentric_with_outer:
            targets.append({
                "kind": "inner",
                "name_key": "hud_target_inner",
                "source_key": "source_inner_tracking",
                "xy": self.inner_xy,
                "score": self._target_scores.get("inner", self.last_score),
            })
        if bool(self.config.track_secondary) and not self.config.secondary_concentric_with_outer:
            targets.append({
                "kind": "secondary",
                "name_key": "hud_target_secondary",
                "source_key": "source_secondary_tracking",
                "xy": self.secondary_xy,
                "score": self._target_scores.get("secondary", self.last_score),
            })

        if targets:
            return targets

        # 没有持续吸附时，仍然按当前手动调节目标显示
        if self.active_target == "secondary" and not self.config.secondary_concentric_with_outer:
            return [{
                "kind": "secondary",
                "name_key": "hud_target_secondary",
                "source_key": "source_secondary_edge",
                "xy": self.secondary_xy,
                "score": self._target_scores.get("secondary", self.last_score),
            }]
        if self.active_target == "inner" and not self.config.inner_concentric_with_outer:
            return [{
                "kind": "inner",
                "name_key": "hud_target_inner",
                "source_key": "source_inner_edge",
                "xy": self.inner_xy,
                "score": self._target_scores.get("inner", self.last_score),
            }]
        if not self.config.middle_concentric_with_outer:
            return [{
                "kind": "middle",
                "name_key": "hud_target_middle",
                "source_key": "source_middle_edge",
                "xy": self.middle_xy,
                "score": self._target_scores.get("middle", self.last_score),
            }]
        fallback = self._fallback_target()
        if fallback == "inner":
            return [{
                "kind": "inner",
                "name_key": "hud_target_inner",
                "source_key": "source_inner_edge",
                "xy": self.inner_xy,
                "score": self._target_scores.get("inner", self.last_score),
            }]
        if fallback == "secondary":
            return [{
                "kind": "secondary",
                "name_key": "hud_target_secondary",
                "source_key": "source_secondary_edge",
                "xy": self.secondary_xy,
                "score": self._target_scores.get("secondary", self.last_score),
            }]
        return [{
            "kind": "middle",
            "name_key": "hud_target_middle",
            "source_key": "source_middle_concentric",
            "xy": (int(self.config.center_x), int(self.config.center_y)),
            "score": self._target_scores.get("middle", self.last_score),
        }]

    def _primary_hud_xy(self) -> Optional[Tuple[int, int]]:
        """返回右侧状态栏和历史数据使用的主目标

        若中圈和内圈同时持续吸附，选择偏移距离更大的那个作为主目标，
        这样右侧简要状态优先提醒最需要调整的圆HUD 左上角仍会同时显示两组
        """
        targets = self._hud_targets()
        if not targets:
            return self._active_xy()
        if len(targets) == 1:
            return targets[0]["xy"]
        worst = max(targets, key=lambda item: VisionEngine.measure(self.config, item["xy"])["dist"])
        return worst["xy"]

    # ------------------------------------------------------------------
    # UI 构建
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # 左侧视频画面鼠标拖动会更新“参考中心/零点”
        # 放大后，右侧和下方各有一个平移滑条，用来移动当前裁剪视野
        video_area = QWidget()
        video_grid = QGridLayout(video_area)
        video_grid.setContentsMargins(0, 0, 0, 0)
        video_grid.setSpacing(4)

        self.video_label = InteractiveVideoLabel()
        self.video_label.center_changed.connect(self._set_center_from_mouse)
        self.video_label.zoom_wheel_delta.connect(self._on_video_wheel_zoom)
        video_grid.addWidget(self.video_label, 0, 0)

        self.view_pan_y_slider = QSlider(Qt.Orientation.Vertical)
        self.view_pan_y_slider.setRange(-1500, 1500)
        self.view_pan_y_slider.setValue(int(self.config.view_pan_y))
        self.view_pan_y_slider.setFixedWidth(22)
        # 让滑块向下拖动时数值增大，对应“查看画面下方”
        self.view_pan_y_slider.setInvertedAppearance(True)
        self.view_pan_y_slider.valueChanged.connect(self._on_view_pan_y)
        video_grid.addWidget(self.view_pan_y_slider, 0, 1)

        self.view_pan_x_slider = QSlider(Qt.Orientation.Horizontal)
        self.view_pan_x_slider.setRange(-1500, 1500)
        self.view_pan_x_slider.setValue(int(self.config.view_pan_x))
        self.view_pan_x_slider.setFixedHeight(22)
        self.view_pan_x_slider.valueChanged.connect(self._on_view_pan_x)
        video_grid.addWidget(self.view_pan_x_slider, 1, 0)

        corner = QWidget()
        corner.setFixedSize(22, 22)
        video_grid.addWidget(corner, 1, 1)
        main_layout.addWidget(video_area, stretch=1)

        # 右侧控制面板内容较多，所以使用滚动区
        # 关键交互规则：鼠标滚轮在右侧参数栏内只负责上下滚动页面，
        # 不允许误改 QSpinBox、QDoubleSpinBox、QComboBox 或 QSlider 的数值
        self.control_scroll = QScrollArea()
        self.control_scroll.setWidgetResizable(True)
        self.control_scroll.setFixedWidth(380)
        self.control_panel = QWidget()
        self.panel_layout = QVBoxLayout(self.control_panel)
        self.panel_layout.setContentsMargins(8, 8, 8, 8)
        self.control_scroll.setWidget(self.control_panel)
        main_layout.addWidget(self.control_scroll)

        self._build_control_group()
        self._build_camera_group()
        self._build_overlay_group()
        self._build_status_group()
        self.panel_layout.addStretch()

        # 自动识别参数不再放在右侧长滚动栏里，而是放在左侧画面下方右下角
        # 光轴调节时用户眼睛主要盯着画面，边看边微调 ROI/阈值/边缘带宽会更顺手
        self._build_vision_group()
        # 自动识别参数只作为微调工具显示在画面右下角
        # 控制宽度，避免挤占左侧预览画面的垂直空间
        self.vision_group.setMaximumWidth(420)
        video_grid.addWidget(self.vision_group, 2, 0, alignment=Qt.AlignmentFlag.AlignRight)

        # 所有右侧子控件创建完成后统一安装滚轮过滤器，
        # 这样滚轮不会改参数，只会滚动右侧控制页
        self._install_control_panel_wheel_filter()
        self.resize(1380, 820)

    def _build_control_group(self) -> None:
        self.control_group = QGroupBox()
        layout = QVBoxLayout(self.control_group)

        row1 = QHBoxLayout()
        self.btn_start = QPushButton()
        self.btn_stop = QPushButton()
        self.btn_reset = QPushButton()
        self.btn_start.clicked.connect(self.start_camera)
        self.btn_stop.clicked.connect(self.stop_camera)
        self.btn_reset.clicked.connect(self.reset_center)
        row1.addWidget(self.btn_start)
        row1.addWidget(self.btn_stop)
        row1.addWidget(self.btn_reset)
        layout.addLayout(row1)

        self.btn_environment_check = QPushButton()
        self.btn_environment_check.clicked.connect(self.show_environment_check)
        layout.addWidget(self.btn_environment_check)

        self.panel_layout.addWidget(self.control_group)

    def _build_camera_group(self) -> None:
        """构建相机控制区

        这里按相机类型把选项分成几个小区域：
        - 基本设置：所有相机都需要，比如相机类型、设备、分辨率、显示帧率
        - ZWO SDK：只有 ZWO/ASI 相机需要 ASICamera2.dll
        - 采集参数：真实相机使用，模拟相机隐藏
        - USB 对焦：只有普通 UVC/DirectShow 摄像头尝试显示，因为 ZWO/QHY 通常没有这种电子对焦项
        """
        self.camera_group = QGroupBox()
        root = QVBoxLayout(self.camera_group)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ---------------- 基本设置 ----------------
        self.camera_basic_group = QGroupBox()
        basic_form = QFormLayout(self.camera_basic_group)
        basic_form.setContentsMargins(8, 8, 8, 8)
        basic_form.setHorizontalSpacing(12)
        basic_form.setVerticalSpacing(6)

        self.camera_type_combo = QComboBox()
        self.camera_type_combo.addItems(["synthetic", "usb", "zwo", "qhy"])
        self.camera_type_combo.currentTextChanged.connect(self._on_camera_type_changed)

        self.camera_device_combo = QComboBox()
        self.camera_device_combo.setMinimumWidth(170)

        self.res_combo = QComboBox()
        for item in ["640x480", "1280x720", "1920x1080", "3264x2448"]:
            self.res_combo.addItem(item)

        self.ui_fps_spin = QSpinBox()
        self.ui_fps_spin.setRange(1, 60)
        self.ui_fps_spin.setSuffix(" FPS")
        self.ui_fps_spin.setValue(int(self.config.ui_fps_limit))
        self.ui_fps_spin.valueChanged.connect(self._on_ui_fps_changed)

        basic_form.addRow(QLabel(), self.camera_type_combo)
        basic_form.addRow(QLabel(), self.camera_device_combo)
        basic_form.addRow(QLabel(), self.res_combo)
        basic_form.addRow(QLabel(), self.ui_fps_spin)
        self.camera_type_label = basic_form.labelForField(self.camera_type_combo)
        self.camera_id_label = basic_form.labelForField(self.camera_device_combo)
        self.res_label = basic_form.labelForField(self.res_combo)
        self.ui_fps_label = basic_form.labelForField(self.ui_fps_spin)
        root.addWidget(self.camera_basic_group)

        # ---------------- ZWO 专属 SDK 路径 ----------------
        self.camera_zwo_group = QGroupBox()
        zwo_form = QFormLayout(self.camera_zwo_group)
        zwo_form.setContentsMargins(8, 8, 8, 8)
        zwo_form.setHorizontalSpacing(12)
        zwo_form.setVerticalSpacing(6)
        self.zwo_dll_edit = QLineEdit()
        self.zwo_dll_edit.setMinimumWidth(170)
        self.zwo_dll_edit.setPlaceholderText("Auto / ASICamera2.dll")
        self.btn_browse_zwo_dll = QPushButton("...")
        self.btn_browse_zwo_dll.setFixedWidth(34)
        self.btn_browse_zwo_dll.clicked.connect(self.browse_zwo_dll)
        self.zwo_dll_row = QWidget()
        dll_layout = QHBoxLayout(self.zwo_dll_row)
        dll_layout.setContentsMargins(0, 0, 0, 0)
        dll_layout.setSpacing(4)
        dll_layout.addWidget(self.zwo_dll_edit)
        dll_layout.addWidget(self.btn_browse_zwo_dll)
        zwo_form.addRow(QLabel(), self.zwo_dll_row)
        self.zwo_dll_label = zwo_form.labelForField(self.zwo_dll_row)
        root.addWidget(self.camera_zwo_group)

        # ---------------- 真实相机采集参数 ----------------
        self.camera_param_group = QGroupBox()
        param_form = QFormLayout(self.camera_param_group)
        param_form.setContentsMargins(8, 8, 8, 8)
        param_form.setHorizontalSpacing(12)
        param_form.setVerticalSpacing(6)

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.01, 60000.0)
        self.exposure_spin.setDecimals(2)
        self.exposure_spin.setSingleStep(1.0)
        self.exposure_spin.setSuffix(" ms")
        self.exposure_spin.setValue(float(self.config.camera_exposure_ms))
        self.exposure_spin.valueChanged.connect(lambda _v: self._on_camera_param_input_changed())

        self.iso_spin = QSpinBox()
        self.iso_spin.setRange(0, 6400)
        self.iso_spin.setSingleStep(10)
        self.iso_spin.setValue(int(self.config.camera_iso))
        self.iso_spin.valueChanged.connect(lambda _v: self._on_camera_param_input_changed())

        self.gain_spin = QSpinBox()
        self.gain_spin.setRange(0, 1000)
        self.gain_spin.setValue(int(self.config.camera_gain))
        self.gain_spin.valueChanged.connect(lambda _v: self._on_camera_param_input_changed())

        self.auto_exposure_check = QCheckBox()
        self.auto_exposure_check.setChecked(bool(self.config.camera_auto_exposure))
        self.auto_exposure_check.stateChanged.connect(lambda _state: self._on_camera_param_input_changed())

        param_form.addRow(QLabel(), self.exposure_spin)
        param_form.addRow(QLabel(), self.iso_spin)
        param_form.addRow(QLabel(), self.gain_spin)
        param_form.addRow(QLabel(), self.auto_exposure_check)
        self.exposure_label = param_form.labelForField(self.exposure_spin)
        self.iso_label = param_form.labelForField(self.iso_spin)
        self.gain_label = param_form.labelForField(self.gain_spin)
        self.auto_exposure_label = param_form.labelForField(self.auto_exposure_check)
        root.addWidget(self.camera_param_group)

        # ---------------- USB 专属电子对焦 ----------------
        self.usb_focus_group = QGroupBox()
        focus_form = QFormLayout(self.usb_focus_group)
        focus_form.setContentsMargins(8, 8, 8, 8)
        focus_form.setHorizontalSpacing(12)
        focus_form.setVerticalSpacing(6)
        self.auto_focus_check = QCheckBox()
        self.auto_focus_check.setChecked(bool(self.config.camera_auto_focus))
        self.auto_focus_check.stateChanged.connect(lambda _state: self._on_camera_focus_changed())
        self.focus_spin = QSpinBox()
        self.focus_spin.setRange(0, 1023)
        self.focus_spin.setSingleStep(1)
        self.focus_spin.setValue(int(self.config.camera_focus))
        self.focus_spin.valueChanged.connect(lambda _v: self._on_camera_focus_changed())
        focus_form.addRow(QLabel(), self.auto_focus_check)
        focus_form.addRow(QLabel(), self.focus_spin)
        self.auto_focus_label = focus_form.labelForField(self.auto_focus_check)
        self.focus_label = focus_form.labelForField(self.focus_spin)
        root.addWidget(self.usb_focus_group)

        # ---------------- 操作按钮 ----------------
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.btn_refresh_cameras = QPushButton()
        self.btn_refresh_cameras.clicked.connect(self.refresh_camera_devices)
        self.btn_apply_camera = QPushButton()
        self.btn_apply_camera.clicked.connect(self.apply_camera_settings)
        self.btn_apply_params = QPushButton()
        self.btn_apply_params.clicked.connect(self.apply_camera_params)
        btn_row.addWidget(self.btn_refresh_cameras)
        btn_row.addWidget(self.btn_apply_camera)
        btn_row.addWidget(self.btn_apply_params)
        root.addLayout(btn_row)

        self.panel_layout.addWidget(self.camera_group)
        self._update_camera_brand_visibility()
    def _build_overlay_group(self) -> None:
        self.overlay_group = QGroupBox()
        layout = QVBoxLayout(self.overlay_group)

        # 画面放大100% 为不放大，200% 为围绕参考中心做 2 倍放大
        self.zoom_group = QGroupBox()
        zoom_form = QFormLayout(self.zoom_group)
        self.zoom_slider, self.zoom_value = self._make_slider(100, 400, self.config.zoom_percent, self._on_zoom)
        zoom_form.addRow(QLabel(), self._slider_row(self.zoom_slider, self.zoom_value))
        self.zoom_label = zoom_form.labelForField(self.zoom_slider.parent())
        layout.addWidget(self.zoom_group)

        # 三个圆的控制组：每个圆的颜色/半径/线宽仍在自己的框内
        # 外圈框额外放参考中心位置调节、吸附外圈边缘、设为圆心
        # 中圈/内圈框额外放各自检测圆心位置调节和吸附按钮
        self.circle_widgets = []
        self.circle1_group = self._make_circle_group(self.config.circle1, 10, 1600)
        self.circle2_group = self._make_circle_group(self.config.circle2, 5, 1000)
        self.circle3_group = self._make_circle_group(self.config.circle3, 1, 500)
        self.circle4_group = self._make_circle_group(self.config.circle4, 1, 700)

        # 外圈：参考中心位置调节 + 外圈边缘拟合
        outer_form: QFormLayout = self.circle1_group.layout()  # type: ignore[assignment]
        self.h_offset_slider, self.h_offset_value = self._make_outer_editable_slider(-1500, 1500, self.config.horizontal_offset, self._on_h_offset)
        self.v_offset_slider, self.v_offset_value = self._make_outer_editable_slider(-1500, 1500, self.config.vertical_offset, self._on_v_offset)
        outer_form.addRow(QLabel(), self._slider_row(self.h_offset_slider, self.h_offset_value))
        outer_form.addRow(QLabel(), self._slider_row(self.v_offset_slider, self.v_offset_value))
        self.h_offset_label = outer_form.labelForField(self.h_offset_slider.parent())
        self.v_offset_label = outer_form.labelForField(self.v_offset_slider.parent())
        outer_btn_row = QWidget()
        outer_btn_layout = QHBoxLayout(outer_btn_row)
        outer_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_snap_edge = QPushButton()
        self.btn_snap_edge.clicked.connect(self.snap_outer_edge)
        self.btn_set_reference = QPushButton()
        self.btn_set_reference.clicked.connect(self.set_outer_as_reference)
        outer_btn_layout.addWidget(self.btn_snap_edge)
        outer_btn_layout.addWidget(self.btn_set_reference)
        outer_form.addRow(outer_btn_row)

        # 中圈：做法与内圈一致，用于吸附圆形亮斑边缘，也可切换为与外圈同心辅助显示
        middle_form: QFormLayout = self.circle2_group.layout()  # type: ignore[assignment]
        self.middle_x_slider, self.middle_x_value = self._make_editable_slider(-1500, 1500, self.config.circle2_center_x - self.config.center_x, self._on_middle_x)
        self.middle_y_slider, self.middle_y_value = self._make_editable_slider(-1500, 1500, self.config.circle2_center_y - self.config.center_y, self._on_middle_y)
        middle_form.addRow(QLabel(), self._slider_row(self.middle_x_slider, self.middle_x_value))
        middle_form.addRow(QLabel(), self._slider_row(self.middle_y_slider, self.middle_y_value))
        self.middle_x_label = middle_form.labelForField(self.middle_x_slider.parent())
        self.middle_y_label = middle_form.labelForField(self.middle_y_slider.parent())
        middle_edge_row = QWidget()
        middle_edge_layout = QHBoxLayout(middle_edge_row)
        middle_edge_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_snap_middle_edge = QPushButton()
        self.btn_snap_middle_edge.clicked.connect(self.snap_middle_edge)
        self.middle_track_check = QCheckBox()
        self.middle_track_check.setChecked(bool(self.config.track_middle))
        self.middle_track_check.stateChanged.connect(lambda _: self._on_track_middle())
        self.middle_concentric_check = QCheckBox()
        self.middle_concentric_check.setChecked(bool(self.config.middle_concentric_with_outer))
        self.middle_concentric_check.stateChanged.connect(lambda _: self._on_middle_concentric_mode())
        middle_edge_layout.addWidget(self.btn_snap_middle_edge)
        middle_edge_layout.addWidget(self.middle_track_check)
        middle_edge_layout.addWidget(self.middle_concentric_check)
        middle_form.addRow(middle_edge_row)

        # 内圈：红色小圆边缘位置调节 + 边缘吸附 + 持续吸附
        inner_form: QFormLayout = self.circle3_group.layout()  # type: ignore[assignment]
        self.inner_x_slider, self.inner_x_value = self._make_editable_slider(-1500, 1500, self.config.circle3_center_x - self.config.center_x, self._on_inner_x)
        self.inner_y_slider, self.inner_y_value = self._make_editable_slider(-1500, 1500, self.config.circle3_center_y - self.config.center_y, self._on_inner_y)
        inner_form.addRow(QLabel(), self._slider_row(self.inner_x_slider, self.inner_x_value))
        inner_form.addRow(QLabel(), self._slider_row(self.inner_y_slider, self.inner_y_value))
        self.inner_x_label = inner_form.labelForField(self.inner_x_slider.parent())
        self.inner_y_label = inner_form.labelForField(self.inner_y_slider.parent())
        inner_edge_row = QWidget()
        inner_edge_layout = QHBoxLayout(inner_edge_row)
        inner_edge_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_snap_inner_edge = QPushButton()
        self.btn_snap_inner_edge.clicked.connect(self.snap_inner_edge)
        self.inner_track_check = QCheckBox()
        self.inner_track_check.setChecked(bool(self.config.track_inner))
        self.inner_track_check.stateChanged.connect(lambda _: self._on_track_inner())
        self.inner_concentric_check = QCheckBox()
        self.inner_concentric_check.setChecked(bool(self.config.inner_concentric_with_outer))
        self.inner_concentric_check.stateChanged.connect(lambda _: self._on_inner_concentric_mode())
        inner_edge_layout.addWidget(self.btn_snap_inner_edge)
        inner_edge_layout.addWidget(self.inner_track_check)
        inner_edge_layout.addWidget(self.inner_concentric_check)
        inner_form.addRow(inner_edge_row)

        # 副镜圈：做法与内圈一致，用于独立吸附副镜边缘，并把副镜圆心调到外圈参考中心
        secondary_form: QFormLayout = self.circle4_group.layout()  # type: ignore[assignment]
        self.secondary_x_slider, self.secondary_x_value = self._make_editable_slider(-1500, 1500, self.config.circle4_center_x - self.config.center_x, self._on_secondary_x)
        self.secondary_y_slider, self.secondary_y_value = self._make_editable_slider(-1500, 1500, self.config.circle4_center_y - self.config.center_y, self._on_secondary_y)
        secondary_form.addRow(QLabel(), self._slider_row(self.secondary_x_slider, self.secondary_x_value))
        secondary_form.addRow(QLabel(), self._slider_row(self.secondary_y_slider, self.secondary_y_value))
        self.secondary_x_label = secondary_form.labelForField(self.secondary_x_slider.parent())
        self.secondary_y_label = secondary_form.labelForField(self.secondary_y_slider.parent())
        secondary_edge_row = QWidget()
        secondary_edge_layout = QHBoxLayout(secondary_edge_row)
        secondary_edge_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_snap_secondary_edge = QPushButton()
        self.btn_snap_secondary_edge.clicked.connect(self.snap_secondary_edge)
        self.secondary_track_check = QCheckBox()
        self.secondary_track_check.setChecked(bool(self.config.track_secondary))
        self.secondary_track_check.stateChanged.connect(lambda _: self._on_track_secondary())
        self.secondary_concentric_check = QCheckBox()
        self.secondary_concentric_check.setChecked(bool(self.config.secondary_concentric_with_outer))
        self.secondary_concentric_check.stateChanged.connect(lambda _: self._on_secondary_concentric_mode())
        secondary_edge_layout.addWidget(self.btn_snap_secondary_edge)
        secondary_edge_layout.addWidget(self.secondary_track_check)
        secondary_edge_layout.addWidget(self.secondary_concentric_check)
        secondary_form.addRow(secondary_edge_row)

        layout.addWidget(self.circle1_group)
        layout.addWidget(self.circle2_group)
        layout.addWidget(self.circle3_group)
        layout.addWidget(self.circle4_group)

        # 中心星标也提供颜色选择，因为传统 OCAL 中星标颜色可调
        self.star_group = QGroupBox()
        star_form = QFormLayout(self.star_group)
        self.star_enable = QCheckBox()
        self.star_enable.stateChanged.connect(lambda _: self._update_star())
        self.star_len_slider, self.star_len_value = self._make_slider(5, 6000, self.config.star.length, lambda v: self._update_star(length=v))
        self.star_thick_spin = QDoubleSpinBox()
        self.star_thick_spin.setRange(0.5, 5.0)
        self.star_thick_spin.setDecimals(1)
        self.star_thick_spin.setSingleStep(0.2)
        self.star_thick_spin.setKeyboardTracking(False)
        self.star_thick_spin.valueChanged.connect(lambda v: self._update_star(thickness=float(v)))
        self.star_angle_slider, self.star_angle_value = self._make_slider(0, 359, self.config.star.angle, lambda v: self._update_star(angle=v))
        self.star_color_button = self._make_color_button(self.config.star.color, lambda color: self._update_star(color=color))
        star_form.addRow(QLabel(), self.star_enable)
        star_form.addRow(QLabel(), self._slider_row(self.star_len_slider, self.star_len_value))
        star_form.addRow(QLabel(), self.star_thick_spin)
        star_form.addRow(QLabel(), self._slider_row(self.star_angle_slider, self.star_angle_value))
        star_form.addRow(QLabel(), self.star_color_button)
        self.star_enable_label = star_form.labelForField(self.star_enable)
        self.star_length_label = star_form.labelForField(self.star_len_slider.parent())
        self.star_thick_label = star_form.labelForField(self.star_thick_spin)
        self.star_angle_label = star_form.labelForField(self.star_angle_slider.parent())
        self.star_color_label = star_form.labelForField(self.star_color_button)
        layout.addWidget(self.star_group)

        self.panel_layout.addWidget(self.overlay_group)

    def _build_vision_group(self) -> None:
        """构建紧凑的自动识别参数面板

        这个面板位于画面右下角，只用于边看画面边微调识别参数
        因为它会直接占用视频预览区下方空间，所以这里采用单列表格：
        参数名 + 短滑条 + 数值，去掉大段分组标题，说明文字压缩成两行
        """
        self.vision_group = QGroupBox()
        self.vision_group.setMinimumWidth(360)
        self.vision_group.setMaximumWidth(420)
        layout = QGridLayout(self.vision_group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(3)
        layout.setColumnStretch(1, 1)

        self.roi_slider, self.roi_value = self._make_slider(10, 500, self.config.snap_roi, self._on_roi)
        self.threshold_slider, self.threshold_value = self._make_slider(0, 255, self.config.snap_threshold, self._on_threshold)
        self.band_slider, self.band_value = self._make_slider(5, 180, self.config.edge_band_width, self._on_band)
        self.secondary_band_slider, self.secondary_band_value = self._make_slider(8, 260, self.config.secondary_edge_band_width, self._on_secondary_band)
        self.secondary_sensitivity_slider, self.secondary_sensitivity_value = self._make_slider(0, 100, self.config.secondary_edge_sensitivity, self._on_secondary_sensitivity)

        # 缩短数值列宽度，并限制滑条高度，让整个面板更紧凑
        for slider, value_label in [
            (self.roi_slider, self.roi_value),
            (self.threshold_slider, self.threshold_value),
            (self.band_slider, self.band_value),
            (self.secondary_band_slider, self.secondary_band_value),
            (self.secondary_sensitivity_slider, self.secondary_sensitivity_value),
        ]:
            slider.setFixedHeight(18)
            value_label.setFixedWidth(34)
            value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value_label.setStyleSheet("font-size: 11px;")

        def make_label() -> QLabel:
            label = QLabel()
            label.setFixedWidth(98)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            label.setStyleSheet("font-size: 11px;")
            return label

        def make_slider_cell(slider: QSlider, value_label: QLabel) -> QWidget:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            row_layout.addWidget(slider, stretch=1)
            row_layout.addWidget(value_label)
            return row

        self.roi_label = make_label()
        self.threshold_label = make_label()
        self.band_label = make_label()
        self.secondary_band_label = make_label()
        self.secondary_sensitivity_label = make_label()

        rows = [
            (self.roi_label, self.roi_slider, self.roi_value),
            (self.threshold_label, self.threshold_slider, self.threshold_value),
            (self.band_label, self.band_slider, self.band_value),
            (self.secondary_band_label, self.secondary_band_slider, self.secondary_band_value),
            (self.secondary_sensitivity_label, self.secondary_sensitivity_slider, self.secondary_sensitivity_value),
        ]
        for row_index, (label, slider, value_label) in enumerate(rows):
            layout.addWidget(label, row_index, 0)
            layout.addWidget(make_slider_cell(slider, value_label), row_index, 1)

        self.vision_help_label = QLabel()
        self.vision_help_label.setWordWrap(True)
        self.vision_help_label.setTextFormat(Qt.TextFormat.PlainText)
        self.vision_help_label.setMaximumHeight(34)
        self.vision_help_label.setStyleSheet(
            "color: #555; font-size: 10px; "
            "background: rgba(255,255,255,0.35); border: 1px solid #d6d6d6; "
            "border-radius: 3px; padding: 3px;"
        )
        layout.addWidget(self.vision_help_label, len(rows), 0, 1, 2)

    def _build_status_group(self) -> None:
        self.status_group = QGroupBox()
        layout = QVBoxLayout(self.status_group)
        self.status_score = QLabel()
        self.status_dev = QLabel()
        self.status_offset = QLabel()
        self.status_guide = QLabel()
        self.status_reference = QLabel()
        self.status_text = QLabel()
        for label in [self.status_score, self.status_dev, self.status_offset, self.status_guide, self.status_reference, self.status_text]:
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["zh", "en"])
        self.lang_combo.currentTextChanged.connect(self.change_language)
        layout.addWidget(self.lang_combo)

        self.btn_save = QPushButton()
        self.btn_load = QPushButton()
        self.btn_save.clicked.connect(self.save_parameters)
        self.btn_load.clicked.connect(self.load_parameters)
        layout.addWidget(self.btn_save)
        layout.addWidget(self.btn_load)
        self.panel_layout.addWidget(self.status_group)

    # ------------------------------------------------------------------
    # 右侧参数栏滚轮处理
    # ------------------------------------------------------------------
    def _install_control_panel_wheel_filter(self) -> None:
        """让右侧参数栏的鼠标滚轮只滚动页面，不修改控件数值

        PyQt 的 SpinBox、ComboBox 和 Slider 默认会响应鼠标滚轮
        光轴调节时鼠标经常停在右侧参数框上滚动页面，默认行为会导致曝光、增益、
        半径、颜色选项等参数被误改这里对右侧面板全部子控件安装 eventFilter，
        遇到滚轮事件时统一转发给 QScrollArea 的竖向滚动条
        左侧视频画面不受影响，鼠标滚轮仍然用于缩放画面
        """
        if not hasattr(self, "control_panel"):
            return
        self.control_panel.installEventFilter(self)
        for child in self.control_panel.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 - Qt 固定函数名
        """拦截右侧参数栏滚轮事件，避免滚轮修改输入框/下拉框/滑条"""
        if event.type() == QEvent.Type.Wheel and hasattr(self, "control_panel"):
            try:
                in_control_panel = obj is self.control_panel or self.control_panel.isAncestorOf(obj)
            except RuntimeError:
                in_control_panel = False

            if in_control_panel:
                # 用滚轮的角度增量驱动右侧滚动条angleDelta().y() > 0 表示向上滚
                delta_y = event.angleDelta().y()
                if delta_y:
                    bar = self.control_scroll.verticalScrollBar()
                    bar.setValue(bar.value() - delta_y)
                event.accept()
                return True

        return super().eventFilter(obj, event)

    # ------------------------------------------------------------------
    # 可复用控件
    # ------------------------------------------------------------------
    def _make_slider(self, minimum: int, maximum: int, value: int, callback: Callable[[int], None]) -> Tuple[QSlider, QLabel]:
        slider = DampedSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(int(value))
        value_label = QLabel(str(int(value)))
        value_label.setFixedWidth(52)
        slider.valueChanged.connect(lambda v: (value_label.setText(str(v)), callback(v)))
        return slider, value_label

    def _make_editable_slider(
        self,
        minimum: int,
        maximum: int,
        value: int,
        callback: Callable[[int], None],
    ) -> Tuple[QSlider, QSpinBox]:
        """创建“整数滑条 + 整数输入框”的双向位置控制。"""
        slider = DampedSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(int(value))

        value_input = QSpinBox()
        value_input.setRange(minimum, maximum)
        value_input.setValue(int(value))
        value_input.setSingleStep(1)
        value_input.setKeyboardTracking(False)
        value_input.setFixedWidth(72)
        value_input.setAlignment(Qt.AlignmentFlag.AlignRight)

        def on_slider_changed(new_value: int) -> None:
            if value_input.value() != int(new_value):
                value_input.setValue(int(new_value))
            callback(int(new_value))

        slider.valueChanged.connect(on_slider_changed)
        value_input.valueChanged.connect(lambda new_value: slider.setValue(int(new_value)))
        return slider, value_input

    def _make_outer_editable_slider(
        self,
        minimum: int,
        maximum: int,
        value: float,
        callback: Callable[[float], None],
    ) -> Tuple[QSlider, QDoubleSpinBox]:
        """创建外圈专用位置控制。

        滑条本身仍按整数像素移动；右侧输入框允许输入两位小数。
        手动输入小数时，滑条只移动到最接近的整数刻度，但业务参数保留原始小数；
        用户再次拖动滑条后，参数和输入框都会恢复为对应的整数值。
        """
        slider = DampedSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(int(round(float(value))))

        value_input = QDoubleSpinBox()
        value_input.setRange(float(minimum), float(maximum))
        value_input.setDecimals(2)
        value_input.setSingleStep(0.1)
        value_input.setValue(float(value))
        value_input.setKeyboardTracking(False)
        # 外圈输入框需容纳负数、两位小数和右侧步进按钮。
        # 96 px 可避免数字被按钮遮挡，同时尽量把横向空间留给位置滑条。
        # 其他圆圈的整数输入框尺寸保持原样。
        value_input.setFixedWidth(96)
        value_input.setAlignment(Qt.AlignmentFlag.AlignRight)

        def on_slider_changed(new_value: int) -> None:
            previous = value_input.blockSignals(True)
            value_input.setValue(float(new_value))
            value_input.blockSignals(previous)
            callback(float(new_value))

        def on_input_changed(new_value: float) -> None:
            slider_value = int(round(float(new_value)))
            slider_value = max(slider.minimum(), min(slider.maximum(), slider_value))
            previous = slider.blockSignals(True)
            slider.setValue(slider_value)
            slider.blockSignals(previous)
            callback(float(new_value))

        slider.valueChanged.connect(on_slider_changed)
        value_input.valueChanged.connect(on_input_changed)
        return slider, value_input

    def _slider_row(self, slider: QSlider, value_label: QWidget) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(slider)
        layout.addWidget(value_label)
        return row

    def _make_color_button(self, initial_color: Tuple[int, int, int], callback: Callable[[Tuple[int, int, int]], None]) -> QPushButton:
        """创建短小的颜色块按钮

        旧版本使用带英文颜色名的下拉框，不够直观
        现在每个圈只显示一个纯色块，点击色块后打开系统颜色选择器
        """
        button = QPushButton()
        button.setText("")
        button.setFixedSize(46, 24)
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        def apply_color(color: Tuple[int, int, int]) -> None:
            button._bgr_color = color  # type: ignore[attr-defined]
            button.setStyleSheet(self._color_button_style(color))
            button.setToolTip(f"BGR: {color[0]}, {color[1]}, {color[2]}")

        def choose_color() -> None:
            current = getattr(button, "_bgr_color", initial_color)
            chosen = QColorDialog.getColor(bgr_to_qcolor(current), self, self.i18n.t("custom_color"))
            if not chosen.isValid():
                return
            color = qcolor_to_bgr(chosen)
            apply_color(color)
            callback(color)

        button._set_bgr_color = apply_color  # type: ignore[attr-defined]
        apply_color(initial_color)
        button.clicked.connect(choose_color)
        return button

    def _color_button_style(self, color: Tuple[int, int, int]) -> str:
        """颜色块按钮样式只显示色块，不显示颜色名称"""
        q = bgr_to_qcolor(color)
        return (
            "QPushButton {"
            f"background-color: rgb({q.red()}, {q.green()}, {q.blue()});"
            "border: 1px solid #9a9a9a;"
            "border-radius: 3px;"
            "}"
            "QPushButton:hover { border: 2px solid #ffffff; }"
        )

    def _make_circle_group(self, circle: CircleConfig, min_radius: int, max_radius: int) -> QGroupBox:
        group = QGroupBox()
        form = QFormLayout(group)
        enabled = QCheckBox()
        radius_slider, radius_value = self._make_slider(min_radius, max_radius, circle.radius, lambda v, c=circle: self._update_circle(c, radius=v))
        thickness = QDoubleSpinBox()
        thickness.setRange(0.5, 5.0)
        thickness.setDecimals(1)
        thickness.setSingleStep(0.2)
        thickness.setKeyboardTracking(False)
        thickness.setValue(float(circle.thickness))
        color_button = self._make_color_button(circle.color, lambda color, c=circle: self._update_circle(c, color=color))

        enabled.stateChanged.connect(lambda _, c=circle, cb=enabled: self._update_circle(c, enabled=cb.isChecked()))
        thickness.valueChanged.connect(lambda v, c=circle: self._update_circle(c, thickness=float(v)))

        form.addRow(QLabel(), enabled)
        form.addRow(QLabel(), self._slider_row(radius_slider, radius_value))
        form.addRow(QLabel(), thickness)
        form.addRow(QLabel(), color_button)
        self.circle_widgets.append({
            "group": group,
            "circle": circle,
            "enabled": enabled,
            "radius_slider": radius_slider,
            "radius_value": radius_value,
            "thickness": thickness,
            "color_button": color_button,
            "enabled_label": form.labelForField(enabled),
            "radius_label": form.labelForField(radius_slider.parent()),
            "thick_label": form.labelForField(thickness),
            "color_label": form.labelForField(color_button),
        })
        return group

    # ------------------------------------------------------------------
    # 语言刷新
    # ------------------------------------------------------------------
    def _apply_language(self) -> None:
        t = self.i18n.t
        self.setWindowTitle(t("app_title"))
        self.control_group.setTitle(t("control"))
        self.btn_start.setText(t("start"))
        self.btn_stop.setText(t("stop"))
        self.btn_reset.setText(t("reset_center"))
        self.btn_environment_check.setText(t("environment_check"))

        self.camera_group.setTitle(t("camera"))
        self.camera_basic_group.setTitle(t("camera_basic"))
        self.camera_zwo_group.setTitle(t("camera_zwo_sdk"))
        self.camera_param_group.setTitle(t("camera_capture_params"))
        self.usb_focus_group.setTitle(t("usb_focus"))
        self.camera_type_label.setText(t("camera_type"))
        self.camera_id_label.setText(t("camera_device"))
        self.res_label.setText(t("resolution"))
        self.ui_fps_label.setText(t("ui_fps_limit"))
        self.zwo_dll_label.setText(t("zwo_dll"))
        self.exposure_label.setText(t("exposure"))
        self.iso_label.setText(t("iso"))
        self.gain_label.setText(t("gain"))
        self.auto_exposure_label.setText(t("auto_exposure"))
        self.auto_focus_label.setText(t("auto_focus"))
        self.focus_label.setText(t("manual_focus"))
        self.btn_refresh_cameras.setText(t("refresh_cameras"))
        self.btn_apply_camera.setText(t("apply_camera"))
        self.btn_apply_params.setText(t("apply_params"))

        self.overlay_group.setTitle(t("overlay"))
        self.h_offset_label.setText(t("position_x"))
        self.v_offset_label.setText(t("position_y"))
        self._update_outer_pick_button_text()
        self.btn_set_reference.setText(t("set_as_center"))
        self.middle_x_label.setText(t("position_x"))
        self.middle_y_label.setText(t("position_y"))
        self.btn_snap_middle_edge.setText(t("snap_middle_edge"))
        self.middle_track_check.setText(t("continuous_snap"))
        self.middle_concentric_check.setText(t("middle_concentric_mode"))
        self.inner_x_label.setText(t("position_x"))
        self.inner_y_label.setText(t("position_y"))
        self.btn_snap_inner_edge.setText(t("snap_inner_edge"))
        self.inner_track_check.setText(t("continuous_snap"))
        self.inner_concentric_check.setText(t("inner_concentric_mode"))
        self.secondary_x_label.setText(t("position_x"))
        self.secondary_y_label.setText(t("position_y"))
        self.btn_snap_secondary_edge.setText(t("snap_secondary_edge"))
        self.secondary_track_check.setText(t("continuous_snap"))
        self.secondary_concentric_check.setText(t("secondary_concentric_mode"))
        self.zoom_group.setTitle(t("zoom"))
        self.zoom_label.setText(t("zoom"))
        self.view_pan_x_slider.setToolTip(t("view_pan_x"))
        self.view_pan_y_slider.setToolTip(t("view_pan_y"))

        circle_titles = [t("circle1"), t("circle2"), t("circle3"), t("circle4")]
        for i, labels in enumerate(self.circle_widgets):
            labels["group"].setTitle(circle_titles[i])
            labels["enabled_label"].setText(t("enabled"))
            labels["radius_label"].setText(t("radius"))
            labels["thick_label"].setText(t("thickness"))
            labels["color_label"].setText(t("color"))

        self.star_group.setTitle(t("star"))
        self.star_enable_label.setText(t("enabled"))
        self.star_length_label.setText(t("length"))
        self.star_thick_label.setText(t("thickness"))
        self.star_angle_label.setText(t("angle"))
        self.star_color_label.setText(t("color"))

        self.vision_group.setTitle(t("vision"))
        self.roi_label.setText(t("vision_roi_compact"))
        self.threshold_label.setText(t("vision_threshold_compact"))
        self.band_label.setText(t("vision_band_compact"))
        self.secondary_band_label.setText(t("vision_secondary_band_compact"))
        self.secondary_sensitivity_label.setText(t("vision_secondary_sensitivity_compact"))
        self.vision_help_label.setText(t("vision_help_compact"))
        self.vision_help_label.setToolTip(t("vision_help"))

        self.status_group.setTitle(t("status"))
        self.btn_save.setText(t("save"))
        self.btn_load.setText(t("load"))
        self._update_camera_brand_visibility()
        self._update_status_labels()

    # ------------------------------------------------------------------
    # 环境检测
    # ------------------------------------------------------------------
    def _environment_config_snapshot(self) -> AppConfig:
        """生成用于检测的配置快照，包含尚未点击“应用相机”的当前 UI 选择。"""
        snapshot = copy.deepcopy(self.config)
        if hasattr(self, "camera_type_combo"):
            snapshot.camera_type = self.camera_type_combo.currentText().strip().lower()
        if hasattr(self, "camera_device_combo"):
            snapshot.camera_id = self._current_camera_id()
        if hasattr(self, "zwo_dll_edit"):
            snapshot.zwo_dll_path = self.zwo_dll_edit.text().strip()
        return snapshot

    def _collect_environment_report(self, probe_hardware: bool = True) -> EnvironmentReport:
        """运行环境检测并返回结构化报告。"""
        snapshot = self._environment_config_snapshot()
        camera_running = bool(self.thread and self.thread.isRunning())
        return run_environment_check(
            snapshot,
            self.config_manager.filepath,
            language=self.config.language,
            probe_hardware=probe_hardware,
            camera_is_running=camera_running,
        )

    def _present_environment_report(self, report: EnvironmentReport) -> None:
        """显示环境检测窗口；重复检测时复用同一个窗口。"""
        if self.environment_dialog is None:
            self.environment_dialog = EnvironmentCheckDialog(report, self)
            self.environment_dialog.rerun_requested.connect(self.show_environment_check)
        else:
            self.environment_dialog.set_report(report)
        self.environment_dialog.show()
        self.environment_dialog.raise_()
        self.environment_dialog.activateWindow()

    def _show_startup_environment_issues(self) -> None:
        """启动自检仅在存在阻断错误时自动显示。"""
        report = self._startup_environment_report
        if report is not None and report.has_errors:
            self._present_environment_report(report)

    def show_environment_check(self) -> None:
        """由用户主动运行环境检测，并显示可复制的完整报告。"""
        report = self._collect_environment_report(probe_hardware=True)
        self._present_environment_report(report)

    # ------------------------------------------------------------------
    # 相机控制
    # ------------------------------------------------------------------
    def _on_ui_fps_changed(self, fps: int) -> None:
        """在线调整 UI 显示帧率

        这是可选性能项：只限制发送到界面的画面数量，不影响相机曝光、增益或真实采集
        长曝光时建议调到 5-15 FPS；普通 USB 摄像头可以调到 20-30 FPS
        """
        self.config.ui_fps_limit = int(fps)
        if self.thread and self.thread.isRunning():
            self.thread.set_fps_limit(int(fps))

    def _on_camera_param_input_changed(self) -> None:
        """曝光/增益/自动曝光输入后实时更新相机

        用户反馈每次输入相机参数后还要点击“应用参数”太麻烦
        这里先同步配置，再通过 QTimer 防抖写入采集线程真实写入发生在 VideoThread 内部，
        可以避免 UI 线程直接调用 ZWO SDK 造成卡顿
        """
        if self._updating_ui:
            return
        self.config.camera_exposure_ms = float(self.exposure_spin.value())
        self.config.camera_iso = int(self.iso_spin.value())
        self.config.camera_gain = int(self.gain_spin.value())
        self.config.camera_auto_exposure = self.auto_exposure_check.isChecked()
        if hasattr(self, "auto_focus_check"):
            self.config.camera_auto_focus = self.auto_focus_check.isChecked()
        if hasattr(self, "focus_spin"):
            self.config.camera_focus = int(self.focus_spin.value())
        # 只有相机线程运行时才需要在线写入；没启动时保存到 config，启动时会自动使用
        if self.thread and self.thread.isRunning():
            self._camera_param_timer.start()

    def _on_camera_focus_changed(self) -> None:
        """USB 对焦参数变化后实时写入

        仅 USB/UVC 相机可能支持电子对焦；如果驱动不支持，后端会安全忽略
        """
        if self._updating_ui:
            return
        self.config.camera_auto_focus = self.auto_focus_check.isChecked()
        self.config.camera_focus = int(self.focus_spin.value())
        self.focus_spin.setEnabled(not self.config.camera_auto_focus)
        if self.thread and self.thread.isRunning():
            self._camera_param_timer.start()

    def _apply_camera_params_debounced(self) -> None:
        """防抖结束后，把最新曝光/增益写入后台采集线程"""
        if not (self.thread and self.thread.isRunning()):
            return
        self.thread.request_camera_controls(
            float(self.config.camera_exposure_ms),
            int(self.config.camera_iso),
            int(self.config.camera_gain),
            bool(self.config.camera_auto_exposure),
            bool(self.config.camera_auto_focus),
            int(self.config.camera_focus),
        )

    def _on_camera_type_changed(self, camera_type: str) -> None:
        """相机品牌切换时刷新设备，并同步品牌专属 UI

        用户反馈：选择 synthetic/usb/qhy 时，ZWO SDK DLL 输入框还一直显示，
        容易让人误以为所有相机都需要 ASICamera2.dll
        因此这里让 ZWO SDK DLL 这一项只在 camera_type == "zwo" 时显示
        """
        self._update_camera_brand_visibility()
        self.refresh_camera_devices()

    def _update_camera_brand_visibility(self) -> None:
        """根据相机品牌显示/隐藏品牌专属选项，并调整控件含义"""
        if not hasattr(self, "camera_type_combo"):
            return
        camera_type = self.camera_type_combo.currentText().lower()
        is_zwo = camera_type == "zwo"
        is_usb = camera_type == "usb"
        is_synthetic = camera_type == "synthetic"
        is_real_camera = not is_synthetic

        # synthetic 不需要设备和采集参数；ZWO 才需要 SDK DLL；USB 才显示电子对焦
        self.camera_device_combo.setVisible(not is_synthetic)
        self.camera_id_label.setVisible(not is_synthetic)
        self.camera_param_group.setVisible(is_real_camera)
        self.camera_zwo_group.setVisible(is_zwo)
        self.usb_focus_group.setVisible(is_usb)
        self.btn_apply_params.setEnabled(is_real_camera)

        # 不同相机类型下，同一控件对应的真实含义不同
        if is_zwo:
            self.exposure_label.setText(self.i18n.t("exposure"))
            self.iso_label.setText(self.i18n.t("iso_offset"))
            self.iso_spin.setRange(0, 255)
            self.iso_spin.setSingleStep(1)
            self.iso_spin.setToolTip(self.i18n.t("iso_offset_tip"))
            self.gain_label.setText(self.i18n.t("gain"))
            self.camera_param_group.setToolTip(self.i18n.t("zwo_param_tip"))
        elif is_usb:
            self.exposure_label.setText(self.i18n.t("usb_exposure"))
            self.iso_label.setText(self.i18n.t("usb_brightness"))
            self.iso_spin.setRange(0, 6400)
            self.iso_spin.setSingleStep(10)
            self.iso_spin.setToolTip(self.i18n.t("usb_brightness_tip"))
            self.gain_label.setText(self.i18n.t("gain"))
            self.camera_param_group.setToolTip(self.i18n.t("usb_param_tip"))
            self.focus_spin.setEnabled(not self.auto_focus_check.isChecked())
        elif camera_type == "qhy":
            self.exposure_label.setText(self.i18n.t("exposure"))
            self.iso_label.setText(self.i18n.t("offset_brightness"))
            self.iso_spin.setRange(0, 255)
            self.iso_spin.setSingleStep(1)
            self.iso_spin.setToolTip(self.i18n.t("qhy_param_tip"))
            self.gain_label.setText(self.i18n.t("gain"))
            self.camera_param_group.setToolTip(self.i18n.t("qhy_param_tip"))
        else:
            self.camera_param_group.setToolTip("")

    def _current_camera_id(self) -> int:
        """读取设备下拉框里保存的真实设备编号"""
        data = self.camera_device_combo.currentData()
        if data is None:
            return int(self.config.camera_id)
        try:
            return int(data)
        except (TypeError, ValueError):
            return int(self.config.camera_id)

    def refresh_camera_devices(self) -> None:
        """刷新当前相机类型下识别到的设备列表

        选择 ZWO 时，这里会通过 ASICamera2.dll 枚举 ASI 相机，
        让用户直接选择“0 - ASIxxxx”，不再手填编号
        """
        if not hasattr(self, "camera_device_combo"):
            return
        camera_type = self.camera_type_combo.currentText() if hasattr(self, "camera_type_combo") else self.config.camera_type
        current_id = self._current_camera_id() if self.camera_device_combo.count() else int(self.config.camera_id)
        if camera_type == "zwo":
            # ZWO 枚举时优先使用 UI 中指定的 ASICamera2.dll；为空时自动搜索
            # 注意：这里必须是 ASICamera2.dll，不能选择 ASI662MM-Pro.dll 这种型号/DirectShow DLL
            self.config.zwo_dll_path = self.zwo_dll_edit.text().strip() if hasattr(self, "zwo_dll_edit") else self.config.zwo_dll_path
            devices = ZWOCamera.discover(self.config.zwo_dll_path)
            if devices:
                self.last_status_detail = ""
                # 如果 SDK 是自动搜索成功的，把实际加载到的 ASICamera2.dll 路径写回配置，
                # 下次启动就不需要用户再次手动选择
                if getattr(ZWOCamera, "_sdk_path", ""):
                    self.zwo_dll_edit.setText(ZWOCamera._sdk_path)
                    self.config.zwo_dll_path = ZWOCamera._sdk_path
                    self.config_manager.save(self.config)
            else:
                self.last_status_key = "camera_open_fail"
                self.last_status_detail = ZWOCamera._sdk_error or self.i18n.t("no_camera_found")
                self._update_status_labels()
        else:
            devices = list_camera_devices(camera_type, current_id=current_id)
            if devices:
                self.last_status_detail = ""

        self._updating_ui = True
        self.camera_device_combo.clear()
        if devices:
            for device_id, name in devices:
                self.camera_device_combo.addItem(name, int(device_id))
        else:
            # 没识别到真实设备时保留当前编号，方便用户修复驱动/zwoasi 后再次点刷新
            self.camera_device_combo.addItem(self.i18n.t("no_camera_found"), int(current_id))

        # 尽量保持原来选择的编号
        target_index = 0
        for i in range(self.camera_device_combo.count()):
            if int(self.camera_device_combo.itemData(i)) == int(current_id):
                target_index = i
                break
        self.camera_device_combo.setCurrentIndex(target_index)
        self._updating_ui = False

    def browse_zwo_dll(self) -> None:
        """手动选择 ASICamera2.dll

        自动搜索失败时，建议选择 ZWO 安装目录中的 64 位 ASICamera2.dll，
        不要选择 C:/Windows/SysWOW64 里的 32 位 DLL
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.i18n.t("select_zwo_dll"),
            self.zwo_dll_edit.text().strip() or "C:/Program Files",
            "ASICamera2.dll (ASICamera2.dll);;DLL (*.dll);;All Files (*)",
        )
        if path:
            # 只接受 SDK 入口 ASICamera2.dll用户如果误选 ASI662MM-Pro.dll 这种相机型号 DLL，
            # ctypes 无法通过它枚举设备，必须提示重新选择
            if Path(path).name.lower() != "asicamera2.dll":
                QMessageBox.warning(
                    self,
                    self.i18n.t("select_zwo_dll"),
                    self.i18n.t("wrong_zwo_dll"),
                )
                # 保留路径用于底层在附近搜索 ASICamera2.dll，但不把这个错误文件当作可加载 SDK
            self.zwo_dll_edit.setText(path)
            self.config.zwo_dll_path = path
            # 选择一次后立即记忆化，哪怕用户忘记点“保存参数”，下次打开也会自动使用该路径
            self.config_manager.save(self.config)
            self.last_status_key = "zwo_dll_remembered"
            self.refresh_camera_devices()

    def start_camera(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.thread = VideoThread(self.config)
        self.thread.frame_signal.connect(self._on_frame_ready)
        self.thread.status_signal.connect(self._handle_thread_status)
        self.thread.start()
        self.last_status_key = "running"
        self._update_status_labels()

    def _on_frame_ready(self, cv_img: np.ndarray) -> None:
        """绘制一帧并向采集线程释放单帧背压槽位

        使用 sender() 而不是 self.thread，可避免停止旧相机并启动新相机时，
        旧线程残留信号误释放新线程的帧槽位
        """
        source_thread = self.sender()
        try:
            self.update_image(cv_img)
        finally:
            if isinstance(source_thread, VideoThread):
                source_thread.mark_frame_consumed()

    def stop_camera(self) -> None:
        if hasattr(self, "video_label"):
            self._cancel_outer_three_point_mode(clear_points=True)
        if self.thread:
            self.thread.stop()
            self.thread = None
        self.last_status_key = "stopped"
        self._update_status_labels()

    def apply_camera_settings(self) -> None:
        self.config.camera_type = self.camera_type_combo.currentText()
        self.config.camera_id = self._current_camera_id()
        self.config.zwo_dll_path = self.zwo_dll_edit.text().strip()
        self.config.camera_exposure_ms = float(self.exposure_spin.value())
        self.config.camera_iso = int(self.iso_spin.value())
        self.config.camera_gain = int(self.gain_spin.value())
        self.config.camera_auto_exposure = self.auto_exposure_check.isChecked()
        self.config.camera_auto_focus = self.auto_focus_check.isChecked()
        self.config.camera_focus = int(self.focus_spin.value())
        self.config.ui_fps_limit = int(self.ui_fps_spin.value())
        if self.thread and self.thread.isRunning():
            self.thread.set_fps_limit(self.config.ui_fps_limit)
        w, h = self._parse_resolution(self.res_combo.currentText())
        self.config.frame_width = w
        self.config.frame_height = h
        self.config.update_center_from_offsets()
        self.config_manager.save(self.config)
        self.stop_camera()
        self.start_camera()

    def apply_camera_params(self) -> None:
        """应用曝光/增益等相机参数

        性能优化：旧逻辑会停止相机再重新启动
        ZWO 长曝光时，停止线程可能要等 ASIGetVideoData 超时，界面会明显卡顿
        新逻辑是在采集线程内在线写入曝光/增益；只有相机品牌、设备、分辨率、SDK DLL 改变时才需要“应用相机”重启后端
        """
        self.config.zwo_dll_path = self.zwo_dll_edit.text().strip()
        self.config.camera_exposure_ms = float(self.exposure_spin.value())
        self.config.camera_iso = int(self.iso_spin.value())
        self.config.camera_gain = int(self.gain_spin.value())
        self.config.camera_auto_exposure = self.auto_exposure_check.isChecked()
        self.config.camera_auto_focus = self.auto_focus_check.isChecked()
        self.config.camera_focus = int(self.focus_spin.value())
        self.config.ui_fps_limit = int(self.ui_fps_spin.value())

        if self.thread and self.thread.isRunning():
            self.thread.set_fps_limit(self.config.ui_fps_limit)
            self._camera_param_timer.stop()
            self.thread.request_camera_controls(
                self.config.camera_exposure_ms,
                self.config.camera_iso,
                self.config.camera_gain,
                self.config.camera_auto_exposure,
                self.config.camera_auto_focus,
                self.config.camera_focus,
            )
            self.last_status_key = "params_applied"
        else:
            self.last_status_key = "params_applied"
        self._update_status_labels()

    def _parse_resolution(self, text: str) -> Tuple[int, int]:
        try:
            w, h = text.lower().split("x")
            return int(w), int(h)
        except Exception:
            return 1280, 720

    def _handle_thread_status(self, key: str) -> None:
        # 关键修正：真实相机打开失败时，不再把 UI 和配置强制改回 synthetic
        # 这样用户能看到自己当前选的仍然是 zwo，并可以修复依赖后直接刷新/重试
        if "::" in key:
            key, detail = key.split("::", 1)
            self.last_status_detail = detail
        else:
            self.last_status_detail = "" if key == "camera_opened" else self.last_status_detail
        self.last_status_key = "running" if key == "camera_opened" else key
        self._update_status_labels()

    # ------------------------------------------------------------------
    # 参数同步和覆盖层控制
    # ------------------------------------------------------------------
    def _sync_all_controls_from_config(self) -> None:
        self._updating_ui = True
        self.lang_combo.setCurrentText(self.config.language)
        self.zwo_dll_edit.setText(self.config.zwo_dll_path)
        self.camera_type_combo.setCurrentText(self.config.camera_type)
        self._update_camera_brand_visibility()
        self.refresh_camera_devices()
        for i in range(self.camera_device_combo.count()):
            if int(self.camera_device_combo.itemData(i)) == int(self.config.camera_id):
                self.camera_device_combo.setCurrentIndex(i)
                break
        self.res_combo.setCurrentText(f"{self.config.frame_width}x{self.config.frame_height}")
        self.ui_fps_spin.setValue(int(self.config.ui_fps_limit))
        self.exposure_spin.setValue(float(self.config.camera_exposure_ms))
        self.iso_spin.setValue(int(self.config.camera_iso))
        self.gain_spin.setValue(int(self.config.camera_gain))
        self.auto_exposure_check.setChecked(bool(self.config.camera_auto_exposure))
        self.auto_focus_check.setChecked(bool(self.config.camera_auto_focus))
        self.focus_spin.setValue(int(self.config.camera_focus))
        self.focus_spin.setEnabled(not bool(self.config.camera_auto_focus))
        self.h_offset_slider.setValue(int(round(float(self.config.horizontal_offset))))
        self.v_offset_slider.setValue(int(round(float(self.config.vertical_offset))))
        self.h_offset_value.setValue(float(self.config.horizontal_offset))
        self.v_offset_value.setValue(float(self.config.vertical_offset))
        self.zoom_slider.setValue(self.config.zoom_percent)
        self.zoom_value.setText(str(self.config.zoom_percent))
        self.view_pan_x_slider.setValue(int(self.config.view_pan_x))
        self.view_pan_y_slider.setValue(int(self.config.view_pan_y))
        self._update_pan_sliders_enabled()
        self.middle_xy = (int(self.config.circle2_center_x), int(self.config.circle2_center_y))
        self.inner_xy = (int(self.config.circle3_center_x), int(self.config.circle3_center_y))
        self.secondary_xy = (int(self.config.circle4_center_x), int(self.config.circle4_center_y))
        self.active_target = self.config.active_target if self.config.active_target in {"middle", "inner", "secondary"} else "middle"
        self.detected_xy = self._active_xy()
        self._sync_target_sliders()
        self.middle_track_check.setChecked(bool(self.config.track_middle))
        self.middle_concentric_check.setChecked(bool(self.config.middle_concentric_with_outer))
        self.inner_track_check.setChecked(bool(self.config.track_inner))
        self.inner_concentric_check.setChecked(bool(self.config.inner_concentric_with_outer))
        self.secondary_track_check.setChecked(bool(self.config.track_secondary))
        self.secondary_concentric_check.setChecked(bool(self.config.secondary_concentric_with_outer))
        self.star_enable.setChecked(self.config.star.enabled)
        self.star_len_slider.setValue(self.config.star.length)
        self.star_thick_spin.setValue(self.config.star.thickness)
        self.star_angle_slider.setValue(self.config.star.angle)
        self.star_color_button._set_bgr_color(self.config.star.color)  # type: ignore[attr-defined]
        for labels in self.circle_widgets:
            c: CircleConfig = labels["circle"]
            labels["enabled"].setChecked(c.enabled)
            labels["radius_slider"].setValue(c.radius)
            labels["radius_value"].setText(str(c.radius))
            labels["thickness"].setValue(c.thickness)
            labels["color_button"]._set_bgr_color(c.color)  # type: ignore[attr-defined]
        self.roi_slider.setValue(self.config.snap_roi)
        self.threshold_slider.setValue(self.config.snap_threshold)
        self.band_slider.setValue(self.config.edge_band_width)
        self.secondary_band_slider.setValue(self.config.secondary_edge_band_width)
        self.secondary_sensitivity_slider.setValue(self.config.secondary_edge_sensitivity)
        self._updating_ui = False
        self._update_middle_concentric_ui()
        self._update_inner_concentric_ui()
        self._update_secondary_concentric_ui()
        self._update_reference_lock_ui()


    def _sync_target_sliders(self) -> None:
        """把中圈/内圈当前位置同步到各自调节框的 X/Y 滑条

        滑条显示的是“目标圆心相对外圈参考圆心”的偏移，而不是绝对像素坐标
        这样用户看到的数值就是调节过程中的 dx/dy
        """
        if not hasattr(self, "middle_x_slider"):
            return
        self._updating_ui = True
        mid_dx = int(self.config.circle2_center_x - self.config.center_x)
        mid_dy = int(self.config.circle2_center_y - self.config.center_y)
        in_dx = int(self.config.circle3_center_x - self.config.center_x)
        in_dy = int(self.config.circle3_center_y - self.config.center_y)
        sec_dx = int(self.config.circle4_center_x - self.config.center_x)
        sec_dy = int(self.config.circle4_center_y - self.config.center_y)
        for slider, label, value in [
            (self.middle_x_slider, self.middle_x_value, mid_dx),
            (self.middle_y_slider, self.middle_y_value, mid_dy),
            (self.inner_x_slider, self.inner_x_value, in_dx),
            (self.inner_y_slider, self.inner_y_value, in_dy),
            (self.secondary_x_slider, self.secondary_x_value, sec_dx),
            (self.secondary_y_slider, self.secondary_y_value, sec_dy),
        ]:
            value = int(max(slider.minimum(), min(slider.maximum(), value)))
            slider.setValue(value)
            label.setValue(int(value))
        self._updating_ui = False

    def _set_center_from_mouse(self, x: int, y: int) -> None:
        """鼠标点击/拖拽画面时更新外圈参考中心

        关键交互逻辑：
        1. 100% 原始视图下，直接移动外圈参考中心
        2. 放大视图下，也允许点选/拖拽外圈参考中心，但不能让画面跟着鼠标跳动
           因此在修改 center_x/center_y 前，先记录当前裁剪视野的实际中心点；
           修改参考中心后，再反向调整 view_pan_x/view_pan_y，让裁剪视野保持在原地
        """
        if self.config.reference_locked:
            return

        # 鼠标点选/拖动只更新当前外圈搜索中心，不应取消已经完成的按钮吸附次数
        # 在 1/3 或 2/3 阶段手动修正位置后，下一次“吸附外圈边缘”会以
        # 当前 center_x/center_y 为新的搜索初值，同时保留前面已记录的结果

        # 记录当前放大裁剪窗口的中心放大时 _apply_zoom_to_frame 使用
        # center_x + view_pan_x / center_y + view_pan_y 作为裁剪中心
        keep_view_still = int(self.config.zoom_percent) > 100
        view_anchor_x = int(self.config.center_x + self.config.view_pan_x)
        view_anchor_y = int(self.config.center_y + self.config.view_pan_y)

        # 鼠标拖拽的是外圈参考中心/零点位置调好后可以保存，下次启动复用
        self.config.center_x = int(x)
        self.config.center_y = int(y)
        self.config.update_offsets_from_center()

        if keep_view_still:
            # 保持当前看到的裁剪区域不动这样放大后仍然可以点选/拖拽圆心，
            # 但画面不会因为 reference center 改变而自动跟随移动
            self.config.view_pan_x = int(view_anchor_x - self.config.center_x)
            self.config.view_pan_y = int(view_anchor_y - self.config.center_y)
            if hasattr(self, "view_pan_x_slider"):
                self.config.view_pan_x = int(max(self.view_pan_x_slider.minimum(),
                                                 min(self.view_pan_x_slider.maximum(), self.config.view_pan_x)))
                self.view_pan_x_slider.setValue(self.config.view_pan_x)
            if hasattr(self, "view_pan_y_slider"):
                self.config.view_pan_y = int(max(self.view_pan_y_slider.minimum(),
                                                 min(self.view_pan_y_slider.maximum(), self.config.view_pan_y)))
                self.view_pan_y_slider.setValue(self.config.view_pan_y)

        self._sync_offset_sliders()
        self._sync_target_sliders()
        self.last_status_key = "reference_set"
        self._update_status_labels()

    def reset_center(self) -> None:
        self._cancel_outer_three_point_mode(clear_points=True)
        self.config.horizontal_offset = 0
        self.config.vertical_offset = 0
        self.config.update_center_from_offsets()
        self.config.reference_locked = False
        if self.config.middle_concentric_with_outer:
            self._apply_middle_concentric_position()
        else:
            self._set_target_xy("middle", self.config.center_x, self.config.center_y)
        if self.config.inner_concentric_with_outer:
            self._apply_inner_concentric_position()
        else:
            self._set_target_xy("inner", self.config.center_x, self.config.center_y)
        if self.config.secondary_concentric_with_outer:
            self._apply_secondary_concentric_position()
        else:
            self._set_target_xy("secondary", self.config.center_x, self.config.center_y)
        self.last_source_key = "source_waiting"
        self.last_status_key = "waiting"
        self.last_status_detail = ""
        self._sync_offset_sliders()
        self._update_reference_lock_ui()
        self._update_status_labels()

    def set_outer_as_reference(self) -> None:
        """把当前外圈圆心锁定为调节参考圆心

        外圈圆心来自镜筒/调焦筒边缘，因此它就是后续中圈、内圈需要移动过去的机械基准
        """
        self._cancel_outer_three_point_mode(clear_points=True)
        self.config.reference_locked = True
        self.last_status_key = "reference_set"
        self.last_status_detail = ""
        self._sync_offset_sliders()
        self._sync_target_sliders()
        self._update_reference_lock_ui()
        self._push_history()
        self._update_status_labels()

    def _sync_offset_sliders(self) -> None:
        self._updating_ui = True
        h_value = float(max(self.h_offset_slider.minimum(), min(self.h_offset_slider.maximum(), self.config.horizontal_offset)))
        v_value = float(max(self.v_offset_slider.minimum(), min(self.v_offset_slider.maximum(), self.config.vertical_offset)))
        self.h_offset_slider.setValue(int(round(h_value)))
        self.v_offset_slider.setValue(int(round(v_value)))
        self.h_offset_value.setValue(h_value)
        self.v_offset_value.setValue(v_value)
        self._updating_ui = False

    def _on_h_offset(self, value: float) -> None:
        if self._updating_ui or self.config.reference_locked:
            return
        self.config.horizontal_offset = float(value)
        self.config.update_center_from_offsets()
        self._sync_target_sliders()
        self._update_status_labels()

    def _on_v_offset(self, value: float) -> None:
        if self._updating_ui or self.config.reference_locked:
            return
        self.config.vertical_offset = float(value)
        self.config.update_center_from_offsets()
        self._sync_target_sliders()
        self._update_status_labels()



    def _apply_middle_concentric_position(self, sync_ui: bool = True) -> None:
        """让中圈圆心固定等于外圈参考中心

        实时视频路径传 sync_ui=False，避免每一帧都重设滑块和文本造成额外事件
        """
        target = (int(self.config.center_x), int(self.config.center_y))
        changed = self.middle_xy != target or (self.config.circle2_center_x, self.config.circle2_center_y) != target
        self.middle_xy = target
        self.config.circle2_center_x, self.config.circle2_center_y = target
        if self.active_target == "middle":
            self._set_active_target(self._fallback_target())
        if sync_ui and changed:
            self._sync_target_sliders()

    def _on_middle_concentric_mode(self) -> None:
        """切换“中圈与外圈同心”模式"""
        if self._updating_ui:
            return
        enabled = self.middle_concentric_check.isChecked()
        self.config.middle_concentric_with_outer = bool(enabled)
        if enabled:
            self.config.track_middle = False
            self.middle_track_check.setChecked(False)
            self._apply_middle_concentric_position()
            self.last_source_key = "source_middle_concentric"
        self._update_middle_concentric_ui()
        self._update_status_labels()

    def _update_middle_concentric_ui(self) -> None:
        """中圈同心模式下禁用会改变中圈圆心的控件，保留半径/线宽/颜色"""
        if not hasattr(self, "middle_concentric_check"):
            return
        enabled = bool(self.config.middle_concentric_with_outer)
        for widget in [self.middle_x_slider, self.middle_y_slider, self.middle_x_value, self.middle_y_value, self.btn_snap_middle_edge, self.middle_track_check]:
            widget.setEnabled(not enabled)
        if enabled:
            self._apply_middle_concentric_position()



    def _apply_inner_concentric_position(self, sync_ui: bool = True) -> None:
        """让内圈圆心固定等于外圈参考中心实时帧中不重复刷新控件"""
        target = (int(self.config.center_x), int(self.config.center_y))
        changed = self.inner_xy != target or (self.config.circle3_center_x, self.config.circle3_center_y) != target
        self.inner_xy = target
        self.config.circle3_center_x, self.config.circle3_center_y = target
        if self.active_target == "inner":
            self._set_active_target(self._fallback_target())
        if sync_ui and changed:
            self._sync_target_sliders()

    def _on_inner_concentric_mode(self) -> None:
        """切换“内圈与外圈同心”模式"""
        if self._updating_ui:
            return
        enabled = self.inner_concentric_check.isChecked()
        self.config.inner_concentric_with_outer = bool(enabled)
        if enabled:
            self.config.track_inner = False
            self.inner_track_check.setChecked(False)
            self._apply_inner_concentric_position()
            self.last_source_key = "source_inner_concentric"
        self._update_inner_concentric_ui()
        self._update_status_labels()

    def _update_inner_concentric_ui(self) -> None:
        """内圈同心模式下禁用会改变内圈圆心的控件，保留半径/线宽/颜色"""
        if not hasattr(self, "inner_concentric_check"):
            return
        enabled = bool(self.config.inner_concentric_with_outer)
        for widget in [self.inner_x_slider, self.inner_y_slider, self.inner_x_value, self.inner_y_value, self.btn_snap_inner_edge, self.inner_track_check]:
            widget.setEnabled(not enabled)
        if enabled:
            self._apply_inner_concentric_position()

    def _apply_secondary_concentric_position(self, sync_ui: bool = True) -> None:
        """让副镜圈圆心固定等于外圈参考中心实时帧中不重复刷新控件"""
        target = (int(self.config.center_x), int(self.config.center_y))
        changed = self.secondary_xy != target or (self.config.circle4_center_x, self.config.circle4_center_y) != target
        self.secondary_xy = target
        self.config.circle4_center_x, self.config.circle4_center_y = target
        if self.active_target == "secondary":
            self._set_active_target(self._fallback_target())
        if sync_ui and changed:
            self._sync_target_sliders()

    def _on_secondary_concentric_mode(self) -> None:
        """切换“副镜圈与外圈同心”模式"""
        if self._updating_ui:
            return
        enabled = self.secondary_concentric_check.isChecked()
        self.config.secondary_concentric_with_outer = bool(enabled)
        if enabled:
            self.config.track_secondary = False
            self.secondary_track_check.setChecked(False)
            self._apply_secondary_concentric_position()
            self.last_source_key = "source_secondary_concentric"
        self._update_secondary_concentric_ui()
        self._update_status_labels()

    def _update_secondary_concentric_ui(self) -> None:
        """副镜同心模式下禁用会改变副镜圆心的控件，保留半径/线宽/颜色"""
        if not hasattr(self, "secondary_concentric_check"):
            return
        enabled = bool(self.config.secondary_concentric_with_outer)
        for widget in [self.secondary_x_slider, self.secondary_y_slider, self.secondary_x_value, self.secondary_y_value, self.btn_snap_secondary_edge, self.secondary_track_check]:
            widget.setEnabled(not enabled)
        if enabled:
            self._apply_secondary_concentric_position()

    def _update_reference_lock_ui(self) -> None:
        """外圈设为参考中心后，锁定会改变外圈参考几何的控件

        锁定后只允许继续修改外圈颜色和线宽；半径、位置、启用状态、吸附和设为圆心
        必须等用户点击“重置圆心”后才能再次调整，避免参考中心被误触破坏
        """
        if not hasattr(self, "circle_widgets") or not self.circle_widgets:
            return
        locked = bool(self.config.reference_locked)
        outer = self.circle_widgets[0]
        for key in ["enabled", "radius_slider", "radius_value"]:
            outer[key].setEnabled(not locked)
        # 线宽和颜色始终允许调，因为它们只影响显示，不改变参考中心
        outer["thickness"].setEnabled(True)
        outer["color_button"].setEnabled(True)
        for widget in [self.h_offset_slider, self.v_offset_slider, self.h_offset_value, self.v_offset_value, self.btn_set_reference]:
            widget.setEnabled(not locked)
        # 外圈参考圆心一旦锁定，吸附按钮也必须禁用
        # 用户需要点击“重置圆心”解除锁定后，才能开始新一轮三次吸附，
        # 避免误触按钮破坏已经建立的机械参考中心
        self.btn_snap_edge.setEnabled(not locked)


    def _on_middle_x(self, value: int) -> None:
        if self._updating_ui or self.config.middle_concentric_with_outer:
            return
        self._set_target_xy("middle", self.config.center_x + int(value), self.config.circle2_center_y)
        self.last_source_key = "source_middle_edge"
        self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
        self._update_status_labels()

    def _on_middle_y(self, value: int) -> None:
        if self._updating_ui or self.config.middle_concentric_with_outer:
            return
        self._set_target_xy("middle", self.config.circle2_center_x, self.config.center_y + int(value))
        self.last_source_key = "source_middle_edge"
        self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
        self._update_status_labels()

    def _on_inner_x(self, value: int) -> None:
        if self._updating_ui or self.config.inner_concentric_with_outer:
            return
        self._set_target_xy("inner", self.config.center_x + int(value), self.config.circle3_center_y)
        self.last_source_key = "source_inner_edge"
        self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
        self._update_status_labels()

    def _on_inner_y(self, value: int) -> None:
        if self._updating_ui or self.config.inner_concentric_with_outer:
            return
        self._set_target_xy("inner", self.config.circle3_center_x, self.config.center_y + int(value))
        self.last_source_key = "source_inner_edge"
        self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
        self._update_status_labels()

    def _on_secondary_x(self, value: int) -> None:
        if self._updating_ui or self.config.secondary_concentric_with_outer:
            return
        self._set_target_xy("secondary", self.config.center_x + int(value), self.config.circle4_center_y)
        self.last_source_key = "source_secondary_edge"
        self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
        self._update_status_labels()

    def _on_secondary_y(self, value: int) -> None:
        if self._updating_ui or self.config.secondary_concentric_with_outer:
            return
        self._set_target_xy("secondary", self.config.circle4_center_x, self.config.center_y + int(value))
        self.last_source_key = "source_secondary_edge"
        self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
        self._update_status_labels()

    def _on_track_middle(self) -> None:
        if self.config.middle_concentric_with_outer:
            self.middle_track_check.setChecked(False)
            self.config.track_middle = False
            return
        self.config.track_middle = self.middle_track_check.isChecked()
        self.config.auto_tracking = bool(self.config.track_middle or self.config.track_inner or self.config.track_secondary)
        if self.config.track_middle:
            self._set_active_target("middle")

    def _on_track_inner(self) -> None:
        if self.config.inner_concentric_with_outer:
            self.inner_track_check.setChecked(False)
            self.config.track_inner = False
            return
        self.config.track_inner = self.inner_track_check.isChecked()
        self.config.auto_tracking = bool(self.config.track_middle or self.config.track_inner or self.config.track_secondary)
        if self.config.track_inner:
            self._set_active_target("inner")

    def _on_track_secondary(self) -> None:
        if self.config.secondary_concentric_with_outer:
            self.secondary_track_check.setChecked(False)
            self.config.track_secondary = False
            return
        self.config.track_secondary = self.secondary_track_check.isChecked()
        self.config.auto_tracking = bool(self.config.track_middle or self.config.track_inner or self.config.track_secondary)
        if self.config.track_secondary:
            self._set_active_target("secondary")

    def _on_zoom(self, value: int) -> None:
        self.config.zoom_percent = value
        self._update_pan_sliders_enabled()

    def _on_video_wheel_zoom(self, steps: int) -> None:
        """鼠标在画面上滚动滚轮时放大/缩小

        每格滚轮调整 10%，最终仍通过右侧 zoom_slider 生效，保证 UI 显示、配置保存和坐标映射一致
        """
        if not hasattr(self, "zoom_slider"):
            return
        step = 10 if steps > 0 else -10
        new_value = max(self.zoom_slider.minimum(), min(self.zoom_slider.maximum(), self.zoom_slider.value() + step))
        self.zoom_slider.setValue(new_value)

    def _on_view_pan_x(self, value: int) -> None:
        """放大画面下方横向滑条：调整当前裁剪视野的水平位置"""
        self.config.view_pan_x = int(value)

    def _on_view_pan_y(self, value: int) -> None:
        """放大画面右侧纵向滑条：调整当前裁剪视野的垂直位置"""
        self.config.view_pan_y = int(value)

    def _update_pan_sliders_enabled(self) -> None:
        """只有在放大状态下启用画面平移滑条"""
        enabled = int(self.config.zoom_percent) > 100
        if hasattr(self, "view_pan_x_slider"):
            self.view_pan_x_slider.setEnabled(enabled)
            self.view_pan_x_slider.setVisible(enabled)
        if hasattr(self, "view_pan_y_slider"):
            self.view_pan_y_slider.setEnabled(enabled)
            self.view_pan_y_slider.setVisible(enabled)

    def _update_circle(self, circle: CircleConfig, enabled: Optional[bool] = None,
                       radius: Optional[int] = None, thickness: Optional[float] = None,
                       color: Optional[Tuple[int, int, int]] = None) -> None:
        if enabled is not None:
            circle.enabled = enabled
        if radius is not None:
            circle.radius = radius
        if thickness is not None:
            circle.thickness = float(thickness)
        if color is not None:
            circle.color = color

    def _update_star(self, length: Optional[int] = None, thickness: Optional[float] = None,
                     angle: Optional[int] = None, color: Optional[Tuple[int, int, int]] = None) -> None:
        self.config.star.enabled = self.star_enable.isChecked()
        if length is not None:
            self.config.star.length = length
        if thickness is not None:
            self.config.star.thickness = float(thickness)
        if angle is not None:
            self.config.star.angle = angle
        if color is not None:
            self.config.star.color = color

    def _on_roi(self, value: int) -> None:
        self.config.snap_roi = value

    def _on_threshold(self, value: int) -> None:
        self.config.snap_threshold = value

    def _on_band(self, value: int) -> None:
        self.config.edge_band_width = value

    def _on_secondary_band(self, value: int) -> None:
        self.config.secondary_edge_band_width = value

    def _on_secondary_sensitivity(self, value: int) -> None:
        self.config.secondary_edge_sensitivity = value

    # ------------------------------------------------------------------
    # 自动识别与调整提示
    # ------------------------------------------------------------------
    def snap_center(self) -> None:
        """吸附中圈内部的圆形亮斑中心

        这个功能保留在中圈调节框内，适合画面中圆形亮斑边缘不清晰时快速得到一个中圈圆心初值
        """
        if self.current_frame is None:
            return
        search_center = self.middle_xy
        ok, nx, ny, info = VisionEngine.snap_bright_center(
            self.current_frame,
            search_center[0],
            search_center[1],
            self.config.snap_roi,
            self.config.snap_threshold,
        )
        if ok:
            self._set_target_xy("middle", nx, ny)
            self.last_score = info.get("score", 100.0)
            self._target_scores["middle"] = self.last_score
            self.last_source_key = "source_middle_edge"
            self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
            self._push_history()
        else:
            self.last_score = 0.0
            self.last_source_key = "source_waiting"
            self.last_status_key = "snap_fail"
            QMessageBox.warning(self, self.i18n.t("auto_snap_center"), self.i18n.t("snap_fail"))
        self._update_status_labels()

    def _update_outer_pick_button_text(self) -> None:
        """根据三次按钮吸附进度更新按钮文字"""
        if not hasattr(self, "btn_snap_edge"):
            return
        base = self.i18n.t("auto_snap_edge")
        count = len(self._outer_snap_results)
        if self._outer_three_point_mode and count <= 3:
            self.btn_snap_edge.setText(f"{base} ({count}/3)")
        else:
            self.btn_snap_edge.setText(base)

    def _cancel_outer_three_point_mode(self, clear_points: bool = True) -> None:
        self._outer_three_point_mode = False
        self._outer_finalize_pending = False
        if clear_points:
            self._outer_snap_results.clear()
            self._outer_snap_scores.clear()
            self._outer_snap_point_sets.clear()
            self._outer_snap_infos.clear()
            self._outer_snap_start_geometry = None
        self._update_outer_pick_button_text()
        if hasattr(self, "btn_snap_edge"):
            self.btn_snap_edge.setEnabled(not bool(self.config.reference_locked))

    def _apply_outer_snap_geometry(self, x: int, y: int, radius: int) -> None:
        """应用一次外圈拟合结果，并在放大状态下保持当前视野不跳动"""
        keep_view_still = int(self.config.zoom_percent) > 100
        view_anchor_x = int(self.config.center_x + self.config.view_pan_x)
        view_anchor_y = int(self.config.center_y + self.config.view_pan_y)

        self.config.center_x = int(x)
        self.config.center_y = int(y)
        self.config.circle1.radius = int(radius)
        self.config.update_offsets_from_center()

        if keep_view_still:
            self.config.view_pan_x = int(view_anchor_x - self.config.center_x)
            self.config.view_pan_y = int(view_anchor_y - self.config.center_y)
            self.config.view_pan_x = int(max(self.view_pan_x_slider.minimum(),
                                             min(self.view_pan_x_slider.maximum(), self.config.view_pan_x)))
            self.config.view_pan_y = int(max(self.view_pan_y_slider.minimum(),
                                             min(self.view_pan_y_slider.maximum(), self.config.view_pan_y)))
            self.view_pan_x_slider.setValue(self.config.view_pan_x)
            self.view_pan_y_slider.setValue(self.config.view_pan_y)

        if self.config.middle_concentric_with_outer:
            self._apply_middle_concentric_position()
        if self.config.inner_concentric_with_outer:
            self._apply_inner_concentric_position()
        if self.config.secondary_concentric_with_outer:
            self._apply_secondary_concentric_position()

        outer = self.circle_widgets[0]
        self._updating_ui = True
        outer["radius_slider"].setValue(self.config.circle1.radius)
        outer["radius_value"].setText(str(self.config.circle1.radius))
        self._updating_ui = False
        self._sync_offset_sliders()
        self._sync_target_sliders()

    def snap_outer_edge(self) -> None:
        """连续点击三次按钮，合并三轮边缘内点后执行联合鲁棒几何圆拟合

        每次点击都自动采集大量边缘点；第三次先做轮次级一致性排异，再合并
        有效轮次的全部内点，使用 RANSAC + Huber-IRLS + 条件数/角度覆盖检查
        求最终圆心鼠标只负责改变下一次搜索初值，不参与边缘点采集
        """
        if self.config.reference_locked:
            return
        # 第三轮已经采集完成、联合拟合尚未结束时禁止再次进入，
        # 避免双击造成第 4 次采样或重复执行最终融合
        if self._outer_finalize_pending:
            return
        if self.current_frame is None:
            QMessageBox.warning(self, self.i18n.t("auto_snap_edge"), self.i18n.t("waiting"))
            return

        # 仅在按钮点击时复制一帧，确保本轮检测始终使用同一张完整图像
        # 这不会影响持续视频性能，因为三次标定只发生三次复制
        frame_for_snap = self.current_frame.copy()

        if not self._outer_three_point_mode:
            self._outer_three_point_mode = True
            self._outer_snap_results.clear()
            self._outer_snap_scores.clear()
            self._outer_snap_point_sets.clear()
            self._outer_snap_infos.clear()
            self._outer_snap_start_geometry = (
                int(self.config.center_x), int(self.config.center_y), int(self.config.circle1.radius)
            )

        start_x = int(self.config.center_x)
        start_y = int(self.config.center_y)
        start_r = int(self.config.circle1.radius)
        ok, nx, ny, nr, info = VisionEngine.snap_outer_edge(
            frame_for_snap,
            start_x,
            start_y,
            start_r,
            self.config.edge_band_width,
        )
        if not ok:
            self.last_score = 0.0
            self.last_source_key = "source_outer_three_point"
            self.last_status_key = "outer_auto_fit_fail"
            reason = str(info.get("reason", "fit_failed"))
            self.last_status_detail = f"{self.i18n.t('outer_auto_fit_fail_tip')} [{reason}]"
            self._update_outer_pick_button_text()
            self._update_status_labels()
            QMessageBox.warning(
                self,
                self.i18n.t("auto_snap_edge"),
                f"{self.i18n.t('outer_auto_fit_fail_tip')}\n{reason}",
            )
            return

        raw_points = np.asarray(info.get("inlier_points", np.empty((0, 2))), dtype=np.float32)
        if raw_points.ndim != 2 or raw_points.shape[1] != 2 or raw_points.shape[0] < 24:
            self.last_score = 0.0
            self.last_status_key = "outer_auto_fit_fail"
            self.last_status_detail = self.i18n.t("outer_auto_fit_fail_tip")
            self._update_status_labels()
            return

        result = (int(nx), int(ny), int(nr))
        snap_score = float(info.get("score", 0.0))
        self._outer_snap_results.append(result)
        self._outer_snap_scores.append(snap_score)
        self._outer_snap_point_sets.append(raw_points.copy())
        self._outer_snap_infos.append(dict(info))
        self._apply_outer_snap_geometry(*result)

        count = len(self._outer_snap_results)
        self.last_score = snap_score
        self.last_source_key = "source_outer_three_point"
        self._update_outer_pick_button_text()
        coverage = float(info.get("coverage", 0.0))
        condition = float(info.get("condition_number", 0.0))
        if count < 3:
            self.last_status_key = "outer_button_second" if count == 1 else "outer_button_third"
            self.last_status_detail = (
                f"{self.i18n.t('outer_button_continue_tip')} "
                f"points={raw_points.shape[0]}, coverage={coverage:.0f}°, cond={condition:.2f}"
            )
            self._update_status_labels()
            return

        # 第三次点击已经真实执行了一次完整的 VisionEngine.snap_outer_edge
        # 先显示第三轮单独吸附结果和 3/3 状态，再延后执行联合拟合；
        # 这样用户能明确看到三次吸附，而不是第三轮被最终结果瞬间覆盖
        self._outer_finalize_pending = True
        self.btn_snap_edge.setEnabled(False)
        self.last_status_key = "outer_button_complete"
        self.last_status_detail = (
            f"{self.i18n.t('outer_button_fusing_tip')} "
            f"points={raw_points.shape[0]}, coverage={coverage:.0f}°, cond={condition:.2f}"
        )
        self._update_status_labels()
        QTimer.singleShot(120, self._finalize_outer_three_snap)

    def _finalize_outer_three_snap(self) -> None:
        """在三次独立吸附都完成后，联合三轮有效边缘点求最终圆"""
        if (not self._outer_three_point_mode or not self._outer_finalize_pending
                or len(self._outer_snap_results) < 3):
            return

        # 轮次级排异：先寻找圆心/半径最一致的两轮，再判断第三轮是否可纳入
        values = np.asarray(self._outer_snap_results[:3], dtype=np.float64)
        scores = np.asarray(self._outer_snap_scores[:3], dtype=np.float64)
        pair_distances: list[Tuple[float, int, int]] = []
        for i in range(3):
            for j in range(i + 1, 3):
                center_delta = math.hypot(values[i, 0] - values[j, 0], values[i, 1] - values[j, 1])
                radius_delta = abs(values[i, 2] - values[j, 2])
                pair_distances.append((center_delta + radius_delta * 0.55, i, j))
        pair_distances.sort(key=lambda item: item[0])
        closest_distance, first_idx, second_idx = pair_distances[0]
        median_radius = float(np.median(values[:, 2]))
        pair_limit = max(7.0, float(self.config.edge_band_width) * 1.05, median_radius * 0.035)

        if closest_distance > pair_limit:
            self.last_score = 0.0
            self.last_status_key = "outer_three_fit_inconsistent"
            self.last_status_detail = self.i18n.t("outer_three_fit_inconsistent_tip")
            if self._outer_snap_start_geometry is not None:
                self._apply_outer_snap_geometry(*self._outer_snap_start_geometry)
            self._cancel_outer_three_point_mode(clear_points=True)
            self._update_status_labels()
            QMessageBox.warning(
                self, self.i18n.t("auto_snap_edge"), self.i18n.t("outer_three_fit_inconsistent_tip")
            )
            return

        seed_indices = [first_idx, second_idx]
        seed_circle = values[seed_indices].mean(axis=0)
        inlier_limit = max(pair_limit, closest_distance * 2.0 + 1.5)
        accepted_indices: list[int] = []
        for i in range(3):
            distance = math.hypot(values[i, 0] - seed_circle[0], values[i, 1] - seed_circle[1])
            distance += abs(values[i, 2] - seed_circle[2]) * 0.55
            if distance <= inlier_limit:
                accepted_indices.append(i)
        if len(accepted_indices) < 2:
            accepted_indices = seed_indices

        # 平衡每轮点数，避免 Canny 兜底轮因为点更多而压倒径向采样轮
        balanced_sets: list[np.ndarray] = []
        max_points_per_round = 1400
        for idx in accepted_indices:
            pts = np.asarray(self._outer_snap_point_sets[idx], dtype=np.float64)
            if pts.shape[0] > max_points_per_round:
                choose = np.linspace(0, pts.shape[0] - 1, max_points_per_round, dtype=np.int64)
                pts = pts[choose]
            balanced_sets.append(pts)
        merged_points = np.vstack(balanced_sets)

        selected_scores = np.clip(scores[accepted_indices], 5.0, 100.0)
        weights = selected_scores / float(selected_scores.sum())
        prior_circle = np.sum(values[accepted_indices] * weights[:, None], axis=0)
        joint = VisionEngine.fit_circle_points_robust(
            merged_points,
            float(prior_circle[0]),
            float(prior_circle[1]),
            float(prior_circle[2]),
            band_width=self.config.edge_band_width,
            min_points=48,
            min_coverage_deg=135.0,
            use_ransac=True,
        )
        if not joint.get("ok", False):
            self.last_score = 0.0
            self.last_status_key = "outer_joint_fit_degenerate"
            reason = str(joint.get("reason", "joint_fit_failed"))
            coverage = float(joint.get("coverage", 0.0))
            condition = float(joint.get("condition_number", 0.0))
            self.last_status_detail = (
                f"{self.i18n.t('outer_joint_fit_degenerate_tip')} "
                f"[{reason}, coverage={coverage:.0f}°, cond={condition:.2f}]"
            )
            if self._outer_snap_start_geometry is not None:
                self._apply_outer_snap_geometry(*self._outer_snap_start_geometry)
            self._cancel_outer_three_point_mode(clear_points=True)
            self._update_status_labels()
            QMessageBox.warning(
                self,
                self.i18n.t("auto_snap_edge"),
                f"{self.i18n.t('outer_joint_fit_degenerate_tip')}\n{reason}",
            )
            return

        final_result = (
            int(round(float(joint["cx"]))),
            int(round(float(joint["cy"]))),
            int(round(float(joint["radius"]))),
        )
        self._apply_outer_snap_geometry(*final_result)
        consistency = max(0.0, min(100.0, 100.0 - closest_distance / max(1.0, pair_limit) * 30.0))
        joint_score = float(joint.get("score", 0.0))
        self.last_score = max(0.0, min(100.0, joint_score * 0.84 + consistency * 0.16))
        self.last_source_key = "source_outer_three_point"
        self.last_status_key = "outer_three_point_success"
        self.last_status_detail = (
            f"{self.i18n.t('outer_three_point_success_tip')} "
            f"points={int(joint.get('points', 0))}, "
            f"coverage={float(joint.get('coverage', 0.0)):.0f}°, "
            f"cond={float(joint.get('condition_number', 0.0)):.2f}, "
            f"RMSE={float(joint.get('rmse', 0.0)):.2f}px"
        )
        self._cancel_outer_three_point_mode(clear_points=True)
        self._push_history()
        self._update_status_labels()

    def snap_middle_edge(self) -> None:
        """吸附上传示例图中的大圆形亮斑边缘，更新中圈圆心和半径"""
        if self.config.middle_concentric_with_outer:
            return
        if self.current_frame is None:
            return
        ok, nx, ny, nr, info = VisionEngine.snap_outer_edge(
            self.current_frame,
            self.config.circle2_center_x,
            self.config.circle2_center_y,
            self.config.circle2.radius,
            self.config.edge_band_width,
        )
        if ok:
            self._set_target_xy("middle", nx, ny)
            self.config.circle2.radius = nr
            self.last_score = info.get("score", 100.0)
            self._target_scores["middle"] = self.last_score
            self.last_source_key = "source_middle_edge"
            self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
            self._sync_all_controls_from_config()
            self._push_history()
        else:
            self.last_score = 0.0
            self.last_status_key = "middle_edge_fail"
            QMessageBox.warning(self, self.i18n.t("snap_middle_edge"), self.i18n.t("middle_edge_fail"))
        self._update_status_labels()

    def snap_inner_edge(self) -> None:
        """吸附上传示例图中的红色小圆边缘，更新内圈圆心和半径"""
        if self.config.inner_concentric_with_outer:
            return
        if self.current_frame is None:
            return
        ok, nx, ny, nr, info = VisionEngine.snap_outer_edge(
            self.current_frame,
            self.config.circle3_center_x,
            self.config.circle3_center_y,
            self.config.circle3.radius,
            self.config.edge_band_width,
        )
        if ok:
            self._set_target_xy("inner", nx, ny)
            self.config.circle3.radius = nr
            self.last_score = info.get("score", 100.0)
            self._target_scores["inner"] = self.last_score
            self.last_source_key = "source_inner_edge"
            self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
            self._sync_all_controls_from_config()
            self._push_history()
        else:
            self.last_score = 0.0
            self.last_status_key = "inner_edge_fail"
            QMessageBox.warning(self, self.i18n.t("snap_inner_edge"), self.i18n.t("inner_edge_fail"))
        self._update_status_labels()

    def snap_secondary_edge(self) -> None:
        """吸附副镜边缘，更新副镜圈圆心和半径"""
        if self.config.secondary_concentric_with_outer:
            return
        if self.current_frame is None:
            return
        ok, nx, ny, nr, info = VisionEngine.snap_secondary_edge(
            self.current_frame,
            self.config.circle4_center_x,
            self.config.circle4_center_y,
            self.config.circle4.radius,
            self.config.secondary_edge_band_width,
            self.config.secondary_edge_sensitivity,
        )
        if ok:
            self._set_target_xy("secondary", nx, ny)
            self.config.circle4.radius = nr
            self.last_score = info.get("score", 100.0)
            self._target_scores["secondary"] = self.last_score
            self.last_source_key = "source_secondary_edge"
            self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
            self._sync_all_controls_from_config()
            self._push_history()
        else:
            self.last_score = 0.0
            self.last_status_key = "secondary_edge_fail"
            QMessageBox.warning(self, self.i18n.t("snap_secondary_edge"), self.i18n.t("secondary_edge_fail"))
        self._update_status_labels()

    def _auto_track_if_needed(self) -> None:
        """持续吸附跟踪

        中圈持续吸附使用亮斑中心快速算法；内圈持续吸附使用环形边缘拟合
        为了避免卡顿，不是每帧都跑，而是间隔若干帧执行一次
        """
        if self.current_frame is None or not (self.config.track_middle or self.config.track_inner or self.config.track_secondary):
            return
        if self.config.middle_concentric_with_outer:
            self.config.track_middle = False
            if hasattr(self, "middle_track_check"):
                self.middle_track_check.setChecked(False)
        if self.config.inner_concentric_with_outer:
            self.config.track_inner = False
            if hasattr(self, "inner_track_check"):
                self.inner_track_check.setChecked(False)
        if self.config.secondary_concentric_with_outer:
            self.config.track_secondary = False
            if hasattr(self, "secondary_track_check"):
                self.secondary_track_check.setChecked(False)
        self._frame_counter += 1
        if self._frame_counter % 6 != 0:
            return

        if self.config.track_middle and not self.config.middle_concentric_with_outer:
            ok, nx, ny, nr, info = VisionEngine.snap_outer_edge(
                self.current_frame,
                self.config.circle2_center_x,
                self.config.circle2_center_y,
                self.config.circle2.radius,
                self.config.edge_band_width,
            )
            if ok:
                self._set_target_xy("middle", nx, ny)
                self.config.circle2.radius = int(round(self.config.circle2.radius * 0.8 + nr * 0.2))
                self.last_score = info.get("score", self.last_score)
                self._target_scores["middle"] = self.last_score
                self.last_source_key = "source_middle_tracking"
                self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
                self._push_history()

        if self.config.track_inner and self._frame_counter % 12 == 0:
            ok, nx, ny, nr, info = VisionEngine.snap_outer_edge(
                self.current_frame,
                self.config.circle3_center_x,
                self.config.circle3_center_y,
                self.config.circle3.radius,
                self.config.edge_band_width,
            )
            if ok:
                self._set_target_xy("inner", nx, ny)
                # 半径连续跟踪时只做轻微更新，避免边缘瞬间误识别导致圆圈跳动过大
                self.config.circle3.radius = int(round(self.config.circle3.radius * 0.8 + nr * 0.2))
                self.last_score = info.get("score", self.last_score)
                self._target_scores["inner"] = self.last_score
                self.last_source_key = "source_inner_tracking"
                self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
                self._push_history()

        if self.config.track_secondary and self._frame_counter % 12 == 0:
            ok, nx, ny, nr, info = VisionEngine.snap_secondary_edge(
                self.current_frame,
                self.config.circle4_center_x,
                self.config.circle4_center_y,
                self.config.circle4.radius,
                self.config.secondary_edge_band_width,
                self.config.secondary_edge_sensitivity,
            )
            if ok:
                self._set_target_xy("secondary", nx, ny)
                self.config.circle4.radius = int(round(self.config.circle4.radius * 0.8 + nr * 0.2))
                self.last_score = info.get("score", self.last_score)
                self._target_scores["secondary"] = self.last_score
                self.last_source_key = "source_secondary_tracking"
                self.last_status_key = "adjusting" if self.config.reference_locked else "need_reference"
                self._push_history()

    def _push_history(self) -> None:
        self.detected_xy = self._primary_hud_xy()
        m = VisionEngine.measure(self.config, self.detected_xy)
        self._history["dx"].append(m["dx"])
        self._history["dy"].append(m["dy"])
        self._history["dist"].append(m["dist"])
        self._history["score"].append(self.last_score)
        for values in self._history.values():
            del values[:-240]

    # ------------------------------------------------------------------
    # 配置保存、读取、语言切换
    # ------------------------------------------------------------------
    def save_parameters(self) -> None:
        self.config.language = self.lang_combo.currentText()
        self.config.camera_type = self.camera_type_combo.currentText()
        self.config.camera_id = self._current_camera_id()
        self.config.zwo_dll_path = self.zwo_dll_edit.text().strip()
        self.config.camera_exposure_ms = float(self.exposure_spin.value())
        self.config.camera_iso = int(self.iso_spin.value())
        self.config.camera_gain = int(self.gain_spin.value())
        self.config.camera_auto_exposure = self.auto_exposure_check.isChecked()
        self.config.camera_auto_focus = self.auto_focus_check.isChecked()
        self.config.camera_focus = int(self.focus_spin.value())
        self.config.ui_fps_limit = int(self.ui_fps_spin.value())
        self.config.view_pan_x = int(self.view_pan_x_slider.value())
        self.config.view_pan_y = int(self.view_pan_y_slider.value())
        self.config.middle_concentric_with_outer = bool(self.middle_concentric_check.isChecked())
        self.config.inner_concentric_with_outer = bool(self.inner_concentric_check.isChecked())
        self.config.secondary_concentric_with_outer = bool(self.secondary_concentric_check.isChecked())
        self.config.track_middle = False if self.config.middle_concentric_with_outer else bool(self.middle_track_check.isChecked())
        self.config.track_inner = False if self.config.inner_concentric_with_outer else bool(self.inner_track_check.isChecked())
        self.config.track_secondary = False if self.config.secondary_concentric_with_outer else bool(self.secondary_track_check.isChecked())
        self.config.auto_tracking = bool(self.config.track_middle or self.config.track_inner or self.config.track_secondary)
        if self.config.middle_concentric_with_outer:
            self._apply_middle_concentric_position()
        if self.config.inner_concentric_with_outer:
            self._apply_inner_concentric_position()
        if self.config.secondary_concentric_with_outer:
            self._apply_secondary_concentric_position()
        self.config.active_target = self.active_target
        self.config.circle2_center_x, self.config.circle2_center_y = self.middle_xy
        self.config.circle3_center_x, self.config.circle3_center_y = self.inner_xy
        self.config.circle4_center_x, self.config.circle4_center_y = self.secondary_xy
        self.config_manager.save(self.config)
        self.last_status_key = "saved"
        self._update_status_labels()

    def load_parameters(self) -> None:
        self._cancel_outer_three_point_mode(clear_points=True)
        self.config = self.config_manager.load()
        self.i18n.set_language(self.config.language)
        self.middle_xy = (int(self.config.circle2_center_x), int(self.config.circle2_center_y))
        self.inner_xy = (int(self.config.circle3_center_x), int(self.config.circle3_center_y))
        self.secondary_xy = (int(self.config.circle4_center_x), int(self.config.circle4_center_y))
        self.active_target = self.config.active_target if self.config.active_target in {"middle", "inner", "secondary"} else "middle"
        self.detected_xy = self._active_xy()
        self.last_score = 0.0
        self._target_scores = {"middle": 0.0, "inner": 0.0, "secondary": 0.0}
        self.last_source_key = "source_waiting"
        self.last_status_key = "loaded"
        self._sync_all_controls_from_config()
        self._apply_language()
        self._update_status_labels()

    def change_language(self, lang: str) -> None:
        self.config.language = lang
        self.i18n.set_language(lang)
        self._apply_language()

    # ------------------------------------------------------------------
    # 画面渲染和状态刷新
    # ------------------------------------------------------------------
    def update_image(self, cv_img: np.ndarray) -> None:
        self._render_counter += 1
        # 不复制原始帧，避免高分辨率下每帧额外占用大量内存和 CPU
        # 后续绘制都在 display_frame 上进行，不会污染 current_frame
        self.current_frame = cv_img
        h, w = cv_img.shape[:2]
        if w != self.config.frame_width or h != self.config.frame_height:
            self.config.frame_width = w
            self.config.frame_height = h
            self.config.center_x = float(max(0.0, min(float(w - 1), float(self.config.center_x))))
            self.config.center_y = float(max(0.0, min(float(h - 1), float(self.config.center_y))))
            self.config.circle2_center_x = int(max(0, min(w - 1, self.config.circle2_center_x)))
            self.config.circle2_center_y = int(max(0, min(h - 1, self.config.circle2_center_y)))
            self.config.circle3_center_x = int(max(0, min(w - 1, self.config.circle3_center_x)))
            self.config.circle3_center_y = int(max(0, min(h - 1, self.config.circle3_center_y)))
            self.config.circle4_center_x = int(max(0, min(w - 1, self.config.circle4_center_x)))
            self.config.circle4_center_y = int(max(0, min(h - 1, self.config.circle4_center_y)))
            self.middle_xy = (self.config.circle2_center_x, self.config.circle2_center_y)
            self.inner_xy = (self.config.circle3_center_x, self.config.circle3_center_y)
            self.secondary_xy = (self.config.circle4_center_x, self.config.circle4_center_y)
            self.config.update_offsets_from_center()
            self._sync_offset_sliders()
            self._sync_target_sliders()

        if self.config.middle_concentric_with_outer:
            self._apply_middle_concentric_position(sync_ui=False)
        if self.config.inner_concentric_with_outer:
            self._apply_inner_concentric_position(sync_ui=False)
        if self.config.secondary_concentric_with_outer:
            self._apply_secondary_concentric_position(sync_ui=False)
        self._auto_track_if_needed()
        hud_targets = self._hud_targets()
        self.detected_xy = self._primary_hud_xy()

        # 先把相机画面裁剪/缩放到当前显示控件实际尺寸，再绘制圆圈和 HUD
        # 这样线条和文字不再被 Qt 二次缩放，显示器上会更锐利；
        # HUD 字号也跟随显示器上的实际像素，而不是 CMOS 原始分辨率
        output_size = self._display_output_size(w, h)
        display_frame, view_rect = self._apply_zoom_to_frame(cv_img, output_size)
        VisionEngine.draw_geometry_display(
            display_frame,
            self.config,
            view_rect,
            (w, h),
            self.middle_xy,
            self.inner_xy,
            self.secondary_xy,
            self.active_target,
        )
        VisionEngine.draw_hud(display_frame, self.config, self.i18n, self.detected_xy,
                              self.last_score, self.last_source_key, self.last_status_key,
                              target_metrics=hud_targets)
        # 用户反馈底部 dx/dy/dist/score 曲线实际意义不大，正式界面只保留左上角 HUD 提示

        rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
        # QPixmap.fromImage 会在当前调用中接管/复制图像数据；这里不再先做 QImage.copy，
        # 避免每帧产生两份显示缓冲区rgb 在转换完成前保持有效
        qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888)
        self.video_label.set_frame_pixmap(QPixmap.fromImage(qimg), w, h, view_rect)
        # 状态文本不需要每帧刷新；低频刷新可以减少 PyQt 文本布局开销
        if self._render_counter % 3 == 0:
            self._update_status_labels()

    def _display_output_size(self, frame_w: int, frame_h: int) -> Tuple[int, int]:
        """计算最终要送到 QLabel 的显示图尺寸

        输出尺寸跟随左侧视频控件的实际屏幕尺寸，而不是相机 CMOS 分辨率
        这样 HUD 文字和圆圈线条会直接画在显示器像素上，不会再被 QLabel 二次缩放发虚
        """
        label_w = max(2, int(self.video_label.width()))
        label_h = max(2, int(self.video_label.height()))
        if frame_w <= 0 or frame_h <= 0:
            return label_w, label_h
        aspect = frame_w / max(1.0, float(frame_h))
        out_w = label_w
        out_h = int(round(out_w / aspect))
        if out_h > label_h:
            out_h = label_h
            out_w = int(round(out_h * aspect))
        return max(2, out_w), max(2, out_h)

    def _apply_zoom_to_frame(self, frame: np.ndarray, output_size: Tuple[int, int]) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
        """围绕参考中心裁剪，再缩放到显示器实际输出尺寸"""
        h, w = frame.shape[:2]
        out_w, out_h = output_size
        zoom = max(100, min(400, int(self.config.zoom_percent))) / 100.0

        if zoom <= 1.01:
            view_rect = (0, 0, w, h)
            src = frame
        else:
            crop_w = max(2, int(w / zoom))
            crop_h = max(2, int(h / zoom))

            # 默认围绕外圈参考中心放大用户拖动下方/右侧滑条后，
            # 在参考中心基础上加入 view_pan_x / view_pan_y 偏移
            cx = int(max(0, min(w - 1, self.config.center_x + self.config.view_pan_x)))
            cy = int(max(0, min(h - 1, self.config.center_y + self.config.view_pan_y)))
            x1 = max(0, min(w - crop_w, cx - crop_w // 2))
            y1 = max(0, min(h - crop_h, cy - crop_h // 2))
            view_rect = (x1, y1, crop_w, crop_h)
            src = frame[y1:y1 + crop_h, x1:x1 + crop_w]

        # 图像本身可适度平滑缩放；圆圈、十字线、文字稍后在最终尺寸上重新绘制，保持锐利
        if src.shape[1] == out_w and src.shape[0] == out_h:
            return src.copy(), view_rect
        interpolation = cv2.INTER_AREA if (src.shape[1] > out_w or src.shape[0] > out_h) else cv2.INTER_LINEAR
        shown = cv2.resize(src, (out_w, out_h), interpolation=interpolation)
        return shown, view_rect

    def _update_status_labels(self) -> None:
        t = self.i18n.t
        self.detected_xy = self._primary_hud_xy()
        m = VisionEngine.measure(self.config, self.detected_xy)
        dx, dy, dist = m["dx"], m["dy"], m["dist"]
        self.status_score.setText(f"{t('score')}: {self.last_score:.1f}")
        self.status_dev.setText(f"{t('dev')}: {dist:.2f}")
        self.status_offset.setText(f"{t('offset')}: {dx:+.1f}, {dy:+.1f}")
        self.status_guide.setText(f"{t('guide')}: {VisionEngine.guide_text(self.config, self.i18n, self.detected_xy)}")
        self.status_reference.setText(f"{t('reference')}: {float(self.config.center_x):+.2f}, {float(self.config.center_y):+.2f}")
        if self.last_status_detail:
            self.status_text.setText(f"Status: {t(self.last_status_key)}\n{self.last_status_detail}")
            self.status_text.setWordWrap(True)
        else:
            self.status_text.setText(f"Status: {t(self.last_status_key)}")

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.stop_camera()
        event.accept()
