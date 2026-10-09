# -*- coding: utf-8 -*-
"""质检验真：边界校验 + 交叉验真 + 置信度分级。

⚠ 教训（必须牢记）：多源互比 ≠ 验真——所有源经同一个错误转换函数时，
错误坐标会"互相一致"。交付前必须用独立真值（用户实测/官方坐标）做黄金向量抽检。
"""
from shapely.geometry import shape, Point

from core.coords import haversine_m

# 边界校验阈值（米）
BOUNDARY_MARGIN_M = 500  # 边界外 <500m 视为"贴边"（边界简化误差），可接受


def in_boundary(lon, lat, polygon_geojson):
    """WGS84 点是否落在 WGS84 多边形内（边界库必须先统一转 WGS84）。"""
    try:
        return shape(polygon_geojson).contains(Point(lon, lat))
    except Exception:
        return False


def distance_to_boundary_m(lon, lat, polygon_geojson):
    """点到多边形边界的最短距离（米，近似，用纬度平均度长）。"""
    try:
        poly = shape(polygon_geojson)
        if poly.contains(Point(lon, lat)):
            return 0.0
        # shapely 返回度数，乘以近似米/度（经度需按纬度校正，这里用近似值）
        deg = poly.exterior.distance(Point(lon, lat))
        return deg * 111000.0
    except Exception:
        return float('inf')


def classify_boundary(lon, lat, polygon_geojson):
    """边界校验分类：返回 ('inside'/'edge'/'outside', distance_m)。

    - 落在边界内 -> 'inside'（通过）
    - 边界外但 <500m（边界简化误差）-> 'edge'（通过但标记"贴边"）
    - 边界外 >=500m -> 'outside'（越界异常，进异常清单）
    """
    if polygon_geojson is None:
        return 'unknown', None
    try:
        poly = shape(polygon_geojson)
        if poly.contains(Point(lon, lat)):
            return 'inside', 0.0
        d = poly.exterior.distance(Point(lon, lat)) * 111000.0
        if d < BOUNDARY_MARGIN_M:
            return 'edge', d
        return 'outside', d
    except Exception:
        return 'unknown', None


def cross_verify(points):
    """交叉验真：对同一 POI 的多源坐标两两比对，返回 (最大偏差米, 源数量)。

    points: [(source_name, lon, lat), ...]
    """
    if len(points) < 2:
        return 0.0, len(points)
    max_dev = 0.0
    for i in range(len(points)):
        for j in range(i + 1, len(points)):
            d = haversine_m(points[i][1], points[i][2], points[j][1], points[j][2])
            max_dev = max(max_dev, d)
    return max_dev, len(points)


def confidence_level(boundary_status, source_count, cross_deviation=None):
    """置信度分级（广西项目验证）：

    高：双源以上一致（偏差<200m）且边界内
    中：单源命中且边界内；或双源偏差 200~500m
    低：单源且无边界校验；或越界；或双源偏差 >500m（需仲裁）
    """
    if source_count >= 2 and boundary_status in ('inside', 'edge') \
            and (cross_deviation is None or cross_deviation < 200):
        return '高'
    if boundary_status in ('inside', 'edge') and source_count == 1:
        return '中'
    if source_count >= 2 and cross_deviation is not None and 200 <= cross_deviation <= 500:
        return '中'
    return '低'
