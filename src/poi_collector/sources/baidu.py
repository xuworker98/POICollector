# -*- coding: utf-8 -*-
"""百度数据源（BD-09 两级转换 -> WGS84）"""
import urllib.parse

from core.coords import bd09_to_wgs84, wgs84_to_bd09
from .base import SourceBase, QuotaExceeded, http_get_json

# 百度配额/权限类错误码（status 1/2/3）
BAIDU_QUOTA_CODES = (1, 2, 3, 4, 302)


class BaiduSource(SourceBase):
    name = "baidu"
    crs = "BD-09"
    supports_geocode = True
    supports_poi = True
    supports_around = True
    supports_reverse = True

    def _call(self, url):
        """百度请求封装：限速 + HTTP + 配额检查 + status 检查。"""
        self.limiter.wait()
        d = http_get_json(url)
        if d is None:
            return None
        if d.get('status') in BAIDU_QUOTA_CODES:
            raise QuotaExceeded(f"百度配额: {d.get('status')} {d.get('msg', '')}")
        if d.get('status') != 0:
            return None
        return d

    def geocode(self, address, city=''):
        q = urllib.parse.quote(address)
        c = urllib.parse.quote(city) if city else ''
        url = (f'https://api.map.baidu.com/geocoding/v3/?address={q}'
               f'&city={c}&output=json&ak={self.key}')
        d = self._call(url)
        if d is None:
            return None
        result = d.get('result') or {}
        loc = result.get('location') or {}
        if not loc.get('lng'):
            return None
        wlon, wlat = bd09_to_wgs84(float(loc['lng']), float(loc['lat']))
        level = result.get('level') or ''
        return (round(wlon, 6), round(wlat, 6), level, level)

    def _parse_pois(self, d):
        """解析百度 results 列表 -> WGS84 dict 列表。"""
        pois = []
        for p in d.get('results', []):
            loc = p.get('location', {})
            lng = loc.get('lng')
            lat = loc.get('lat')
            if lng is None or lat is None:
                continue
            wlon, wlat = bd09_to_wgs84(float(lng), float(lat))
            pois.append({
                'name': p.get('name', ''),
                'address': p.get('address', ''),
                'adcode': p.get('area', ''),
                'pname': '',
                'cityname': p.get('city', ''),
                'adname': p.get('area', ''),
                'type': '',
                'typecode': '',
                'lon': round(wlon, 6),
                'lat': round(wlat, 6),
            })
        return pois

    def poi_search(self, keyword, city='', types=None, page=1, offset=100):
        """百度 POI 搜索（place/v2/search）。"""
        q = urllib.parse.quote(keyword)
        region = ''
        if city:
            region = f'&region={urllib.parse.quote(city)}&city_limit=true'
        url = (f'https://api.map.baidu.com/place/v2/search?query={q}{region}'
               f'&output=json&scope=2&page_size={offset}&page_num={page - 1}&ak={self.key}')
        d = self._call(url)
        if d is None:
            return [], 0
        return self._parse_pois(d), int(d.get('total', 0))

    def around_search(self, lon, lat, radius, keyword='', types=None, page=1, offset=100):
        """周边搜索（圆形区域，中心点为 WGS84 经纬度）。"""
        bd_lon, bd_lat = wgs84_to_bd09(lon, lat)
        q = urllib.parse.quote(keyword or types or '地点')
        url = (f'https://api.map.baidu.com/place/v2/search?query={q}'
               f'&location={bd_lat},{bd_lon}&radius={radius}&output=json&scope=2'
               f'&page_size={offset}&page_num={page - 1}&ak={self.key}')
        d = self._call(url)
        if d is None:
            return [], 0
        return self._parse_pois(d), int(d.get('total', 0))

    def reverse_geocode(self, lon, lat):
        """逆地理编码：WGS84 -> 结构化地址。"""
        url = (f'https://api.map.baidu.com/reverse_geocoding/v3/?location={lat},{lon}'
               f'&output=json&coordtype=wgs84ll&ak={self.key}')
        d = self._call(url)
        if d is None:
            return None
        result = d.get('result') or {}
        comp = result.get('addressComponent', {})
        return {
            'formatted': result.get('formatted_address', ''),
            'province': comp.get('province', ''),
            'city': comp.get('city', ''),
            'district': comp.get('district', ''),
            'township': comp.get('town', ''),
            'street': comp.get('street', ''),
            'number': comp.get('street_number', ''),
        }
