# -*- coding: utf-8 -*-
"""M5 质检验真 单测（纯逻辑，shapely 构造多边形）"""
from shapely.geometry import Polygon, Point, mapping

from core.verify import (
    in_boundary, classify_boundary, cross_verify, confidence_level,
)


def make_polygon():
    # 一个 1°×1° 的方框多边形（近似，边界校验用）
    poly = Polygon([(108, 22), (109, 22), (109, 23), (108, 23)])
    return mapping(poly)


def test_in_boundary():
    geo = make_polygon()
    assert in_boundary(108.5, 22.5, geo) is True
    assert in_boundary(110.0, 22.5, geo) is False


def test_classify_boundary_inside():
    geo = make_polygon()
    assert classify_boundary(108.5, 22.5, geo)[0] == 'inside'


def test_classify_boundary_outside():
    geo = make_polygon()
    status, d = classify_boundary(115.0, 25.0, geo)
    assert status == 'outside'
    assert d is not None and d > 500


def test_classify_boundary_none():
    assert classify_boundary(108.5, 22.5, None)[0] == 'unknown'


def test_cross_verify_agreement():
    # 三源坐标一致（偏差<200m）
    points = [('amap', 108.5, 22.5), ('tianditu', 108.5001, 22.5001),
              ('baidu', 108.5002, 22.5002)]
    dev, count = cross_verify(points)
    assert count == 3
    assert dev < 200


def test_cross_verify_single_source():
    dev, count = cross_verify([('amap', 108.5, 22.5)])
    assert count == 1
    assert dev == 0.0


def test_confidence_high():
    assert confidence_level('inside', 2, 50) == '高'


def test_confidence_mid_single():
    assert confidence_level('inside', 1, None) == '中'


def test_confidence_mid_deviation():
    assert confidence_level('edge', 2, 300) == '中'


def test_confidence_low_outside():
    assert confidence_level('outside', 2, 50) == '低'


def test_confidence_low_arbitrate():
    assert confidence_level('inside', 2, 600) == '低'
