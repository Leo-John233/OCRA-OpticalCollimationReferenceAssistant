# -*- coding: utf-8 -*-
"""定义应用配置及覆盖层状态数据模型

``center_x`` 和 ``center_y`` 表示由镜筒边缘拟合得到的外圈机械中心
检测过程中的临时亮斑中心由界面保存，避免误写入持久配置
所有颜色均使用 OpenCV 的 BGR 通道顺序
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .focus_control import FOCUS_MIDPOINT


@dataclass
class CircleConfig:
    """单个同心圆的显示参数"""

    enabled: bool = True
    radius: int = 120
    thickness: float = 1.0
    color: Tuple[int, int, int] = (0, 255, 0)  # OpenCV BGR 通道顺序


@dataclass
class StarConfig:
    """中心星标/十字准星的显示参数"""

    enabled: bool = True
    length: int = 80
    thickness: float = 1.0
    angle: int = 0
    color: Tuple[int, int, int] = (255, 0, 255)  # OpenCV BGR 通道顺序


@dataclass
class AppConfig:
    """整个程序运行时共享的一份配置状态

    UI、视频线程、视觉算法都会读取这里的参数
    修改参数时优先改 AppConfig，再由 ConfigManager 保存到 txt
    """

    # 通用设置
    language: str = "zh"

    # 相机设置
    camera_type: str = "synthetic"  # synthetic=模拟相机，usb=普通USB相机，zwo=振旺ASI，qhy=QHY
    camera_id: int = 0
    frame_width: int = 1280
    frame_height: int = 720

    # ZWO 和 ASI 曝光在界面中以毫秒显示，写入 SDK 时转换为微秒
    # zwo_dll_path 为空时自动搜索 ASICamera2.dll，也可在界面中手动选择
    camera_exposure_ms: float = 50.0
    # ZWO 后端将 ISO 映射为 OFFSET 亮度偏置
    # USB 后端优先设置 ISO，不受支持时改为亮度
    camera_iso: int = 100
    camera_gain: int = 400
    camera_auto_exposure: bool = False
    # 部分 UVC 和 DirectShow 摄像头支持电子对焦
    # 物理镜头仍需手动旋转，此参数仅对应驱动暴露的 Focus 控制项
    camera_auto_focus: bool = True
    # 保存驱动的绝对焦点，默认中点在界面显示为零
    camera_focus: int = FOCUS_MIDPOINT
    zwo_dll_path: str = ""

    # 外圈参考中心等于图像中心加水平和垂直偏移
    # 内圈检测结果与该中心比较后生成 dx、dy、dist 和 Guide
    center_x: float = 640.0
    center_y: float = 360.0
    horizontal_offset: float = 0.0
    vertical_offset: float = 0.0
    reference_locked: bool = False  # 是否已经点击过“设为零点”

    # 显示缩放比例为 100 时不放大，200 时放大 2 倍
    zoom_percent: int = 100

    # 放大画面的平移偏移，单位是原始相机像素
    # 0 表示裁剪窗口围绕参考中心，正数表示查看右侧或下方区域
    view_pan_x: int = 0
    view_pan_y: int = 0

    # 限制界面刷新帧率可缓解长曝光或高分辨率下的卡顿
    ui_fps_limit: int = 20

    # 中圈、内圈和副镜圈的当前检测中心
    # 外圈绑定 center_x 和 center_y，其余圆分别绑定下列中心
    # 外圈由镜筒边缘确定基准，其余圆吸附后再向该基准移动
    circle2_center_x: int = 640
    circle2_center_y: int = 360
    circle3_center_x: int = 640
    circle3_center_y: int = 360
    circle4_center_x: int = 640
    circle4_center_y: int = 360

    # 自动跟踪分别使用中圈亮斑、内圈边缘和副镜边缘
    auto_tracking: bool = False
    track_middle: bool = False
    track_inner: bool = False
    track_secondary: bool = False
    active_target: str = "middle"  # middle、inner 或 secondary，决定左上角 Guide 当前显示哪个目标的偏移

    # 启用与外圈同心模式后，对应圆仅作为参考中心上的辅助圆显示
    # 此时该圆不参与 Guide 检测，也不允许位置吸附/持续跟踪
    middle_concentric_with_outer: bool = False
    inner_concentric_with_outer: bool = False
    secondary_concentric_with_outer: bool = False

    # 覆盖层包含外圈参考圆及跟随各自检测中心的辅助圆
    circle1: CircleConfig | None = None
    circle2: CircleConfig | None = None
    circle3: CircleConfig | None = None
    circle4: CircleConfig | None = None
    star: StarConfig | None = None

    # 自动识别/吸附参数
    snap_roi: int = 80
    snap_threshold: int = 200  # 0 表示使用 Otsu 自动阈值
    edge_band_width: int = 25
    # 副镜边缘通常仅有局部弱弧线，因此使用独立的搜索带宽和灵敏度
    # secondary_edge_band_width 只影响“吸附副镜边缘/副镜持续吸附”
    # 灵敏度越高越容易接受低对比边缘，但过高可能吸附杂散反光
    secondary_edge_band_width: int = 45
    secondary_edge_sensitivity: int = 70
    guide_tolerance: float = 2.0

    def __post_init__(self) -> None:
        """为可变嵌套对象补默认值，避免 dataclass 共用同一个对象"""
        if self.circle1 is None:
            self.circle1 = CircleConfig(True, 173, 1.0, (0, 255, 0))      # 外圈：绿色
        if self.circle2 is None:
            self.circle2 = CircleConfig(True, 68, 1.0, (0, 0, 255))       # 中圈：红色
        if self.circle3 is None:
            self.circle3 = CircleConfig(True, 27, 1.0, (255, 0, 0))       # 内圈：蓝色
        if self.circle4 is None:
            self.circle4 = CircleConfig(True, 45, 1.0, (255, 255, 0))     # 副镜圈：青色
        if self.star is None:
            self.star = StarConfig(True, 105, 1.0, 0, (255, 0, 255))      # 星标：粉色

    def update_center_from_offsets(self) -> None:
        """根据水平/垂直偏移重新计算绝对参考中心坐标"""
        self.center_x = self.frame_width // 2 + self.horizontal_offset
        self.center_y = self.frame_height // 2 + self.vertical_offset

    def update_offsets_from_center(self) -> None:
        """根据绝对参考中心坐标反算相对画面中心的偏移"""
        self.horizontal_offset = float(self.center_x - self.frame_width // 2)
        self.vertical_offset = float(self.center_y - self.frame_height // 2)

    def align_detected_centers_to_reference_if_default(self) -> None:
        """旧配置或首次启动时，让中圈/内圈检测中心先落在外圈参考中心上"""
        if self.circle2_center_x == 640 and self.circle2_center_y == 360:
            self.circle2_center_x = int(self.center_x)
            self.circle2_center_y = int(self.center_y)
        if self.circle3_center_x == 640 and self.circle3_center_y == 360:
            self.circle3_center_x = int(self.center_x)
            self.circle3_center_y = int(self.center_y)
        if self.circle4_center_x == 640 and self.circle4_center_y == 360:
            self.circle4_center_x = int(self.center_x)
            self.circle4_center_y = int(self.center_y)
