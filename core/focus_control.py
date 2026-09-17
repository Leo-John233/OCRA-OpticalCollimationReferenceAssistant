"""在以零为中心的界面刻度和相机绝对焦点值之间转换"""

FOCUS_MAXIMUM = 1023
FOCUS_MIDPOINT = 512
FOCUS_OFFSET_LIMIT = 512


def focus_from_offset(offset: int) -> int:
    """将左右对称刻度转换为非负驱动值，不把负数直接交给相机"""
    value = max(-FOCUS_OFFSET_LIMIT, min(FOCUS_OFFSET_LIMIT, int(offset)))
    if value <= 0:
        return FOCUS_MIDPOINT + value
    # 驱动有 1024 个整数值，正半轴缩放一个刻度以保持界面完全对称
    return FOCUS_MIDPOINT + round(value * (FOCUS_MAXIMUM - FOCUS_MIDPOINT) / FOCUS_OFFSET_LIMIT)


def focus_to_offset(focus: int) -> int:
    """把保存的绝对焦点还原为界面刻度，保留旧配置的实际位置"""
    value = max(0, min(FOCUS_MAXIMUM, int(focus)))
    if value <= FOCUS_MIDPOINT:
        return value - FOCUS_MIDPOINT
    return round((value - FOCUS_MIDPOINT) * FOCUS_OFFSET_LIMIT / (FOCUS_MAXIMUM - FOCUS_MIDPOINT))
