# -*- coding: utf-8 -*-
"""边界获取：高德 district API（省市县）+ DataV.GeoAtlas（乡镇），统一转 WGS84 缓存"""
import json
import os

import requests

from core.coords import gcj02_to_wgs84
from core.region import pad_code


def parse_polyline(polyline_str):
    """解析高德 district polyline 为 GeoJSON MultiPolygon（GCJ-02 坐标，需再转 WGS84）。

    高德格式：单多边形 "lon,lat;lon,lat;..."，多段（飞地/多岛）用 "|" 分隔。
    """
    if not polyline_str:
        return None
    polygons = []
    for part in polyline_str.split('|'):
        coords = []
        for pair in part.split(';'):
            pair = pair.strip()
            if ',' in pair:
                lon, lat = pair.split(',', 1)
                try:
                    coords.append((float(lon), float(lat)))
                except ValueError:
                    continue
        if len(coords) >= 3:
            coords.append(coords[0])  # 闭合
            polygons.append(coords)
    if not polygons:
        return None
    return {'type': 'MultiPolygon', 'coordinates': [[p] for p in polygons]}


def gcj02_geojson_to_wgs84(geojson):
    """Convert any GeoJSON geometry coordinates from GCJ-02 to WGS84."""
    if not geojson:
        return geojson
    if geojson.get('type') == 'GeometryCollection':
        return {'type': 'GeometryCollection', 'geometries': [
            gcj02_geojson_to_wgs84(item) for item in geojson.get('geometries', [])
        ]}

    def convert(value):
        if (isinstance(value, (list, tuple)) and len(value) >= 2
                and isinstance(value[0], (int, float)) and isinstance(value[1], (int, float))):
            lon, lat = gcj02_to_wgs84(float(value[0]), float(value[1]))
            return [lon, lat, *value[2:]]
        return [convert(item) for item in value]

    return {'type': geojson.get('type'), 'coordinates': convert(geojson.get('coordinates', []))}


def fetch_amap_district(key, keywords, subdistrict=0):
    """高德 district API 拉边界 polyline（省市县三级，个人 key 即可）。

    返回 GeoJSON MultiPolygon（WGS84）或 None。
    """
    import urllib.parse
    q = urllib.parse.quote(str(keywords))
    url = (f'https://restapi.amap.com/v3/config/district?keywords={q}'
           f'&subdistrict={subdistrict}&extensions=all&key={key}')
    try:
        d = requests.get(url, timeout=15).json()
    except Exception:
        return None
    districts = d.get('districts') or []
    if not districts:
        return None
    polyline = districts[0].get('polyline')
    gcj = parse_polyline(polyline)
    return gcj02_geojson_to_wgs84(gcj)


def fetch_datav(adcode):
    """DataV.GeoAtlas 拉乡镇级边界 geojson（免账号，GCJ-02）。

    https://geo.datav.aliyun.com/areas_v3/bound/{adcode}.json
    """
    url = f'https://geo.datav.aliyun.com/areas_v3/bound/{adcode}.json'
    try:
        d = requests.get(url, timeout=15).json()
    except Exception:
        return None
    features = d.get('features') or []
    if not features:
        return None
    # DataV 返回 FeatureCollection，几何为 GCJ-02
    geojson = features[0].get('geometry') if features else None
    return gcj02_geojson_to_wgs84(geojson)


def save_boundary(cache_dir, adcode, geojson):
    """边界入库（GeoJSON 缓存），返回缓存路径。"""
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f'{adcode}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, ensure_ascii=False)
    return path


def load_boundary(cache_dir, adcode):
    path = os.path.join(cache_dir, f'{adcode}.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)
