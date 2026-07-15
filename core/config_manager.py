# -*- coding: utf-8 -*-
# 文件说明：配置读写模块负责把界面参数保存到 config/config.txt，并在下次启动时恢复
from __future__ import annotations

import os
from dataclasses import fields, is_dataclass
from typing import Any, Dict, Tuple

from .app_state import AppConfig, CircleConfig, StarConfig


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "启用", "是"}


def _parse_color(value: str) -> Tuple[int, int, int]:
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 3:
        raise ValueError("颜色必须是 B,G,R 格式，例如 0,255,0")
    return tuple(max(0, min(255, int(p))) for p in parts)  # type: ignore[return-value]


def _format_color(color: Tuple[int, int, int]) -> str:
    return f"{color[0]},{color[1]},{color[2]}"


class ConfigManager:
    """读取和保存 key=value 格式的 config.txt

    配置文件故意采用普通 txt，而不是二进制或复杂格式
    这样用户可以直接用记事本手动微调圆心偏移、半径、线宽、相机类型等参数
    """

    def __init__(self, filepath: str = "config/config.txt") -> None:
        self.filepath = filepath

    def load(self) -> AppConfig:
        config = AppConfig()
        if not os.path.exists(self.filepath):
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            self.save(config)
            return config

        raw: Dict[str, str] = {}
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                raw[key.strip()] = value.strip()

        # 读取普通字段，例如语言、相机类型、分辨率、圆心和吸附参数
        for name in [
            "language",
            "camera_type",
            "camera_id",
            "frame_width",
            "frame_height",
            "camera_exposure_ms",
            "camera_iso",
            "camera_gain",
            "camera_auto_exposure",
            "camera_auto_focus",
            "camera_focus",
            "zwo_dll_path",
            "center_x",
            "center_y",
            "horizontal_offset",
            "vertical_offset",
            "reference_locked",
            "zoom_percent",
            "view_pan_x",
            "view_pan_y",
            "ui_fps_limit",
            "auto_tracking",
            "track_middle",
            "track_inner",
            "track_secondary",
            "active_target",
            "middle_concentric_with_outer",
            "inner_concentric_with_outer",
            "secondary_concentric_with_outer",
            "circle2_center_x",
            "circle2_center_y",
            "circle3_center_x",
            "circle3_center_y",
            "circle4_center_x",
            "circle4_center_y",
            "snap_roi",
            "snap_threshold",
            "edge_band_width",
            "secondary_edge_band_width",
            "secondary_edge_sensitivity",
            "guide_tolerance",
        ]:
            if name not in raw:
                continue
            current = getattr(config, name)
            try:
                if isinstance(current, bool):
                    setattr(config, name, _parse_bool(raw[name]))
                elif isinstance(current, int):
                    setattr(config, name, int(float(raw[name])))
                elif isinstance(current, float):
                    setattr(config, name, float(raw[name]))
                else:
                    setattr(config, name, raw[name])
            except ValueError:
                print(f"[Config] 已忽略无效配置: {name}={raw[name]}")

        # 读取嵌套对象，例如 circle1.radius、star.length 等覆盖层参数
        self._load_nested(raw, config.circle1, "circle1")
        self._load_nested(raw, config.circle2, "circle2")
        self._load_nested(raw, config.circle3, "circle3")
        self._load_nested(raw, config.circle4, "circle4")
        self._load_nested(raw, config.star, "star")

        # 保持圆心和偏移一致如果配置里明确写了 offset，就以 offset 为准重新计算圆心
        if "horizontal_offset" in raw or "vertical_offset" in raw:
            config.update_center_from_offsets()
        else:
            config.update_offsets_from_center()

        # 兼容旧配置：如果没有保存过中圈/内圈检测中心，则先让它们落在外圈参考中心
        if "circle2_center_x" not in raw or "circle2_center_y" not in raw:
            config.circle2_center_x = int(config.center_x)
            config.circle2_center_y = int(config.center_y)
        if "circle3_center_x" not in raw or "circle3_center_y" not in raw:
            config.circle3_center_x = int(config.center_x)
            config.circle3_center_y = int(config.center_y)
        if "circle4_center_x" not in raw or "circle4_center_y" not in raw:
            config.circle4_center_x = int(config.center_x)
            config.circle4_center_y = int(config.center_y)
        return config

    def _load_nested(self, raw: Dict[str, str], obj: Any, prefix: str) -> None:
        for field in fields(obj):
            key = f"{prefix}.{field.name}"
            if key not in raw:
                continue
            try:
                current = getattr(obj, field.name)
                if isinstance(current, bool):
                    setattr(obj, field.name, _parse_bool(raw[key]))
                elif isinstance(current, float):
                    setattr(obj, field.name, float(raw[key]))
                elif isinstance(current, int):
                    setattr(obj, field.name, int(float(raw[key])))
                elif isinstance(current, tuple):
                    setattr(obj, field.name, _parse_color(raw[key]))
                else:
                    setattr(obj, field.name, raw[key])
            except ValueError:
                print(f"[Config] 已忽略无效配置: {key}={raw[key]}")

    def save(self, config: AppConfig) -> None:
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        config.update_offsets_from_center()
        lines = [
            "# OCAL Python Pro 配置文件",
            "# 所有坐标、偏移、半径单位均为原始相机画面像素",
            f"language={config.language}",
            f"camera_type={config.camera_type}",
            f"camera_id={config.camera_id}",
            f"frame_width={config.frame_width}",
            f"frame_height={config.frame_height}",
            f"camera_exposure_ms={config.camera_exposure_ms}",
            f"camera_iso={config.camera_iso}",
            f"camera_gain={config.camera_gain}",
            f"camera_auto_exposure={config.camera_auto_exposure}",
            f"camera_auto_focus={config.camera_auto_focus}",
            f"camera_focus={config.camera_focus}",
            f"zwo_dll_path={config.zwo_dll_path}",
            f"center_x={config.center_x}",
            f"center_y={config.center_y}",
            f"horizontal_offset={config.horizontal_offset}",
            f"vertical_offset={config.vertical_offset}",
            f"reference_locked={config.reference_locked}",
            f"zoom_percent={config.zoom_percent}",
            f"view_pan_x={config.view_pan_x}",
            f"view_pan_y={config.view_pan_y}",
            f"ui_fps_limit={config.ui_fps_limit}",
            f"auto_tracking={config.auto_tracking}",
            f"track_middle={config.track_middle}",
            f"track_inner={config.track_inner}",
            f"track_secondary={config.track_secondary}",
            f"active_target={config.active_target}",
            f"middle_concentric_with_outer={config.middle_concentric_with_outer}",
            f"inner_concentric_with_outer={config.inner_concentric_with_outer}",
            f"secondary_concentric_with_outer={config.secondary_concentric_with_outer}",
            f"circle2_center_x={config.circle2_center_x}",
            f"circle2_center_y={config.circle2_center_y}",
            f"circle3_center_x={config.circle3_center_x}",
            f"circle3_center_y={config.circle3_center_y}",
            f"circle4_center_x={config.circle4_center_x}",
            f"circle4_center_y={config.circle4_center_y}",
            f"snap_roi={config.snap_roi}",
            f"snap_threshold={config.snap_threshold}",
            f"edge_band_width={config.edge_band_width}",
            f"secondary_edge_band_width={config.secondary_edge_band_width}",
            f"secondary_edge_sensitivity={config.secondary_edge_sensitivity}",
            f"guide_tolerance={config.guide_tolerance}",
        ]
        lines.extend(self._dump_nested(config.circle1, "circle1"))
        lines.extend(self._dump_nested(config.circle2, "circle2"))
        lines.extend(self._dump_nested(config.circle3, "circle3"))
        lines.extend(self._dump_nested(config.circle4, "circle4"))
        lines.extend(self._dump_nested(config.star, "star"))
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def _dump_nested(self, obj: Any, prefix: str) -> list[str]:
        lines: list[str] = []
        if not is_dataclass(obj):
            return lines
        for field in fields(obj):
            value = getattr(obj, field.name)
            if isinstance(value, tuple):
                value = _format_color(value)
            lines.append(f"{prefix}.{field.name}={value}")
        return lines
