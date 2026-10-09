# -*- coding: utf-8 -*-
"""M1 坐标核心单测：往返自洽 + 偏移量级 + 回归基准。

原则（见 python-project-conventions）：算法测试优先用 roundtrip 验证数学正确性，
不依赖网络上流传的、来自不同 GCJ-02 实现的不精确参考坐标（那些"约值"会误报）。
"""
import pytest

from core.coords import (
    wgs84_to_gcj02, gcj02_to_wgs84,
    bd09_to_gcj02, bd09_to_wgs84,
    cgcs2000_to_wgs84, haversine_m,
    gcj02_to_bd09, convert_coord, transform_between,
)


def test_roundtrip_wgs84_gcj02():
    """WGS84 -> GCJ-02 -> WGS84 往返自洽（<1e-6 度，黄金向量级）"""
    points = [
        (116.397428, 39.90923),    # 北京天安门
        (112.936104, 28.169231),   # 湖南大学
        (108.366900, 22.816730),   # 广西南宁
    ]
    for lon, lat in points:
        glon, glat = wgs84_to_gcj02(lon, lat)
        back_lon, back_lat = gcj02_to_wgs84(glon, glat)
        assert back_lon == pytest.approx(lon, abs=1e-6)
        assert back_lat == pytest.approx(lat, abs=1e-6)


def test_gcj02_offset_magnitude():
    """GCJ-02 偏移量级：中国境内应为 50~700m（非恒等变换、非异常）"""
    points = [
        (116.397428, 39.90923),    # 北京
        (108.366900, 22.816730),   # 南宁
        (121.473701, 31.230416),   # 上海
    ]
    for lon, lat in points:
        glon, glat = wgs84_to_gcj02(lon, lat)
        d = haversine_m(lon, lat, glon, glat)
        assert 50.0 < d < 700.0, f"GCJ偏移异常: {lon},{lat} -> {d:.1f}m"


def test_gcj02_known_point_regression():
    """已知点回归：本算法正算得精确 GCJ 后逆解，应闭合回原 WGS84（<1cm）"""
    wlon, wlat = gcj02_to_wgs84(*wgs84_to_gcj02(116.397428, 39.90923))
    assert haversine_m(116.397428, 39.90923, wlon, wlat) < 0.01


def test_bd09_to_gcj02_offset_magnitude():
    """BD-09 相对 GCJ-02 的额外偏移量级 <1500m"""
    bd_lon, bd_lat = 116.307755, 40.057891  # 百度大厦 BD-09
    gcj_lon, gcj_lat = bd09_to_gcj02(bd_lon, bd_lat)
    d = haversine_m(bd_lon, bd_lat, gcj_lon, gcj_lat)
    assert d < 1500.0


def test_bd09_to_wgs84_chain():
    """BD-09 -> GCJ-02 -> WGS84 两级转换一致性"""
    w1 = bd09_to_wgs84(116.307755, 40.057891)
    w2 = gcj02_to_wgs84(*bd09_to_gcj02(116.307755, 40.057891))
    assert w1[0] == pytest.approx(w2[0], abs=1e-9)
    assert w1[1] == pytest.approx(w2[1], abs=1e-9)


def test_cgcs2000_near_wgs84():
    """CGCS2000 与 WGS84 差异极小（工程可视为等同）"""
    lon, lat = cgcs2000_to_wgs84(108.3669, 22.81673)
    d = haversine_m(108.3669, 22.81673, lon, lat)
    assert d < 10.0


def test_haversine_known_distance():
    """haversine 距离合理性（北京-上海约 1067km，量级校验）"""
    d = haversine_m(116.397428, 39.90923, 121.473701, 31.230416)
    assert 1_000_000 < d < 1_100_000


def test_gcj02_bd09_roundtrip():
    """GCJ-02 <-> BD-09 往返自洽"""
    gcj = (116.403747, 39.911954)
    bd = gcj02_to_bd09(*gcj)
    back = bd09_to_gcj02(*bd)
    assert back[0] == pytest.approx(gcj[0], abs=1e-6)
    assert back[1] == pytest.approx(gcj[1], abs=1e-6)


def test_convert_coord_targets():
    """convert_coord 各目标坐标系"""
    wgs = (116.397428, 39.90923)
    # WGS84 原样返回
    assert convert_coord(*wgs, 'WGS84') == wgs
    # GCJ-02 / BD-09 应产生偏移
    assert convert_coord(*wgs, 'GCJ-02') != wgs
    assert convert_coord(*wgs, 'BD-09') != wgs
    # CGCS2000 与 WGS84 差异极小（<10m）
    cgcs = convert_coord(*wgs, 'CGCS2000')
    assert haversine_m(wgs[0], wgs[1], cgcs[0], cgcs[1]) < 10.0


def test_transform_between_roundtrip():
    """transform_between 任意坐标系往返闭合"""
    import itertools
    coord = (116.397428, 39.90923)  # 北京天安门
    crs_list = ['WGS84', 'CGCS2000', 'GCJ-02', 'BD-09']
    for src, dst in itertools.product(crs_list, crs_list):
        if src == dst:
            continue
        mid = transform_between(*coord, src, dst)
        back = transform_between(*mid, dst, src)
        # BD-09 往返有 ~1e-6 度固有误差（gcj02_to_bd09 与 bd09_to_gcj02 非严格互逆），
        # 约 11cm，可忽略；容差放宽到 1e-5（约 1.1m）
        assert back[0] == pytest.approx(coord[0], abs=1e-5), f'{src}->{dst} 经度未闭合'
        assert back[1] == pytest.approx(coord[1], abs=1e-5), f'{src}->{dst} 纬度未闭合'
