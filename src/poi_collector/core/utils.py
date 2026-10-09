# -*- coding: utf-8 -*-
"""坐标/地址通用工具：度分秒解析、坐标校验、格式化。"""
import re


def parse_coordinate_str(coord_str):
    """解析经纬度字符串返回十进制度，失败返回 None。

    支持：十进制（113.123456）、度分秒（113°22′00″E）、冒号（113:22:00）、
    方向字母（N/S/E/W，S/W 为负）。
    """
    if not coord_str:
        return None
    s = str(coord_str).strip()
    direction = 1
    upper = s.upper()
    if upper.endswith(('N', 'S', 'E', 'W')):
        if upper[-1] in ('S', 'W'):
            direction = -1
        s = s[:-1].strip()
    try:
        return float(s) * direction
    except ValueError:
        pass
    patterns = [
        r'(-?\d+)[°度]\s*(\d+)[′分\']?\s*([\d.]+)[″秒"]?',
        r'(-?\d+)\s+(\d+)\s+([\d.]+)',
        r'(-?\d+):(\d+):([\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, s)
        if m:
            deg, min_, sec = m.groups()
            try:
                return (int(deg) + int(min_) / 60 + float(sec) / 3600) * direction
            except (ValueError, TypeError):
                continue
    return None


def validate_coordinate(lon, lat):
    """校验经纬度范围。"""
    return -180 <= lon <= 180 and -90 <= lat <= 90


def format_coord(lon, lat, precision=6):
    """格式化坐标显示。"""
    return f'{lon:.{precision}f}, {lat:.{precision}f}'
