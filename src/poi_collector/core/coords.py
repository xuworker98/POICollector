# -*- coding: utf-8 -*-
"""坐标系纠偏链（自广西项目 gc_common.py 一字不改搬入）:
  天地图 CGCS2000 -> pyproj EPSG:4490->4326 -> WGS84
  高德/腾讯 GCJ-02 -> 标准迭代逆解 -> WGS84
  百度  BD-09 -> GCJ-02 -> 迭代逆解 -> WGS84
"""
import math

import pyproj

# ---------- CGCS2000 -> WGS84 (pyproj 严格转换) ----------
_T4490_4326 = pyproj.Transformer.from_crs('EPSG:4490', 'EPSG:4326', always_xy=True)


def cgcs2000_to_wgs84(lon, lat):
    return _T4490_4326.transform(lon, lat)


_T4326_4490 = pyproj.Transformer.from_crs('EPSG:4326', 'EPSG:4490', always_xy=True)


def wgs84_to_cgcs2000(lon, lat):
    return _T4326_4490.transform(lon, lat)


# ---------- GCJ-02 <-> WGS84 ----------
_A = 6378245.0
_EE = 0.00669342162296594323


def _transform_lat(x, y):
    ret = -100.0 + 2.0*x + 3.0*y + 0.2*y*y + 0.1*x*y + 0.2*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(y*math.pi) + 40.0*math.sin(y/3.0*math.pi)) * 2.0/3.0
    ret += (160.0*math.sin(y/12.0*math.pi) + 320*math.sin(y*math.pi/30.0)) * 2.0/3.0
    return ret


def _transform_lon(x, y):
    ret = 300.0 + x + 2.0*y + 0.1*x*x + 0.1*x*y + 0.1*math.sqrt(abs(x))
    ret += (20.0*math.sin(6.0*x*math.pi) + 20.0*math.sin(2.0*x*math.pi)) * 2.0/3.0
    ret += (20.0*math.sin(x*math.pi) + 40.0*math.sin(x/3.0*math.pi)) * 2.0/3.0
    ret += (150.0*math.sin(x/12.0*math.pi) + 300.0*math.sin(x/30.0*math.pi)) * 2.0/3.0
    return ret


def wgs84_to_gcj02(lon, lat):
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * math.pi)
    dlon = (dlon * 180.0) / (_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lon + dlon, lat + dlat


def gcj02_to_wgs84(lon, lat):
    # 标准迭代逆解：从GCJ点出发，反复用正向偏移修正逼近真值WGS
    # 迭代6次往返误差<1e-9度（黄金测试向量验证过）
    # ⚠ 千万不要用"简单减偏移"公式——误差4×GCJ偏移量≈2km（广西项目踩过的重大坑）
    wlon, wlat = lon, lat
    for _ in range(6):
        glon, glat = wgs84_to_gcj02(wlon, wlat)
        wlon -= (glon - lon)
        wlat -= (glat - lat)
    return wlon, wlat


# ---------- BD-09 -> GCJ-02 -> WGS84 ----------
_X_PI = math.pi * 3000.0 / 180.0


def bd09_to_gcj02(lng, lat):
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x*x + y*y) - 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * _X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def bd09_to_wgs84(lng, lat):
    g_lon, g_lat = bd09_to_gcj02(lng, lat)
    return gcj02_to_wgs84(g_lon, g_lat)


def gcj02_to_bd09(lng, lat):
    """GCJ-02 -> BD-09（bd09_to_gcj02 的逆运算）"""
    x = lng
    y = lat
    z = math.sqrt(x * x + y * y) + 0.00002 * math.sin(y * _X_PI)
    theta = math.atan2(y, x) + 0.000003 * math.cos(x * _X_PI)
    bd_lng = z * math.cos(theta) + 0.0065
    bd_lat = z * math.sin(theta) + 0.006
    return bd_lng, bd_lat


def wgs84_to_bd09(lng, lat):
    g_lon, g_lat = wgs84_to_gcj02(lng, lat)
    return gcj02_to_bd09(g_lon, g_lat)


# ---------- 距离（交叉验真用） ----------
def haversine_m(lon1, lat1, lon2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


# ---------- 统一坐标转换出口（WGS84 -> 目标坐标系） ----------
def convert_coord(lon, lat, target_crs):
    """WGS84 坐标转为目标坐标系。target_crs: WGS84 / CGCS2000 / GCJ-02 / BD-09。"""
    t = (target_crs or 'WGS84').upper()
    if t == 'WGS84':
        return lon, lat
    if t == 'CGCS2000':
        return wgs84_to_cgcs2000(lon, lat)
    if t in ('GCJ-02', 'GCJ02'):
        return wgs84_to_gcj02(lon, lat)
    if t in ('BD-09', 'BD09'):
        return wgs84_to_bd09(lon, lat)
    return lon, lat


def transform_between(lon, lat, src_cs, dst_cs):
    """任意坐标系互转（以 WGS84 为枢纽）。src_cs/dst_cs: WGS84 / CGCS2000 / GCJ-02 / BD-09。"""
    src = (src_cs or 'WGS84').upper().strip()
    dst = (dst_cs or 'WGS84').upper().strip()
    # 1. 源 -> WGS84
    if src == 'WGS84':
        wlon, wlat = lon, lat
    elif src == 'CGCS2000':
        wlon, wlat = cgcs2000_to_wgs84(lon, lat)
    elif src in ('GCJ-02', 'GCJ02'):
        wlon, wlat = gcj02_to_wgs84(lon, lat)
    elif src in ('BD-09', 'BD09'):
        wlon, wlat = bd09_to_wgs84(lon, lat)
    else:
        raise ValueError(f'不支持的源坐标系: {src_cs}')
    # 2. WGS84 -> 目标
    return convert_coord(wlon, wlat, dst)
