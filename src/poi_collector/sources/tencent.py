# -*- coding: utf-8 -*-
"""腾讯位置服务 WebService 数据源（GCJ-02）。"""
import urllib.parse

from core.coords import gcj02_to_wgs84, wgs84_to_gcj02
from .base import SourceBase, QuotaExceeded, http_get_json

TENCENT_QUOTA_CODES = (120, 121)


class TencentSource(SourceBase):
    name = "tencent"
    crs = "GCJ-02"
    supports_geocode = True
    supports_poi = True
    supports_around = True
    supports_reverse = True

    def _call(self, url):
        self.limiter.wait()
        data = http_get_json(url)
        if not isinstance(data, dict):
            return None
        status = int(data.get('status', -1))
        if status in TENCENT_QUOTA_CODES:
            raise QuotaExceeded(f"腾讯配额用尽: {status} {data.get('message', '')}")
        return data if status == 0 else None

    def geocode(self, address, city=''):
        q = urllib.parse.quote(address)
        region = f'&region={urllib.parse.quote(city)}' if city else ''
        url = f'https://apis.map.qq.com/ws/geocoder/v1/?address={q}{region}&key={self.key}'
        d = self._call(url)
        if d is None:
            return None
        result = d.get('result') or {}
        loc = result.get('location') or {}
        if not loc.get('lng'):
            return None
        wlon, wlat = gcj02_to_wgs84(float(loc['lng']), float(loc['lat']))
        title = result.get('title') or ''
        return (round(wlon, 6), round(wlat, 6), '', title)

    def poi_search(self, keyword, city='', types=None, page=1, offset=20):
        if not city:
            return [], 0
        q = urllib.parse.quote(keyword or types or '地点')
        boundary = urllib.parse.quote(f'region({city},0)')
        page_size = max(1, min(int(offset), 20))
        url = (f'https://apis.map.qq.com/ws/place/v1/search?keyword={q}'
               f'&boundary={boundary}&page_size={page_size}&page_index={page}'
               f'&key={self.key}')
        d = self._call(url)
        if d is None:
            return [], 0
        pois = []
        for item in d.get('data') or []:
            location = item.get('location') or {}
            if location.get('lng') is None or location.get('lat') is None:
                continue
            lon, lat = gcj02_to_wgs84(float(location['lng']), float(location['lat']))
            ad = item.get('ad_info') or {}
            category = item.get('category') or ''
            pois.append({
                'name': item.get('title') or '',
                'address': item.get('address') or '',
                'adcode': str(ad.get('adcode') or ''),
                'pname': ad.get('province') or '',
                'cityname': ad.get('city') or '',
                'adname': ad.get('district') or '',
                'type': category,
                'typecode': '',
                'lon': round(lon, 6),
                'lat': round(lat, 6),
            })
        return pois, int(d.get('count') or len(pois))

    def around_search(self, lon, lat, radius, keyword='', types=None, page=1, offset=20):
        q = urllib.parse.quote(keyword or types or '地点')
        glon, glat = wgs84_to_gcj02(lon, lat)
        boundary = urllib.parse.quote(f'nearby({glat},{glon},{int(radius)},1)')
        size = max(1, min(int(offset), 20))
        url = (f'https://apis.map.qq.com/ws/place/v1/search?keyword={q}'
               f'&boundary={boundary}&page_size={size}&page_index={page}&key={self.key}')
        data = self._call(url)
        if data is None:
            return [], 0
        # Reuse the normalized parser by presenting the same response to a tiny local path.
        pois = []
        for item in data.get('data') or []:
            location, ad = item.get('location') or {}, item.get('ad_info') or {}
            if location.get('lng') is None or location.get('lat') is None:
                continue
            plon, plat = gcj02_to_wgs84(float(location['lng']), float(location['lat']))
            pois.append({'name': item.get('title') or '', 'address': item.get('address') or '',
                         'adcode': str(ad.get('adcode') or ''), 'pname': ad.get('province') or '',
                         'cityname': ad.get('city') or '', 'adname': ad.get('district') or '',
                         'type': item.get('category') or '', 'typecode': '',
                         'lon': round(plon, 6), 'lat': round(plat, 6)})
        return pois, int(data.get('count') or len(pois))

    def reverse_geocode(self, lon, lat):
        glon, glat = wgs84_to_gcj02(lon, lat)
        url = (f'https://apis.map.qq.com/ws/geocoder/v1/?location={glat},{glon}'
               f'&get_poi=0&key={self.key}')
        data = self._call(url)
        if data is None:
            return None
        result, comp = data.get('result') or {}, (data.get('result') or {}).get('address_component') or {}
        return {'formatted': result.get('address') or '', 'province': comp.get('province') or '',
                'city': comp.get('city') or '', 'district': comp.get('district') or '',
                'township': comp.get('street') or '', 'street': comp.get('street') or '',
                'number': comp.get('street_number') or ''}
