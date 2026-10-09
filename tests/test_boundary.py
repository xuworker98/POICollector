# -*- coding: utf-8 -*-
"""M5 边界获取 单测（纯逻辑：polyline 解析 + GCJ→WGS84 几何转换）"""
from boundary.fetcher import parse_polyline, gcj02_geojson_to_wgs84


def test_parse_polyline_single():
    polyline = '108.0,22.0;109.0,22.0;109.0,23.0;108.0,23.0'
    geo = parse_polyline(polyline)
    assert geo['type'] == 'MultiPolygon'
    assert len(geo['coordinates']) == 1
    assert len(geo['coordinates'][0][0]) == 5  # 4 点 + 闭合


def test_parse_polyline_multi():
    polyline = '108.0,22.0;109.0,22.0;109.0,23.0|110.0,24.0;111.0,24.0;111.0,25.0'
    geo = parse_polyline(polyline)
    assert len(geo['coordinates']) == 2


def test_parse_polyline_empty():
    assert parse_polyline('') is None
    assert parse_polyline(None) is None


def test_parse_polyline_insufficient_points():
    assert parse_polyline('108.0,22.0;109.0,22.0') is None  # 少于3点不成多边形


def test_gcj_geojson_to_wgs84_shift():
    """GCJ→WGS84 后坐标应发生偏移（中国境内非零偏移）"""
    polyline = '116.40,39.91;116.41,39.91;116.41,39.92;116.40,39.92'
    gcj = parse_polyline(polyline)
    wgs = gcj02_geojson_to_wgs84(gcj)
    # 转换后坐标应与原始 GCJ 不同（存在偏移）
    orig_lon = gcj['coordinates'][0][0][0][0]
    new_lon = wgs['coordinates'][0][0][0][0]
    assert orig_lon != new_lon


def test_gcj_polygon_to_wgs84_shift():
    polygon = {'type': 'Polygon', 'coordinates': [[
        [116.40, 39.91], [116.41, 39.91], [116.41, 39.92], [116.40, 39.91]
    ]]}
    converted = gcj02_geojson_to_wgs84(polygon)
    assert converted['type'] == 'Polygon'
    assert converted['coordinates'][0][0] != polygon['coordinates'][0][0]
