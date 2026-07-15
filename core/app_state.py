# -*- coding: utf-8 -*-
# 文件说明：全局状态数据模型这里只定义参数结构，不直接操作 UI 或相机
# 设计逻辑：
# 1. center_x / center_y 代表 Circle 1 外圈参考中心，即镜筒边缘拟合得到的机械中心
# 2. 当前检测到的内圈亮斑中心不写在这里，而由 UI 运行时保存，避免把临时检测结果误存为配置
# 3. 所有颜色都使用 OpenCV 的 BGR 顺序，例如绿色是 (0, 255, 0)，不是 RGB
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass
class CircleConfig:
    """单个同心圆的显示参数"""

    enabled: bool = True
    radius: int = 120
    thickness: float = 1.0
    color: Tuple[int, int, int] = (0, 255, 0)  # OpenCV BGR 色彩顺序


@dataclass
class StarConfig:
    """中心星标/十字准星的显示参数"""

    enabled: bool = True
    length: int = 80
    thickness: float = 1.0
    angle: int = 0
    color: Tuple[int, int, int] = (255, 0, 255)  # OpenCV BGR 色彩顺序


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

    # ZWO/ASI 相机参数曝光在 UI 中以毫秒显示，写入 SDK 时会转换为微秒
    # zwo_dll_path 可以为空，程序会自动搜索 ASICamera2.dll；找不到时可在 UI 中手动选择
    camera_exposure_ms: float = 50.0
    # 相机 ISO / 亮度偏置说明：ZWO ASI 相机没有传统相机意义上的 ISO，
    # 本字段在 ZWO 后端映射为 OFFSET/亮度偏置；USB 后端会优先尝试 ISO，失败则尝试亮度
    camera_iso: int = 100
    camera_gain: int = 400
    camera_auto_exposure: bool = False
    # USB 摄像头专用：部分 UVC/DirectShow 摄像头支持电子对焦
    # 物理镜头仍然需要手动旋转；这里用于支持驱动暴露的 Focus 控制项
    camera_auto_focus: bool = True
    camera_focus: int = 0
    zwo_dll_path: str = ""

    # Circle 1 外圈参考中心/零点真实圆心 = 图像中心 + 水平/垂直偏移
    # 光轴调整时，内圈检测亮斑会与这个参考中心比较，生成 dx/dy/dist/Guide
    center_x: int = 640
    center_y: int = 360
    horizontal_offset: int = 0
    vertical_offset: int = 0
    reference_locked: bool = False  # 是否已经点击过“设为零点”

    # 显示缩放100=不放大，200=2倍放大，400=4倍放大
    zoom_percent: int = 100

    # 放大画面的平移偏移，单位是原始相机像素
    # 0 表示裁剪窗口围绕参考中心；正数表示查看参考中心右侧/下方区域
    view_pan_x: int = 0
    view_pan_y: int = 0

    # UI 刷新帧率限制相机曝光时间较长或分辨率较高时，限制 UI 绘制频率可以明显降低卡顿
    ui_fps_limit: int = 20

    # 中圈/内圈的当前检测中心
    # Circle 1 外圈仍然绑定 center_x / center_y；Circle 2/3 分别绑定下面两个中心
    # 这样才能表达真实调节逻辑：外圈由镜筒边缘确定基准，中圈/内圈吸附后再移动到外圈圆心
    circle2_center_x: int = 640
    circle2_center_y: int = 360
    circle3_center_x: int = 640
    circle3_center_y: int = 360
    circle4_center_x: int = 640
    circle4_center_y: int = 360

    # 自动跟踪开关中圈默认跟踪圆形亮斑中心，内圈默认跟踪小圆边缘
    auto_tracking: bool = False
    track_middle: bool = False
    track_inner: bool = False
    track_secondary: bool = False
    active_target: str = "middle"  # middle、inner 或 secondary，决定左上角 Guide 当前显示哪个目标的偏移

    # 与外圈同心模式：启用后，对应圆只作为外圈参考中心上的辅助同心圆显示
    # 此时该圆不参与 Guide 检测，也不允许位置吸附/持续跟踪
    middle_concentric_with_outer: bool = False
    inner_concentric_with_outer: bool = False
    secondary_concentric_with_outer: bool = False

    # 覆盖层对象Circle 1 是外圈参考圆；Circle 2/3 是吸附后跟随各自检测中心的辅助圆
    circle1: CircleConfig | None = None
    circle2: CircleConfig | None = None
    circle3: CircleConfig | None = None
    circle4: CircleConfig | None = None
    star: StarConfig | None = None

    # 自动识别/吸附参数
    snap_roi: int = 80
    snap_threshold: int = 200  # 0 表示使用 Otsu 自动阈值
    edge_band_width: int = 25
    # 副镜边缘通常只有局部弱弧线，单独给它更宽的搜索带宽和更高的弱边缘灵敏度
    # secondary_edge_band_width 只影响“吸附副镜边缘/副镜持续吸附”
    # secondary_edge_sensitivity 越高，越愿意接受低对比边缘；过高可能吸到杂散反光
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
        self.horizontal_offset = int(self.center_x - self.frame_width // 2)
        self.vertical_offset = int(self.center_y - self.frame_height // 2)

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
