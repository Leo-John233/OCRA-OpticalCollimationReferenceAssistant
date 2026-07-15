# -*- coding: utf-8 -*-
# 文件说明：视觉算法模块只负责 OpenCV 绘制、亮斑吸附、外圈边缘拟合，不依赖 PyQt
# 设计逻辑：
# 1. 参考中心由 config.center_x / config.center_y 表示，等同于 OCAL 的“设为零点”
# 2. detected_x / detected_y 是当前检测到的亮斑中心，用它和参考中心计算 dx/dy/dist
# 3. dx/dy 的方向逻辑按 OCAL 截图处理：dx<0 提示 RIGHT，dy<0 提示 DOWN
from __future__ import annotations

import math
from typing import Dict, Iterable, Optional, Tuple

import cv2
import numpy as np

# 启用 OpenCV 内部 SIMD/多线程优化某些环境默认已开启，显式设置可避免被外部库关闭
cv2.setUseOptimized(True)
try:
    cv2.setNumThreads(0)
except Exception:
    pass

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # Pillow 是可选依赖；缺失时退回 OpenCV 英文字体
    Image = ImageDraw = ImageFont = None

from .app_state import AppConfig, CircleConfig


class VisionEngine:
    """纯 OpenCV 视觉算法层，不导入 PyQt

    这里提供三类能力：
    1. 绘制 OCAL 风格的十字线、同心圆、中心星标、检测点和方向箭头
    2. 中心亮斑吸附：适合吸附 OCAL 中心反射亮点
    3. 环形边缘吸附：适合手动粗调外圈后，对外圈圆边缘做最小二乘拟合
    """

    # ------------------------------------------------------------------
    # Unicode 文本绘制：OpenCV 自带 putText 无法稳定显示中文，所以优先用 Pillow
    # ------------------------------------------------------------------
    _font_cache: Dict[Tuple[int, bool], object] = {}

    @staticmethod
    def _find_font_path() -> Optional[str]:
        """寻找常见中文字体Windows 用户通常会命中微软雅黑或黑体"""
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        import os
        for path in candidates:
            if os.path.exists(path):
                return path
        return None

    @staticmethod
    def _get_font(size: int, bold: bool = False):
        """获取 Pillow 字体对象找不到中文字体时退回默认字体"""
        key = (size, bold)
        if key in VisionEngine._font_cache:
            return VisionEngine._font_cache[key]
        if ImageFont is None:
            return None
        font_path = VisionEngine._find_font_path()
        try:
            font = ImageFont.truetype(font_path, size=size) if font_path else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        VisionEngine._font_cache[key] = font
        return font

    @staticmethod
    def _hud_scale(frame: np.ndarray) -> float:
        """根据当前显示帧尺寸自动计算 HUD 缩放比例

        以 1280x720 为基准低分辨率自动缩小，高分辨率自动放大，
        并限制比例范围，避免文字过大遮挡画面或过小看不清
        """
        h, w = frame.shape[:2]
        base = min(w / 1280.0, h / 720.0)
        return float(max(0.72, min(1.55, base)))

    @staticmethod
    def _scaled(value: float, scale: float, min_value: int = 1) -> int:
        """将设计稿尺寸按 HUD 缩放比例转换为整数像素"""
        return max(min_value, int(round(value * scale)))

    @staticmethod
    def _draw_text_block(frame: np.ndarray, lines: Iterable[Tuple[str, Tuple[int, int, int], int, bool]],
                         x: int, y: int, line_gap: int = 28, stroke_width: int = 2) -> None:
        """一次性绘制多行 Unicode 文本，避免 OpenCV 中文乱码

        文字加黑色描边无论画面是白色亮斑、黑色背景还是高噪声，
        左上角 HUD 都能保持清晰
        """
        if Image is None or ImageDraw is None or ImageFont is None:
            # Pillow 不存在时退回 OpenCV中文可能显示为问号，但程序不会崩溃
            for i, (text, color, size, _bold) in enumerate(lines):
                org = (x, y + line_gap * i)
                font_scale = max(0.45, size / 28.0)
                thickness = max(1, int(round(size / 16.0)))
                cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
                cv2.putText(frame, text, org, cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)
            return
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(image)
        for i, (text, color, size, bold) in enumerate(lines):
            b, g, r = color
            font = VisionEngine._get_font(size, bold)
            try:
                draw.text((x, y + line_gap * i), text, fill=(r, g, b), font=font,
                          stroke_width=stroke_width, stroke_fill=(0, 0, 0))
            except TypeError:
                draw.text((x + 1, y + line_gap * i + 1), text, fill=(0, 0, 0), font=font)
                draw.text((x, y + line_gap * i), text, fill=(r, g, b), font=font)
        frame[:] = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)

    # ------------------------------------------------------------------
    # 几何覆盖层：画在原始相机坐标上，缩放/放大前执行
    # ------------------------------------------------------------------
    @staticmethod
    def draw_geometry(frame: np.ndarray, config: AppConfig,
                      middle_xy: Optional[Tuple[int, int]] = None,
                      inner_xy: Optional[Tuple[int, int]] = None,
                      secondary_xy: Optional[Tuple[int, int]] = None,
                      active_target: str = "middle") -> np.ndarray:
        """在原始画面上叠加十字线、三圈和中心星标

        当前版本严格按真实 OCAL 调节逻辑分离三个圆心：
        1. 外圈 Circle 1：绑定 config.center_x / config.center_y，由镜筒/调焦筒外缘拟合得到
        2. 中圈 Circle 2：绑定中圈亮斑边缘识别后的圆心
        3. 内圈 Circle 3：绑定红色小圆边缘识别后的圆心

        调光轴时不是把外圈移动到内圈，而是通过调节主镜/副镜，让中圈和内圈的圆心逐渐移动到外圈参考圆心
        """
        h, w = frame.shape[:2]
        ref_x = int(np.clip(config.center_x, 0, w - 1))
        ref_y = int(np.clip(config.center_y, 0, h - 1))
        reference_center = (ref_x, ref_y)

        if middle_xy is None:
            middle_xy = (int(config.circle2_center_x), int(config.circle2_center_y))
        if inner_xy is None:
            inner_xy = (int(config.circle3_center_x), int(config.circle3_center_y))
        if secondary_xy is None:
            secondary_xy = (int(config.circle4_center_x), int(config.circle4_center_y))
        mid_center = (int(np.clip(middle_xy[0], 0, w - 1)), int(np.clip(middle_xy[1], 0, h - 1)))
        inner_center = (int(np.clip(inner_xy[0], 0, w - 1)), int(np.clip(inner_xy[1], 0, h - 1)))
        secondary_center = (int(np.clip(secondary_xy[0], 0, w - 1)), int(np.clip(secondary_xy[1], 0, h - 1)))

        # 用中心星标的紫色轴线替代原来的黄色十字准线
        # 是否显示、长度、角度、线宽、颜色全部由“中心准星（可选）”控制
        if config.star.enabled:
            VisionEngine._draw_star(
                frame,
                reference_center,
                int(max(1, config.star.length)),
                config.star.angle,
                config.star.color,
                config.star.thickness,
            )

        # 外圈：镜筒/调焦筒边缘参考圆
        VisionEngine._draw_circle(frame, reference_center, config.circle1)

        # 中圈：圆形亮斑边缘启用“与外圈同心”时，中圈只作为外圈参考中心上的辅助圆显示
        if getattr(config, "middle_concentric_with_outer", False):
            mid_center = reference_center
        VisionEngine._draw_circle(frame, mid_center, config.circle2)

        # 内圈：红色小圆边缘启用“与外圈同心”时，内圈只作为外圈参考中心上的辅助圆显示
        if getattr(config, "inner_concentric_with_outer", False):
            inner_center = reference_center
        VisionEngine._draw_circle(frame, inner_center, config.circle3)

        # 副镜圈：做法与内圈一致，可独立吸附副镜边缘，也可设置为与外圈同心的辅助圆
        if getattr(config, "secondary_concentric_with_outer", False):
            secondary_center = reference_center
        VisionEngine._draw_circle(frame, secondary_center, config.circle4)

        # 画出中圈/内圈到外圈参考圆心的偏移线，表达“把检测圆心调到外圈圆心”的过程
        # 只在对应圆启用时显示它的小 X 准星和连接线，避免关闭圆后仍残留提示
        marker_items = []
        if not getattr(config, "middle_concentric_with_outer", False):
            marker_items.append((mid_center, config.circle2.color, bool(config.circle2.enabled)))
        if not getattr(config, "inner_concentric_with_outer", False):
            marker_items.append((inner_center, config.circle3.color, bool(config.circle3.enabled)))
        if not getattr(config, "secondary_concentric_with_outer", False):
            marker_items.append((secondary_center, config.circle4.color, bool(config.circle4.enabled)))
        for center, color, enabled in marker_items:
            if enabled and center != reference_center:
                cv2.line(frame, center, reference_center, color, 1, cv2.LINE_AA)
                cv2.drawMarker(frame, center, color, cv2.MARKER_TILTED_CROSS, 18, 1)

        return frame

    @staticmethod
    def draw_overlay(frame: np.ndarray, config: AppConfig) -> np.ndarray:
        """兼容旧调用：只绘制几何覆盖层"""
        return VisionEngine.draw_geometry(frame, config)

    @staticmethod
    def draw_geometry_display(frame: np.ndarray, config: AppConfig,
                              view_rect: Tuple[int, int, int, int],
                              source_size: Tuple[int, int],
                              middle_xy: Optional[Tuple[int, int]] = None,
                              inner_xy: Optional[Tuple[int, int]] = None,
                              secondary_xy: Optional[Tuple[int, int]] = None,
                              active_target: str = "middle") -> np.ndarray:
        """在最终显示画面坐标上绘制覆盖层

        旧做法是在 CMOS 原始帧上先画圆和文字，再交给 Qt 缩放到显示器尺寸
        这样在 1920x1080、4K 或放大预览时，圆线和 HUD 会被二次缩放，边缘发虚
        这里改成先把相机画面裁剪/缩放到屏幕实际显示尺寸，再把圆、十字线、连接线画在
        这个最终显示图上线宽和 HUD 字号因此跟随显示器像素，而不是 CMOS 分辨率
        """
        disp_h, disp_w = frame.shape[:2]
        view_x, view_y, view_w, view_h = view_rect
        view_w = max(1, int(view_w))
        view_h = max(1, int(view_h))
        sx = disp_w / float(view_w)
        sy = disp_h / float(view_h)
        sr = (sx + sy) * 0.5

        def map_point(x: float, y: float) -> Tuple[int, int]:
            return int(round((float(x) - view_x) * sx)), int(round((float(y) - view_y) * sy))

        def scaled_radius(radius: float) -> int:
            return max(1, int(round(float(radius) * sr)))

        ref = map_point(config.center_x, config.center_y)
        middle_src = middle_xy if middle_xy is not None else (config.circle2_center_x, config.circle2_center_y)
        inner_src = inner_xy if inner_xy is not None else (config.circle3_center_x, config.circle3_center_y)
        secondary_src = secondary_xy if secondary_xy is not None else (config.circle4_center_x, config.circle4_center_y)
        mid = map_point(*middle_src)
        inner = map_point(*inner_src)
        secondary = map_point(*secondary_src)

        # 用中心星标的紫色轴线替代黄色十字准线，并直接按显示器像素绘制到最终显示图层
        # 注意：这里必须受“启用”和“长度”控制，不能无条件贯穿全屏
        if config.star.enabled:
            VisionEngine._draw_star(
                frame,
                ref,
                int(round(max(1, config.star.length) * sr)),
                config.star.angle,
                config.star.color,
                config.star.thickness,
            )

        VisionEngine._draw_circle_float(frame, ref, scaled_radius(config.circle1.radius), config.circle1.color, config.circle1.thickness, config.circle1.enabled)

        if getattr(config, "middle_concentric_with_outer", False):
            mid = ref
        VisionEngine._draw_circle_float(frame, mid, scaled_radius(config.circle2.radius), config.circle2.color, config.circle2.thickness, config.circle2.enabled)

        if getattr(config, "inner_concentric_with_outer", False):
            inner = ref
        VisionEngine._draw_circle_float(frame, inner, scaled_radius(config.circle3.radius), config.circle3.color, config.circle3.thickness, config.circle3.enabled)

        if getattr(config, "secondary_concentric_with_outer", False):
            secondary = ref
        VisionEngine._draw_circle_float(frame, secondary, scaled_radius(config.circle4.radius), config.circle4.color, config.circle4.thickness, config.circle4.enabled)

        marker_items = []
        if not getattr(config, "middle_concentric_with_outer", False):
            marker_items.append((mid, config.circle2.color, bool(config.circle2.enabled)))
        if not getattr(config, "inner_concentric_with_outer", False):
            marker_items.append((inner, config.circle3.color, bool(config.circle3.enabled)))
        if not getattr(config, "secondary_concentric_with_outer", False):
            marker_items.append((secondary, config.circle4.color, bool(config.circle4.enabled)))
        for center, color, enabled in marker_items:
            if enabled and center != ref:
                VisionEngine._draw_line_float(frame, center, ref, color, 1.0)
                cv2.drawMarker(frame, center, color, cv2.MARKER_TILTED_CROSS, 18, 1, cv2.LINE_AA)

        return frame

    @staticmethod
    def _draw_full_frame_star_axes(frame: np.ndarray, center: Tuple[int, int],
                                   angle_deg: int, color: Tuple[int, int, int], thickness: float) -> None:
        """绘制覆盖整个显示画面的两条星标轴线

        用中心星标的颜色、角度和线宽，替代原来的黄色十字准线
        线长按当前画面对角线计算，确保无论窗口尺寸如何，都能贯穿整个视频画面
        """
        h, w = frame.shape[:2]
        cx, cy = int(center[0]), int(center[1])
        half_len = int(math.ceil(math.hypot(w, h)))
        angle = math.radians(angle_deg % 360)
        for a in (angle, angle + math.pi / 2.0):
            dx = math.cos(a) * half_len
            dy = math.sin(a) * half_len
            p1 = (int(round(cx - dx)), int(round(cy - dy)))
            p2 = (int(round(cx + dx)), int(round(cy + dy)))
            VisionEngine._draw_line_float(frame, p1, p2, color, thickness)

    @staticmethod
    def _composite_mask(frame: np.ndarray, x1: int, y1: int, mask: np.ndarray,
                        color: Tuple[int, int, int]) -> None:
        """用灰度 mask 把颜色合成到 frame 上

        这里 mask 是 0-255 的抗锯齿透明度图相比直接用 OpenCV 的整数 thickness，
        这种方式可以稳定表达 0.5、0.7、0.9 等亚像素线宽，保证数值越小线越细
        """
        if mask.size == 0:
            return
        h, w = mask.shape[:2]
        roi = frame[y1:y1 + h, x1:x1 + w]
        if roi.size == 0:
            return
        alpha = (mask.astype(np.float32) / 255.0)[..., None]
        color_arr = np.array(color, dtype=np.float32).reshape(1, 1, 3)
        blended = roi.astype(np.float32) * (1.0 - alpha) + color_arr * alpha
        frame[y1:y1 + h, x1:x1 + w] = np.clip(blended, 0, 255).astype(np.uint8)

    @staticmethod
    def _draw_circle_float(frame: np.ndarray, center: Tuple[int, int], radius: int,
                           color: Tuple[int, int, int], thickness: float, enabled: bool = True) -> None:
        """用屏幕像素线宽绘制圆，支持 0.5 这类细档位

        注意：不能先画 1px 再叠加 2px上一版这样会导致 0.5 反而比 1.0 更粗
        当前版本使用局部超采样 mask，线宽直接等于 thickness 对应的屏幕像素宽度
        """
        if not enabled or radius <= 0:
            return
        h, w = frame.shape[:2]
        cx, cy = int(center[0]), int(center[1])
        r = int(radius)
        t = max(0.35, float(thickness))
        scale = 8
        pad = int(math.ceil(t * 2.0 + 3))
        x1 = max(0, cx - r - pad)
        y1 = max(0, cy - r - pad)
        x2 = min(w, cx + r + pad + 1)
        y2 = min(h, cy + r + pad + 1)
        if x2 <= x1 or y2 <= y1:
            return

        roi_w, roi_h = x2 - x1, y2 - y1
        mask_hi = np.zeros((roi_h * scale, roi_w * scale), dtype=np.uint8)
        c_hi = (int(round((cx - x1) * scale)), int(round((cy - y1) * scale)))
        r_hi = max(1, int(round(r * scale)))
        t_hi = max(1, int(round(t * scale)))
        cv2.circle(mask_hi, c_hi, r_hi, 255, t_hi, lineType=cv2.LINE_AA)
        mask = cv2.resize(mask_hi, (roi_w, roi_h), interpolation=cv2.INTER_AREA)
        VisionEngine._composite_mask(frame, x1, y1, mask, color)

    @staticmethod
    def _draw_line_float(frame: np.ndarray, p1: Tuple[int, int], p2: Tuple[int, int],
                         color: Tuple[int, int, int], thickness: float) -> None:
        """用屏幕像素线宽绘制线段，支持 0.5、0.7 等细档位"""
        h, w = frame.shape[:2]
        x1p, y1p = int(p1[0]), int(p1[1])
        x2p, y2p = int(p2[0]), int(p2[1])
        t = max(0.35, float(thickness))
        scale = 8
        pad = int(math.ceil(t * 2.0 + 4))
        x1 = max(0, min(x1p, x2p) - pad)
        y1 = max(0, min(y1p, y2p) - pad)
        x2 = min(w, max(x1p, x2p) + pad + 1)
        y2 = min(h, max(y1p, y2p) + pad + 1)
        if x2 <= x1 or y2 <= y1:
            return

        roi_w, roi_h = x2 - x1, y2 - y1
        mask_hi = np.zeros((roi_h * scale, roi_w * scale), dtype=np.uint8)
        p1_hi = (int(round((x1p - x1) * scale)), int(round((y1p - y1) * scale)))
        p2_hi = (int(round((x2p - x1) * scale)), int(round((y2p - y1) * scale)))
        t_hi = max(1, int(round(t * scale)))
        cv2.line(mask_hi, p1_hi, p2_hi, 255, t_hi, lineType=cv2.LINE_AA)
        mask = cv2.resize(mask_hi, (roi_w, roi_h), interpolation=cv2.INTER_AREA)
        VisionEngine._composite_mask(frame, x1, y1, mask, color)

    @staticmethod
    def _draw_circle(frame: np.ndarray, center: Tuple[int, int], circle: CircleConfig) -> None:
        """绘制单个圆enabled=False 时不显示旧调用保留"""
        if circle.enabled and circle.radius > 0:
            VisionEngine._draw_circle_float(frame, center, int(circle.radius), circle.color, circle.thickness, circle.enabled)

    @staticmethod
    def _draw_star(frame: np.ndarray, center: Tuple[int, int], length: int, angle_deg: int,
                   color: Tuple[int, int, int], thickness: float) -> None:
        """绘制中心星标angle 用来让十字星旋转，模拟传统 OCAL 设置里的 Star Angle"""
        angle = math.radians(angle_deg % 360)
        vectors = [angle, angle + math.pi / 2]
        for a in vectors:
            dx = int(math.cos(a) * length / 2)
            dy = int(math.sin(a) * length / 2)
            VisionEngine._draw_line_float(frame, (center[0] - dx, center[1] - dy),
                                          (center[0] + dx, center[1] + dy), color, thickness)

    # ------------------------------------------------------------------
    # HUD 和方向提示：画在最终显示图上，放大裁剪后执行
    # ------------------------------------------------------------------
    @staticmethod
    def measure(config: AppConfig, detected_xy: Optional[Tuple[int, int]]) -> Dict[str, float]:
        """计算当前检测中心相对参考中心的 dx/dy/dist"""
        if detected_xy is None:
            return {"dx": 0.0, "dy": 0.0, "dist": 0.0}
        dx = float(detected_xy[0] - config.center_x)
        dy = float(detected_xy[1] - config.center_y)
        return {"dx": dx, "dy": dy, "dist": math.hypot(dx, dy)}

    @staticmethod
    def guide_parts(config: AppConfig, detected_xy: Optional[Tuple[int, int]], i18n) -> Tuple[str, str]:
        """根据 dx/dy 生成水平和垂直方向提示

        方向与截图保持一致：
        dx < 0 表示当前亮斑在参考点左边，需要向 RIGHT 调；
        dy < 0 表示当前亮斑在参考点上方，需要向 DOWN 调
        """
        m = VisionEngine.measure(config, detected_xy)
        tol = max(0.1, config.guide_tolerance)
        dx, dy = m["dx"], m["dy"]
        h = i18n.t("ok") if abs(dx) <= tol else (i18n.t("right") if dx < 0 else i18n.t("left"))
        v = i18n.t("ok") if abs(dy) <= tol else (i18n.t("down") if dy < 0 else i18n.t("up"))
        return h, v

    @staticmethod
    def guide_text(config: AppConfig, i18n, detected_xy: Optional[Tuple[int, int]] = None) -> str:
        """生成类似 OCAL 状态栏中的 Guide 文本"""
        h, v = VisionEngine.guide_parts(config, detected_xy, i18n)
        return f"{h} / {v}"

    @staticmethod
    def _target_display_name(i18n, item: dict) -> str:
        """根据 HUD 目标字典返回用户可读的目标名称"""
        if "name_key" in item:
            return i18n.t(item["name_key"])
        if item.get("kind") == "inner":
            return i18n.t("hud_target_inner")
        if item.get("kind") == "secondary":
            return i18n.t("hud_target_secondary")
        if item.get("kind") == "middle":
            return i18n.t("hud_target_middle")
        return i18n.t(item.get("source_key", "source_waiting"))

    @staticmethod
    def _compact_metric_line(config: AppConfig, i18n, item: dict) -> Tuple[str, str, float, float, float]:
        """生成一行紧凑的目标偏移文本"""
        name = VisionEngine._target_display_name(i18n, item)
        xy = item.get("xy")
        m = VisionEngine.measure(config, xy)
        guide = VisionEngine.guide_text(config, i18n, xy)
        px = i18n.t("hud_px")
        text = (
            f"{name}: dx {m['dx']:+.1f}{px}, "
            f"dy {m['dy']:+.1f}{px}, "
            f"dist {m['dist']:.1f}{px}"
        )
        return text, guide, m["dx"], m["dy"], m["dist"]

    @staticmethod
    def draw_hud(frame: np.ndarray, config: AppConfig, i18n,
                 detected_xy: Optional[Tuple[int, int]], score: float,
                 source_key: str, status_key: str,
                 target_metrics: Optional[list[dict]] = None) -> np.ndarray:
        """绘制左上角信息块和方向提示

        新逻辑：HUD 的“检测目标”和其下方 dx/dy/dist/Guide 必须跟随“持续吸附”勾选的圆
        - 只勾选中圈持续吸附：显示中圈数据
        - 只勾选内圈持续吸附：显示内圈数据
        - 中圈和内圈都勾选：同时显示两组数据，不再用单一目标覆盖另一组
        - 没有勾选持续吸附：保持原来的手动目标数据
        """
        targets = list(target_metrics or [])
        if not targets:
            targets = [{
                "kind": "single",
                "name_key": "hud_target_current",
                "source_key": source_key,
                "xy": detected_xy,
                "score": score,
            }]

        tol = max(0.1, config.guide_tolerance)
        measurements = [VisionEngine.measure(config, item.get("xy")) for item in targets]
        # 同时显示中圈和内圈时，整体状态只有在两者都进容差后才显示已对准
        all_aligned = bool(targets) and config.reference_locked and all(m["dist"] <= tol for m in measurements)
        status_text = i18n.t("within_tolerance") if all_aligned else i18n.t(status_key)

        scale = VisionEngine._hud_scale(frame)
        # 多目标会多显示几行，自动略微压缩字号，避免遮挡画面
        multi = len(targets) > 1
        title_size = VisionEngine._scaled(26, scale, 18)
        normal_size = VisionEngine._scaled(19 if multi else 20, scale, 13)
        score_size = VisionEngine._scaled(21 if multi else 22, scale, 14)
        margin_x = VisionEngine._scaled(18, scale, 10)
        margin_y = VisionEngine._scaled(12, scale, 8)
        line_gap = VisionEngine._scaled(25 if multi else 27, scale, 18)
        stroke = VisionEngine._scaled(2, scale, 1)

        ref_text = i18n.t("hud_reference_locked") if config.reference_locked else i18n.t("hud_reference_unlocked")
        lines = [
            (i18n.t("app_title_short"), (255, 255, 255), title_size, True),
            (f"{i18n.t('hud_reference')}: {ref_text}", (255, 255, 255), normal_size, True),
        ]

        if len(targets) == 1:
            item = targets[0]
            xy = item.get("xy")
            local_score = float(item.get("score", score) or 0.0)
            m = VisionEngine.measure(config, xy)
            guide = VisionEngine.guide_text(config, i18n, xy)
            confidence = i18n.t("confidence_high") if local_score >= 80 else (i18n.t("confidence_mid") if local_score >= 50 else i18n.t("confidence_low"))
            px = i18n.t("hud_px")
            lines.extend([
                (f"{i18n.t('hud_source')}: {VisionEngine._target_display_name(i18n, item)}", (255, 255, 255), normal_size, False),
                (f"{i18n.t('hud_confidence')}: {confidence} ({local_score:.0f})", (255, 255, 255), normal_size, False),
                (f"{i18n.t('hud_score')}: {local_score:.1f} / 100", (0, 220, 255), score_size, True),
                (f"{i18n.t('hud_dx')}: {m['dx']:+.1f} {px}", (255, 255, 0), normal_size, True),
                (f"{i18n.t('hud_dy')}: {m['dy']:+.1f} {px}", (255, 255, 0), normal_size, True),
                (f"{i18n.t('hud_dist')}: {m['dist']:.1f} {px}", (255, 255, 0), normal_size, True),
                (f"{i18n.t('hud_guide')}: {guide}", (255, 255, 255), normal_size, False),
            ])
        else:
            target_names = " + ".join(VisionEngine._target_display_name(i18n, item) for item in targets)
            lines.append((f"{i18n.t('hud_source')}: {target_names}", (255, 255, 255), normal_size, True))
            # 两个圆同时持续吸附时，将中圈/内圈分成两组同屏显示
            for item in targets:
                metric_text, guide, _dx, _dy, dist = VisionEngine._compact_metric_line(config, i18n, item)
                color = (0, 220, 0) if dist <= tol and config.reference_locked else (255, 255, 0)
                lines.append((metric_text, color, normal_size, True))
                lines.append((f"{VisionEngine._target_display_name(i18n, item)} {i18n.t('hud_guide')}: {guide}", (255, 255, 255), normal_size, False))

        lines.append((f"{i18n.t('hud_status')}: {status_text}", (0, 0, 255) if not all_aligned else (0, 220, 0), normal_size, True))
        VisionEngine._draw_text_block(frame, lines, margin_x, margin_y, line_gap, stroke)

        # 单目标时保留 OCAL 风格的大方向箭头双目标可能出现方向冲突，
        # 此时只在 HUD 中分别给出中圈/内圈文本建议，避免大箭头误导用户
        if len(targets) == 1 and targets[0].get("xy") is not None:
            m = VisionEngine.measure(config, targets[0].get("xy"))
            VisionEngine._draw_direction_arrows(frame, m["dx"], m["dy"], tol, i18n)
        return frame

    @staticmethod
    def _draw_direction_arrows(frame: np.ndarray, dx: float, dy: float, tol: float, i18n) -> None:
        """在画面中绘制类似 OCAL 的黄色方向提示框和箭头"""
        h, w = frame.shape[:2]
        yellow = (0, 255, 255)
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = VisionEngine._hud_scale(frame)
        box_w = VisionEngine._scaled(112, scale, 82)
        box_h = VisionEngine._scaled(42, scale, 30)
        text_scale = max(0.58, min(1.18, 0.86 * scale))
        text_thick = VisionEngine._scaled(2, scale, 1)
        line_thick = VisionEngine._scaled(3, scale, 2)
        rect_thick = VisionEngine._scaled(2, scale, 1)
        pad = VisionEngine._scaled(8, scale, 5)
        edge_pad = VisionEngine._scaled(20, scale, 12)
        text_y = VisionEngine._scaled(29, scale, 21)

        if abs(dx) > tol:
            label = i18n.t("right_short") if dx < 0 else i18n.t("left_short")
            bx = int(w * 0.78) if dx < 0 else int(w * 0.08)
            by = int(h * 0.50)
            cv2.rectangle(frame, (bx, by), (bx + box_w, by + box_h), yellow, rect_thick)
            cv2.putText(frame, label, (bx + pad, by + text_y), font, text_scale, (0, 0, 0), text_thick + 2, cv2.LINE_AA)
            cv2.putText(frame, label, (bx + pad, by + text_y), font, text_scale, yellow, text_thick, cv2.LINE_AA)
            if dx < 0:
                cv2.arrowedLine(frame, (bx + box_w + pad, by + box_h // 2), (w - edge_pad, by + box_h // 2), yellow, line_thick, tipLength=0.18)
            else:
                cv2.arrowedLine(frame, (bx - pad, by + box_h // 2), (edge_pad, by + box_h // 2), yellow, line_thick, tipLength=0.18)

        if abs(dy) > tol:
            label = i18n.t("down_short") if dy < 0 else i18n.t("up_short")
            v_box_w = VisionEngine._scaled(118, scale, 86)
            bx = int(w * 0.47)
            by = int(h * 0.78) if dy < 0 else int(h * 0.08)
            cv2.rectangle(frame, (bx, by), (bx + v_box_w, by + box_h), yellow, rect_thick)
            cv2.putText(frame, label, (bx + pad, by + text_y), font, text_scale, (0, 0, 0), text_thick + 2, cv2.LINE_AA)
            cv2.putText(frame, label, (bx + pad, by + text_y), font, text_scale, yellow, text_thick, cv2.LINE_AA)
            cx = bx + v_box_w // 2
            if dy < 0:
                cv2.arrowedLine(frame, (cx, by + box_h + pad), (cx, h - edge_pad), yellow, line_thick, tipLength=0.18)
            else:
                cv2.arrowedLine(frame, (cx, by - pad), (cx, edge_pad), yellow, line_thick, tipLength=0.18)

    @staticmethod
    def draw_history_plot(frame: np.ndarray, history: Dict[str, Iterable[float]]) -> np.ndarray:
        """在画面底部绘制 dx/dy/dist/score 的简易曲线

        这不是完整的科学绘图控件，而是一个轻量叠加层，用来复刻 OCAL 底部趋势线的核心效果
        """
        h, w = frame.shape[:2]
        plot_h = max(92, h // 7)
        x0, y0 = 8, h - plot_h - 8
        x1, y1 = w - 8, h - 8
        overlay = frame.copy()
        cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.58, frame, 0.42, 0, frame)
        cv2.rectangle(frame, (x0, y0), (x1, y1), (70, 70, 70), 1)
        mid_y = (y0 + y1) // 2
        cv2.line(frame, (x0, mid_y), (x1, mid_y), (55, 55, 55), 1)

        series = [
            ("dx", (255, 255, 0), -80.0, 80.0),
            ("dy", (0, 255, 0), -80.0, 80.0),
            ("dist", (0, 180, 255), 0.0, 160.0),
            ("score", (0, 220, 255), 0.0, 100.0),
        ]
        for idx, (name, color, vmin, vmax) in enumerate(series):
            values = list(history.get(name, []))[-240:]
            if len(values) >= 2:
                pts = []
                for i, val in enumerate(values):
                    px = int(x0 + i / max(1, len(values) - 1) * (x1 - x0))
                    v = max(vmin, min(vmax, float(val)))
                    py = int(y1 - (v - vmin) / max(1e-6, vmax - vmin) * (y1 - y0))
                    pts.append((px, py))
                cv2.polylines(frame, [np.array(pts, dtype=np.int32)], False, color, 1, cv2.LINE_AA)
            cv2.putText(frame, name, (x0 + 10 + idx * 80, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.46, color, 1, cv2.LINE_AA)
        return frame

    # ------------------------------------------------------------------
    # 视觉识别算法
    # ------------------------------------------------------------------
    @staticmethod
    def snap_bright_center(frame: np.ndarray, current_cx: int, current_cy: int,
                           roi_size: int = 80, threshold: int = 200) -> Tuple[bool, int, int, Dict[str, float]]:
        """在当前圆心附近的 ROI 中快速寻找中心亮斑，并返回新的圆心坐标

        性能优化点：
        1. 只处理用户给定的局部 ROI，不扫描整张图
        2. 固定阈值时跳过高斯模糊，减少每次自动跟踪的 CPU 开销
        3. 用 connectedComponentsWithStats 替代 findContours，组件统计更直接，适合亮斑分割

        threshold > 0：使用固定阈值
        threshold <= 0：使用 Otsu 自动阈值
        返回值中的 info 会包含 score 和 area，方便 UI 显示识别质量
        """
        h, w = frame.shape[:2]
        roi_size = int(max(6, min(roi_size, max(w, h))))
        x1 = max(0, int(current_cx - roi_size))
        x2 = min(w, int(current_cx + roi_size))
        y1 = max(0, int(current_cy - roi_size))
        y2 = min(h, int(current_cy + roi_size))
        if x2 <= x1 or y2 <= y1:
            return False, current_cx, current_cy, {"score": 0.0, "area": 0.0}

        roi = frame[y1:y2, x1:x2]
        # ROI 很小时 cvtColor 开销可接受；如果上游给的是灰度图，也兼容处理
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if roi.ndim == 3 else roi

        if threshold <= 0:
            # Otsu 对噪声敏感，所以只在自动阈值模式下做轻量模糊
            work = cv2.GaussianBlur(gray, (3, 3), 0)
            _, mask = cv2.threshold(work, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            _, mask = cv2.threshold(gray, int(threshold), 255, cv2.THRESH_BINARY)

        area_total = float(cv2.countNonZero(mask))
        if area_total < 3:
            return False, current_cx, current_cy, {"score": 0.0, "area": 0.0}

        # 快速路径：绝大多数 OCAL 场景中 ROI 内只有一个主要亮斑，直接用 moments 最快
        # 如果亮斑面积异常大，或者质心离搜索中心太远，再进入 connected components 兜底排除杂散反光
        M = cv2.moments(mask, binaryImage=True)
        roi_center_x = (x2 - x1) / 2.0
        roi_center_y = (y2 - y1) / 2.0
        lx = M["m10"] / M["m00"] if M["m00"] else roi_center_x
        ly = M["m01"] / M["m00"] if M["m00"] else roi_center_y
        needs_component_check = area_total > mask.size * 0.55 or math.hypot(float(lx) - roi_center_x, float(ly) - roi_center_y) > roi_size * 0.75

        if needs_component_check:
            num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
            if num <= 1:
                return False, current_cx, current_cy, {"score": 0.0, "area": 0.0}
            best_idx = -1
            best_rank = -1e18
            for idx in range(1, num):
                area = float(stats[idx, cv2.CC_STAT_AREA])
                if area < 3:
                    continue
                cx_i, cy_i = centroids[idx]
                distance_penalty = math.hypot(float(cx_i) - roi_center_x, float(cy_i) - roi_center_y)
                rank = area - distance_penalty * 0.65
                if rank > best_rank:
                    best_idx = idx
                    best_rank = rank
            if best_idx < 0:
                return False, current_cx, current_cy, {"score": 0.0, "area": 0.0}
            lx, ly = centroids[best_idx]
            area_total = float(stats[best_idx, cv2.CC_STAT_AREA])

        nx = int(round(x1 + float(lx)))
        ny = int(round(y1 + float(ly)))
        # score 表示本次吸附可信度，不等同于光轴是否已经调准
        score = max(0.0, min(100.0, 100.0 - math.hypot(nx - current_cx, ny - current_cy) / max(1, roi_size) * 35.0))
        return True, nx, ny, {"score": score, "area": area_total}

    @staticmethod
    def _circle_from_three_points(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray):
        """由三个非共线点生成圆；几何退化时返回 None"""
        ax, ay = float(p1[0]), float(p1[1])
        bx, by = float(p2[0]), float(p2[1])
        cx, cy = float(p3[0]), float(p3[1])
        det = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        side_scale = max(
            (ax - bx) ** 2 + (ay - by) ** 2,
            (ax - cx) ** 2 + (ay - cy) ** 2,
            (bx - cx) ** 2 + (by - cy) ** 2,
            1.0,
        )
        # 相对三角形面积过小意味着三点近共线，得到的圆心会极度不稳定
        if abs(det) / side_scale < 1e-3:
            return None
        ux = (
            (ax * ax + ay * ay) * (by - cy)
            + (bx * bx + by * by) * (cy - ay)
            + (cx * cx + cy * cy) * (ay - by)
        ) / det
        uy = (
            (ax * ax + ay * ay) * (cx - bx)
            + (bx * bx + by * by) * (ax - cx)
            + (cx * cx + cy * cy) * (bx - ax)
        ) / det
        rr = math.hypot(ux - ax, uy - ay)
        if not (math.isfinite(ux) and math.isfinite(uy) and math.isfinite(rr) and rr > 1.0):
            return None
        return ux, uy, rr

    @staticmethod
    def _circle_angular_coverage(points: np.ndarray, cx: float, cy: float) -> float:
        """返回边缘点围绕圆心覆盖的角度，单位为度"""
        if points.shape[0] < 3:
            return 0.0
        angles = np.mod(np.arctan2(points[:, 1] - cy, points[:, 0] - cx), 2.0 * math.pi)
        angles = np.sort(angles)
        gaps = np.diff(np.concatenate([angles, angles[:1] + 2.0 * math.pi]))
        largest_gap = float(np.max(gaps)) if gaps.size else 2.0 * math.pi
        return float(max(0.0, min(360.0, math.degrees(2.0 * math.pi - largest_gap))))

    @staticmethod
    def _normalized_algebraic_circle_fit(points: np.ndarray, max_condition: float = 80.0):
        """归一化代数圆拟合，并返回设计矩阵条件数

        先平移、按 RMS 距离缩放后再求解，避免高分辨率图像坐标值过大导致
        条件数被坐标量纲污染条件数只用于识别退化几何，不负责剔除离群点
        """
        pts = np.asarray(points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 2 or pts.shape[0] < 3:
            return None
        finite = np.isfinite(pts).all(axis=1)
        pts = pts[finite]
        if pts.shape[0] < 3:
            return None
        mean = pts.mean(axis=0)
        centered = pts - mean
        scale = float(np.sqrt(np.mean(np.sum(centered * centered, axis=1))))
        if not math.isfinite(scale) or scale < 1e-6:
            return None
        q = centered / scale
        a = np.column_stack((q[:, 0], q[:, 1], np.ones(q.shape[0], dtype=np.float64)))
        b = -(q[:, 0] ** 2 + q[:, 1] ** 2)
        try:
            singular = np.linalg.svd(a, compute_uv=False)
            if singular.size < 3 or singular[-1] <= 1e-12:
                return None
            condition = float(singular[0] / singular[-1])
            if not math.isfinite(condition) or condition > float(max_condition):
                return None
            sol, *_ = np.linalg.lstsq(a, b, rcond=None)
        except np.linalg.LinAlgError:
            return None
        aa, bb, cc = [float(v) for v in sol]
        qx = -aa / 2.0
        qy = -bb / 2.0
        r2 = (aa * aa + bb * bb) / 4.0 - cc
        if not math.isfinite(r2) or r2 <= 1e-10:
            return None
        cx = float(mean[0] + qx * scale)
        cy = float(mean[1] + qy * scale)
        rr = float(math.sqrt(r2) * scale)
        return cx, cy, rr, condition

    @staticmethod
    def _ransac_circle_seed(points: np.ndarray, prior: Tuple[float, float, float],
                            band_width: int, iterations: int = 220):
        """用轻量 RANSAC 从大量候选点中寻找主圆，返回圆和内点掩码"""
        pts = np.asarray(points, dtype=np.float64)
        n = int(pts.shape[0])
        if n < 24:
            return None
        prior_cx, prior_cy, prior_r = [float(v) for v in prior]
        tolerance = max(2.0, float(band_width) * 0.28)
        center_limit = max(float(band_width) * 2.4, abs(prior_r) * 0.10, 12.0)
        radius_limit = max(float(band_width) * 2.2, abs(prior_r) * 0.10, 10.0)
        rng = np.random.default_rng(0x0CA1 + n)
        best = None
        best_mask = None
        best_rank = -1e18
        # 点数很大时无需无限增加迭代；本流程只在第三次按钮或单次吸附时运行
        total_iterations = int(max(100, min(320, iterations)))
        for _ in range(total_iterations):
            ids = rng.choice(n, size=3, replace=False)
            candidate = VisionEngine._circle_from_three_points(pts[ids[0]], pts[ids[1]], pts[ids[2]])
            if candidate is None:
                continue
            cx, cy, rr = candidate
            if math.hypot(cx - prior_cx, cy - prior_cy) > center_limit:
                continue
            if abs(rr - prior_r) > radius_limit:
                continue
            residual = np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - rr)
            mask = residual <= tolerance
            count = int(mask.sum())
            if count < 24:
                continue
            med = float(np.median(residual[mask]))
            coverage = VisionEngine._circle_angular_coverage(pts[mask], cx, cy)
            # 内点数是主项，同时鼓励更宽角度覆盖、惩罚较大残差
            rank = float(count) + coverage * 0.18 - med * 10.0
            if rank > best_rank:
                best_rank = rank
                best = (float(cx), float(cy), float(rr))
                best_mask = mask
        if best is None or best_mask is None:
            return None
        return best, best_mask

    @staticmethod
    def _geometric_circle_irls(points: np.ndarray, initial: Tuple[float, float, float],
                               band_width: int, max_iterations: int = 24,
                               use_huber: bool = True):
        """以几何径向残差为目标精修圆参数

        use_huber=True 时执行 Huber-IRLS 抗离群精修；False 时执行普通几何
        最小二乘，在高斯径向误差假设下等价于最大似然估计
        """
        pts = np.asarray(points, dtype=np.float64)
        cx, cy, rr = [float(v) for v in initial]
        jac_condition = 999999.0
        for _ in range(max_iterations):
            dx = pts[:, 0] - cx
            dy = pts[:, 1] - cy
            dist = np.hypot(dx, dy)
            valid = dist > 1e-8
            if int(valid.sum()) < 24:
                return None
            residual = dist - rr
            center = float(np.median(residual[valid]))
            mad = float(np.median(np.abs(residual[valid] - center)))
            sigma = max(0.25, 1.4826 * mad)
            huber_delta = max(1.25, min(float(band_width) * 0.48, 1.5 * sigma + 0.5))
            abs_res = np.abs(residual)
            weights = np.ones_like(abs_res)
            if use_huber:
                far = abs_res > huber_delta
                weights[far] = huber_delta / np.maximum(abs_res[far], 1e-9)
            weights[~valid] = 0.0

            # residual = hypot(x-cx, y-cy) - r
            jac = np.column_stack((-dx / np.maximum(dist, 1e-9), -dy / np.maximum(dist, 1e-9), -np.ones_like(dist)))
            sw = np.sqrt(weights)
            jw = jac * sw[:, None]
            rw = residual * sw
            try:
                singular = np.linalg.svd(jw, compute_uv=False)
                if singular.size < 3 or singular[-1] <= 1e-10:
                    return None
                jac_condition = float(singular[0] / singular[-1])
                # Jacobian 病态说明点集中在很短圆弧，即便残差很小，圆心也不可靠
                if not math.isfinite(jac_condition) or jac_condition > 250.0:
                    return None
                step, *_ = np.linalg.lstsq(jw, -rw, rcond=None)
            except np.linalg.LinAlgError:
                return None
            step = np.asarray(step, dtype=np.float64)
            # 限制单次步长，避免错误初值造成牛顿步跳到远处
            max_center_step = max(2.0, float(band_width) * 0.75)
            center_norm = float(np.hypot(step[0], step[1]))
            if center_norm > max_center_step:
                step[:2] *= max_center_step / center_norm
            step[2] = float(np.clip(step[2], -max_center_step, max_center_step))
            cx += float(step[0])
            cy += float(step[1])
            rr += float(step[2])
            if rr <= 1.0 or not (math.isfinite(cx) and math.isfinite(cy) and math.isfinite(rr)):
                return None
            if float(np.linalg.norm(step)) < 1e-4:
                break
        return float(cx), float(cy), float(rr), float(jac_condition)

    @staticmethod
    def fit_circle_points_robust(points: np.ndarray, prior_cx: float, prior_cy: float,
                                 prior_r: float, band_width: int = 25,
                                 min_points: int = 24, min_coverage_deg: float = 100.0,
                                 use_ransac: bool = True):
        """对任意数量边缘点执行鲁棒几何圆拟合

        流程：先验径向粗筛 -> RANSAC 主圆 -> Huber-IRLS 几何精修 -> MAD 内点筛选
        -> 条件数和角度覆盖退化检查返回结果字典；失败时 ok=False 并给出 reason
        """
        pts = np.asarray(points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 2:
            return {"ok": False, "reason": "invalid_shape", "points": 0}
        pts = pts[np.isfinite(pts).all(axis=1)]
        if pts.shape[0] < int(min_points):
            return {"ok": False, "reason": "too_few_points", "points": int(pts.shape[0])}

        band_width = int(max(6, band_width))
        prior = (float(prior_cx), float(prior_cy), float(prior_r))
        prior_res = np.abs(np.hypot(pts[:, 0] - prior[0], pts[:, 1] - prior[1]) - prior[2])
        coarse_limit = max(10.0, float(band_width) * 1.8)
        coarse = prior_res <= coarse_limit
        if int(coarse.sum()) >= int(min_points):
            pts = pts[coarse]

        # 半像素量化去重，防止三次静态画面采到完全相同的点后被重复加权
        quantized = np.round(pts * 2.0).astype(np.int64)
        _, unique_idx = np.unique(quantized, axis=0, return_index=True)
        pts = pts[np.sort(unique_idx)]
        if pts.shape[0] < int(min_points):
            return {"ok": False, "reason": "too_few_unique_points", "points": int(pts.shape[0])}

        algebraic = VisionEngine._normalized_algebraic_circle_fit(pts, max_condition=80.0)
        algebraic_initial = prior if algebraic is None else algebraic[:3]
        seed_points = pts
        initial = algebraic_initial
        ransac_inliers = None
        if use_ransac:
            ransac = VisionEngine._ransac_circle_seed(pts, prior, band_width)
            if ransac is not None:
                initial, ransac_inliers = ransac
                if int(ransac_inliers.sum()) >= int(min_points):
                    seed_points = pts[ransac_inliers]

        refined = VisionEngine._geometric_circle_irls(seed_points, initial, band_width)
        if refined is None:
            return {"ok": False, "reason": "ill_conditioned_jacobian", "points": int(seed_points.shape[0])}
        cx, cy, rr, jac_condition = refined

        # 在全部候选点上按最终圆重新做 MAD 点级排异
        all_residual = np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - rr)
        med = float(np.median(all_residual))
        mad = float(np.median(np.abs(all_residual - med)))
        sigma = max(0.25, 1.4826 * mad)
        inlier_limit = max(1.75, min(float(band_width) * 0.58, med + 3.2 * sigma + 0.5))
        inlier_mask = all_residual <= inlier_limit
        inliers = pts[inlier_mask]
        if inliers.shape[0] < int(min_points):
            return {"ok": False, "reason": "too_few_inliers", "points": int(inliers.shape[0])}

        # 对已通过 RANSAC、Huber 和 MAD 清洗的最终内点执行普通几何最小二乘
        # 在径向误差近似独立高斯分布时，这一步就是圆心/半径的最大似然估计
        second = VisionEngine._geometric_circle_irls(
            inliers, (cx, cy, rr), band_width, max_iterations=16, use_huber=False
        )
        if second is None:
            return {"ok": False, "reason": "final_refine_failed", "points": int(inliers.shape[0])}
        cx, cy, rr, jac_condition = second
        final_residual = np.abs(np.hypot(inliers[:, 0] - cx, inliers[:, 1] - cy) - rr)
        rmse = float(np.sqrt(np.mean(final_residual ** 2)))
        median_residual = float(np.median(final_residual))

        algebraic_final = VisionEngine._normalized_algebraic_circle_fit(inliers, max_condition=80.0)
        if algebraic_final is None:
            return {"ok": False, "reason": "ill_conditioned_design", "points": int(inliers.shape[0])}
        design_condition = float(algebraic_final[3])
        coverage = VisionEngine._circle_angular_coverage(inliers, cx, cy)
        if coverage < float(min_coverage_deg):
            return {
                "ok": False,
                "reason": "insufficient_angular_coverage",
                "points": int(inliers.shape[0]),
                "coverage": float(coverage),
                "condition_number": design_condition,
            }

        score = 100.0 - median_residual * 8.0 - max(0.0, 120.0 - coverage) * 0.08
        score += min(10.0, inliers.shape[0] / 100.0)
        score = float(max(0.0, min(100.0, score)))
        return {
            "ok": True,
            "cx": float(cx),
            "cy": float(cy),
            "radius": float(rr),
            "score": score,
            "points": int(inliers.shape[0]),
            "candidate_points": int(pts.shape[0]),
            "inlier_points": inliers.astype(np.float32),
            "residual": median_residual,
            "rmse": rmse,
            "coverage": float(coverage),
            "condition_number": design_condition,
            "jacobian_condition": float(jac_condition),
            "inlier_limit": float(inlier_limit),
            "ransac_used": bool(ransac_inliers is not None),
        }

    @staticmethod
    def snap_outer_edge(frame: np.ndarray, current_cx: int, current_cy: int, radius: int,
                        band_width: int = 25) -> Tuple[bool, int, int, int, Dict[str, object]]:
        """采集大量外圈边缘点，并执行 RANSAC + Huber 几何圆拟合

        每次按钮点击都返回本轮最终内点，供第三次点击时合并所有有效点进行联合拟合
        条件数只负责拒绝退化几何；异常点由 RANSAC、MAD 和 Huber 权重处理
        """
        if radius <= 5:
            return False, current_cx, current_cy, radius, {
                "score": 0.0, "points": 0.0, "mode": 0.0, "reason": "invalid_radius"
            }

        h, w = frame.shape[:2]
        current_cx = int(current_cx)
        current_cy = int(current_cy)
        radius = int(radius)
        band_width = int(max(6, band_width))
        gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame

        def run_fit(x: np.ndarray, y: np.ndarray, mode: float, min_coverage: float):
            pts = np.column_stack((x, y)).astype(np.float64)
            result = VisionEngine.fit_circle_points_robust(
                pts,
                current_cx,
                current_cy,
                radius,
                band_width=band_width,
                min_points=24,
                min_coverage_deg=min_coverage,
                use_ransac=True,
            )
            if not result.get("ok", False):
                result = dict(result)
                result.update({"score": 0.0, "mode": mode})
                return None, result
            result = dict(result)
            result["mode"] = mode
            return (
                int(round(float(result["cx"]))),
                int(round(float(result["cy"]))),
                int(round(float(result["radius"]))),
            ), result

        # -------------------------
        # 方案 A：径向梯度采样
        # -------------------------
        r_min = max(4, int(radius - band_width))
        r_max = min(int(max(w, h) * 1.2), int(radius + band_width))
        radial_failure = {"reason": "no_radial_points", "score": 0.0, "points": 0, "mode": 1.0}
        if r_max > r_min + 4:
            radii = np.arange(r_min, r_max + 1, dtype=np.float32)
            angle_count = int(np.clip(radius * 2.2, 180, 960))
            angles = np.linspace(0.0, 2.0 * math.pi, angle_count, endpoint=False, dtype=np.float32)
            cos_a = np.cos(angles)[:, None]
            sin_a = np.sin(angles)[:, None]
            map_x = (float(current_cx) + cos_a * radii[None, :]).astype(np.float32)
            map_y = (float(current_cy) + sin_a * radii[None, :]).astype(np.float32)
            valid = (map_x >= 0) & (map_x <= w - 1) & (map_y >= 0) & (map_y <= h - 1)
            if np.any(valid):
                samples = cv2.remap(
                    gray_full, map_x, map_y, cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=0,
                ).astype(np.float32)
                if samples.shape[1] >= 5:
                    samples = cv2.blur(samples, (5, 1))
                grad = np.abs(np.diff(samples, axis=1))
                valid_grad = valid[:, 1:] & valid[:, :-1]
                grad[~valid_grad] = 0.0
                best_idx = np.argmax(grad, axis=1)
                best_val = grad[np.arange(grad.shape[0]), best_idx]
                nonzero = best_val[best_val > 0]
                if nonzero.size >= 24:
                    q55 = float(np.percentile(nonzero, 55))
                    q82 = float(np.percentile(nonzero, 82))
                    grad_threshold = max(3.0, q55 * 0.85, q82 * 0.42)
                    selected = best_val >= grad_threshold
                    if int(selected.sum()) >= 24:
                        edge_r = radii[np.clip(best_idx[selected] + 1, 0, len(radii) - 1)].astype(np.float64)
                        edge_angles = angles[selected].astype(np.float64)
                        x = current_cx + np.cos(edge_angles) * edge_r
                        y = current_cy + np.sin(edge_angles) * edge_r
                        fitted, info = run_fit(x, y, mode=1.0, min_coverage=105.0)
                        if fitted is not None:
                            nx, ny, nr = fitted
                            if 0 <= nx < w and 0 <= ny < h and 5 <= nr <= max(w, h) * 1.4:
                                return True, nx, ny, nr, info
                        radial_failure = info

        # -------------------------
        # 方案 B：局部 Canny 环形兜底
        # -------------------------
        margin = int(max(8, band_width + 18))
        crop_r = int(max(8, radius + margin))
        x1 = max(0, int(current_cx - crop_r))
        x2 = min(w, int(current_cx + crop_r))
        y1 = max(0, int(current_cy - crop_r))
        y2 = min(h, int(current_cy + crop_r))
        if x2 <= x1 or y2 <= y1:
            return False, current_cx, current_cy, radius, radial_failure

        roi = gray_full[y1:y2, x1:x2]
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(roi)
        except Exception:
            gray = roi
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        med = float(np.median(gray))
        low = int(max(12, 0.55 * med))
        high = int(min(255, max(low + 18, 1.45 * med)))
        edges = cv2.Canny(gray, low, high, L2gradient=True)

        rh, rw = gray.shape[:2]
        local_cx = float(current_cx - x1)
        local_cy = float(current_cy - y1)
        yy, xx = np.ogrid[:rh, :rw]
        dist2 = (xx - local_cx) ** 2 + (yy - local_cy) ** 2
        inner = max(1, radius - band_width)
        outer = radius + band_width
        band = (dist2 >= inner * inner) & (dist2 <= outer * outer)
        points_y, points_x = np.nonzero((edges > 0) & band)
        point_count = int(len(points_x))
        if point_count < 30:
            failure = dict(radial_failure)
            failure.update({"points": point_count, "mode": 2.0})
            return False, current_cx, current_cy, radius, failure
        if point_count > 5000:
            step = max(1, point_count // 5000)
            points_x = points_x[::step]
            points_y = points_y[::step]
        x = points_x.astype(np.float64) + x1
        y = points_y.astype(np.float64) + y1
        fitted, info = run_fit(x, y, mode=2.0, min_coverage=95.0)
        if fitted is None:
            return False, current_cx, current_cy, radius, info
        nx, ny, nr = fitted
        if not (0 <= nx < w and 0 <= ny < h and 5 <= nr <= max(w, h) * 1.4):
            info = dict(info)
            info["reason"] = "geometry_out_of_bounds"
            return False, current_cx, current_cy, radius, info
        return True, nx, ny, nr, info

    @staticmethod
    def snap_secondary_edge(frame: np.ndarray, current_cx: int, current_cy: int, radius: int,
                            band_width: int = 45, sensitivity: int = 70) -> Tuple[bool, int, int, int, Dict[str, float]]:
        """专门用于副镜弱边缘/局部弧线的吸附

        副镜边缘经常不像外圈那样是一整圈清晰圆弧，而是截图中箭头指向的那种
        低对比、局部、被亮斑和反光打断的边缘通用 snap_outer_edge 会更偏向完整
        高对比圆，所以这里加入两层优化：
        1. 使用更宽的环形搜索带宽和 CLAHE 局部增强，提高暗弱边缘可见度
        2. 在环形 ROI 中做 Canny 后，用带先验约束的 RANSAC 圆拟合，允许只有局部弧线

        sensitivity 取 0-100，越高越容易接受弱边缘；过高可能吸到噪声或反光
        """
        if radius <= 5:
            return False, current_cx, current_cy, radius, {"score": 0.0, "points": 0.0, "mode": 0.0}

        # 先尝试一次通用算法，但给副镜更宽的搜索带宽
        wide_band = int(max(8, band_width))
        ok, nx, ny, nr, info = VisionEngine.snap_outer_edge(frame, current_cx, current_cy, radius, wide_band)
        if ok and info.get("points", 0.0) >= 30:
            info = dict(info)
            info["mode"] = 3.0
            return ok, nx, ny, nr, info

        h, w = frame.shape[:2]
        current_cx = int(current_cx)
        current_cy = int(current_cy)
        radius = int(radius)
        sensitivity = int(max(0, min(100, sensitivity)))
        band_width = int(max(8, min(260, band_width)))

        gray_full = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        crop_r = int(max(20, radius + band_width + 28))
        x1 = max(0, current_cx - crop_r)
        x2 = min(w, current_cx + crop_r)
        y1 = max(0, current_cy - crop_r)
        y2 = min(h, current_cy + crop_r)
        if x2 <= x1 or y2 <= y1:
            return False, current_cx, current_cy, radius, {"score": 0.0, "points": 0.0, "mode": 4.0}

        roi = gray_full[y1:y2, x1:x2]
        try:
            clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8))
            gray = clahe.apply(roi)
        except Exception:
            gray = roi.copy()
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        # sensitivity 越高，Canny 阈值越低，更容易抓住低对比边缘
        med = float(np.median(gray))
        sigma = 0.42 + (100 - sensitivity) / 260.0
        low = int(max(5, (1.0 - sigma) * med))
        high = int(min(255, max(low + 12, (1.0 + sigma) * med)))
        edges = cv2.Canny(gray, low, high, L2gradient=True)

        rh, rw = gray.shape[:2]
        local_cx = float(current_cx - x1)
        local_cy = float(current_cy - y1)
        yy, xx = np.ogrid[:rh, :rw]
        dist = np.sqrt((xx - local_cx) ** 2 + (yy - local_cy) ** 2)
        band = (dist >= max(2, radius - band_width)) & (dist <= radius + band_width)

        # 副镜边缘通常是暗区和亮区的交界保留局部对比足够的边缘点，抑制纯噪声
        local_min = cv2.erode(gray, np.ones((5, 5), np.uint8))
        local_max = cv2.dilate(gray, np.ones((5, 5), np.uint8))
        contrast = (local_max.astype(np.int16) - local_min.astype(np.int16))
        contrast_threshold = max(10, int(36 - sensitivity * 0.22))
        mask = (edges > 0) & band & (contrast >= contrast_threshold)

        points_y, points_x = np.nonzero(mask)
        point_count = int(points_x.size)
        if point_count < 18:
            return False, current_cx, current_cy, radius, {"score": 0.0, "points": float(point_count), "mode": 4.0}

        x = (points_x.astype(np.float64) + x1)
        y = (points_y.astype(np.float64) + y1)
        # 限制点数保证 UI 不被复杂图像拖慢
        if x.size > 3500:
            step = max(1, x.size // 3500)
            x = x[::step]
            y = y[::step]

        def circle_from_3pts(p1: np.ndarray, p2: np.ndarray, p3: np.ndarray):
            ax, ay = p1
            bx, by = p2
            cx, cy = p3
            d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
            if abs(d) < 1e-6:
                return None
            ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
            uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
            rr = math.hypot(ux - ax, uy - ay)
            return ux, uy, rr

        pts = np.column_stack([x, y])
        rng = np.random.default_rng(12345)
        best = None
        best_inliers = None
        n = pts.shape[0]
        iterations = int(220 + sensitivity * 2)
        center_limit = max(35.0, band_width * 2.4)
        radius_limit = max(25.0, band_width * 2.2)
        inlier_tol = max(3.0, band_width * (0.18 + (100 - sensitivity) / 500.0))

        for _ in range(iterations):
            if n < 3:
                break
            idx = rng.choice(n, size=3, replace=False)
            circle = circle_from_3pts(pts[idx[0]], pts[idx[1]], pts[idx[2]])
            if circle is None:
                continue
            cx, cy, rr = circle
            if not (0 <= cx < w and 0 <= cy < h):
                continue
            if abs(rr - radius) > radius_limit:
                continue
            if math.hypot(cx - current_cx, cy - current_cy) > center_limit:
                continue
            residuals = np.abs(np.sqrt((x - cx) ** 2 + (y - cy) ** 2) - rr)
            inliers = residuals <= inlier_tol
            count = int(inliers.sum())
            if count < 16:
                continue
            median_res = float(np.median(residuals[inliers]))
            score_key = (count, -median_res)
            if best is None or score_key > best[0]:
                best = (score_key, cx, cy, rr, median_res)
                best_inliers = inliers

        if best is None or best_inliers is None:
            return False, current_cx, current_cy, radius, {"score": 0.0, "points": float(point_count), "mode": 4.0}

        xx = x[best_inliers]
        yy = y[best_inliers]
        if xx.size >= 6:
            a = np.column_stack((xx, yy, np.ones_like(xx)))
            b = -(xx ** 2 + yy ** 2)
            try:
                sol, *_ = np.linalg.lstsq(a, b, rcond=None)
                A, B, C = sol
                cx = -A / 2.0
                cy = -B / 2.0
                rr = math.sqrt(max(0.0, (A ** 2 + B ** 2) / 4.0 - C))
            except Exception:
                _, cx, cy, rr, _ = best
        else:
            _, cx, cy, rr, _ = best

        residual = float(np.median(np.abs(np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) - rr))) if xx.size else 999.0
        used = int(xx.size)
        score = max(0.0, min(100.0, 100.0 - residual * 5.5 + min(15.0, used / 35.0)))
        return True, int(round(cx)), int(round(cy)), int(round(rr)), {
            "score": score,
            "points": float(used),
            "residual": residual,
            "mode": 4.0,
        }
