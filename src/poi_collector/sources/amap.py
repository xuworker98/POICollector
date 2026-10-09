# -*- coding: utf-8 -*-
"""高德数据源（GCJ-02，QPS/日配额分离）。

状态码语义（⚠ 分离处理是稳定性的关键）:
  10019/10021 = QPS限速  -> 等待递增重试，不中断任务
  10003/10044 = 日配额用尽 -> 抛 QuotaExceeded，触发停机/换源
  10001/10002/10022/10023 = KEY权限异常 -> 打日志返回None
"""
import time
import urllib.parse

from core.coords import gcj02_to_wgs84, wgs84_to_gcj02
from .base import SourceBase, QuotaExceeded, http_get_json

AMAP_QUOTA_CODES = ('10003', '10044')   # 日配额用尽 -> 停机
AMAP_QPS_CODES = ('10019', '10021')     # QPS限速 -> 等待重试(不中断)


class AmapSource(SourceBase):
    name = "amap"
    crs = "GCJ-02"
    supports_geocode = True
    supports_poi = True
    supports_around = True
    supports_reverse = True

    def _call(self, url, qps_retries=4):
        """高德请求封装：QPS限速自动等待递增重试；日配额抛 QuotaExceeded；权限异常返回 None。"""
        last = None
        for attempt in range(qps_retries + 1):
            self.limiter.wait()
            d = http_get_json(url)
            if d is None:
                return None
            code = d.get('infocode')
            if code in AMAP_QPS_CODES:
                last = d
                time.sleep(2.5 + attempt * 2.0)   # 2.5s 起每轮 +2s
                continue
            if code in AMAP_QUOTA_CODES:
                raise QuotaExceeded(f"高德日配额用尽: {code} {d.get('info')}")
            if code in ('10001', '10002', '10022', '10023'):
                return None                        # KEY 权限异常，交给上层标记
            return d
        raise QuotaExceeded(f"高德QPS持续超限: {last.get('infocode')} {last.get('info')}")

    def geocode(self, address, city=''):
        q = urllib.parse.quote(address)
        c = urllib.parse.quote(city) if city else ''
        url = f'https://restapi.amap.com/v3/geocode/geo?address={q}&city={c}&key={self.key}'
        d = self._call(url)
        if d is None or d.get('status') != '1' or not d.get('geocodes'):
            return None
        g = d['geocodes'][0]
        lon, lat = map(float, g['location'].split(','))
        wlon, wlat = gcj02_to_wgs84(lon, lat)
        return (round(wlon, 6), round(wlat, 6), g.get('level') or '', g.get('formatted_address') or '')

    def _parse_pois(self, d):
        """解析高德 pois 列表 -> WGS84 dict 列表。"""
        pois = []
        for p in d.get('pois', []):
            loc = p.get('location', '')
            if not loc:
                continue
            lon, lat = map(float, loc.split(','))
            wlon, wlat = gcj02_to_wgs84(lon, lat)
            pois.append({
                'name': p.get('name') or '',
                'address': p.get('address') or '',
                'adcode': p.get('adcode') or '',
                'pname': p.get('pname') or '',
                'cityname': p.get('cityname') or '',
                'adname': p.get('adname') or '',
                'type': p.get('type') or '',
                'typecode': p.get('typecode') or '',
                'lon': round(wlon, 6),
                'lat': round(wlat, 6),
            })
        return pois

    def poi_search(self, keyword, city='', types=None, page=1, offset=100):
        """高德 POI 搜索（text 接口）。

        ⚠ 铁律：city 参数必填且 citylimit=true —— 无 city 限定会全国同名错配
           （广西项目实测：不带 city，"三塘镇"匹配到湖南衡阳）。
        """
        q = urllib.parse.quote(keyword)
        c = urllib.parse.quote(city) if city else ''
        t = f'&types={urllib.parse.quote(types)}' if types else ''
        url = (f'https://restapi.amap.com/v3/place/text?keywords={q}&city={c}'
               f'&citylimit=true{t}&page={page}&offset={offset}&key={self.key}')
        d = self._call(url)
        if d is None or d.get('status') != '1':
            return [], 0
        return self._parse_pois(d), int(d.get('count', 0))

    def around_search(self, lon, lat, radius, keyword='', types=None, page=1, offset=100):
        """周边搜索（圆形区域，中心点为 WGS84 经纬度）。"""
        gcj_lon, gcj_lat = wgs84_to_gcj02(lon, lat)
        t = f'&types={urllib.parse.quote(types)}' if types else ''
        q = f'&keywords={urllib.parse.quote(keyword)}' if keyword else ''
        url = (f'https://restapi.amap.com/v3/place/around?location={gcj_lon},{gcj_lat}'
               f'&radius={radius}{q}{t}&page={page}&offset={offset}&key={self.key}')
        d = self._call(url)
        if d is None or d.get('status') != '1':
            return [], 0
        return self._parse_pois(d), int(d.get('count', 0))

    def reverse_geocode(self, lon, lat):
        """逆地理编码：WGS84 -> 结构化地址。"""
        gcj_lon, gcj_lat = wgs84_to_gcj02(lon, lat)
        url = (f'https://restapi.amap.com/v3/geocode/regeo?location={gcj_lon},{gcj_lat}'
               f'&extensions=all&key={self.key}')
        d = self._call(url)
        if d is None or d.get('status') != '1':
            return None
        regeo = d.get('regeocode', {})
        comp = regeo.get('addressComponent', {})
        sn = comp.get('streetNumber') or {}
        return {
            'formatted': regeo.get('formatted_address', ''),
            'province': comp.get('province', ''),
            'city': comp.get('city', '') or comp.get('province', ''),
            'district': comp.get('district', ''),
            'township': comp.get('township', ''),
            'street': sn.get('street', ''),
            'number': sn.get('number', ''),
        }
