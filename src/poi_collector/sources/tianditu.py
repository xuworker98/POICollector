# -*- coding: utf-8 -*-
"""天地图服务端数据源（CGCS2000）。

优先使用官方地名搜索 V2.0（``/v2/search``），并兼容旧版地理编码
``/geocoder``。服务端 KEY 不发送浏览器 Referer，也不伪装浏览器 UA。
"""
import json
import urllib.parse
import warnings

from core.coords import cgcs2000_to_wgs84
from .base import (
    SourceBase, QuotaExceeded, SourceUnavailable, HttpRequestError, http_get_json,
)

TIANDITU_QUOTA_CODES = {301001, 301002, 301003, 301004, 301005}
TIANDITU_NO_DATA_CODES = {3001}


class TiandituServiceError(SourceUnavailable):
    """天地图已返回响应，但参数、权限或服务状态异常。"""


class TiandituSource(SourceBase):
    name = 'tianditu'
    crs = 'CGCS2000'
    supports_geocode = True
    supports_poi = True
    supports_around = True

    def __init__(self, key, rate_limit_sec=0.4):
        super().__init__(key, rate_limit_sec)
        self._blocked_reason = None

    def _request(self, endpoint, params):
        if self._blocked_reason:
            raise self._blocked_reason
        self.limiter.wait()
        query = urllib.parse.urlencode(params)
        url = f'https://api.tianditu.gov.cn{endpoint}?{query}'
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                data = http_get_json(
                    url,
                    headers={'Accept': 'application/json', 'User-Agent': ''},
                    raise_last=True,
                    verify=False,
                )
        except HttpRequestError as exc:
            if exc.status_code == 418:
                self._blocked_reason = HttpRequestError(
                    'HTTP 418（天地图 CloudWAF 拦截；请关闭境外 VPN 后重试）',
                    418,
                )
                raise self._blocked_reason from exc
            raise
        if not isinstance(data, dict):
            raise TiandituServiceError('天地图响应不是有效 JSON 对象')
        self._validate_response(data)
        return data

    @staticmethod
    def _response_status(data):
        status = data.get('status')
        if isinstance(status, list):
            status = status[0] if status else {}
        if not isinstance(status, dict):
            status = {}
        raw_code = data.get('code', status.get('infocode'))
        try:
            code = int(raw_code) if raw_code not in (None, '') else None
        except (TypeError, ValueError):
            code = raw_code
        message = (
            data.get('msg') or status.get('cndesc') or status.get('info') or
            data.get('message') or ''
        )
        return code, str(message)

    @classmethod
    def _validate_response(cls, data):
        code, message = cls._response_status(data)
        if code in (None, 0, 1000) or code in TIANDITU_NO_DATA_CODES:
            return
        if code in TIANDITU_QUOTA_CODES:
            raise QuotaExceeded(f'天地图配额/限流：{code} {message}'.strip())
        raise TiandituServiceError(f'天地图返回 {code}：{message or "权限或参数异常"}')

    def _v2_search(self, keyword, city='', page=1, count=20):
        count = max(1, min(int(count), 300))
        start = max(0, (max(1, int(page)) - 1) * count)
        request_data = {
            'keyWord': keyword,
            'queryType': 12 if city else 1,
            'start': start,
            'count': count,
            'show': 2,
        }
        if city:
            request_data['specify'] = city
        else:
            request_data.update({'level': 12, 'mapBound': '-180,-90,180,90'})
        return self._request('/v2/search', {
            'postStr': json.dumps(request_data, ensure_ascii=False, separators=(',', ':')),
            'type': 'query',
            'tk': self.key,
        })

    @staticmethod
    def _parse_v2_pois(data):
        parsed = []
        for item in data.get('pois') or []:
            lonlat = str(item.get('lonlat') or '').split(',')
            if len(lonlat) != 2:
                continue
            try:
                lon, lat = map(float, lonlat)
                wlon, wlat = cgcs2000_to_wgs84(lon, lat)
            except (TypeError, ValueError):
                continue
            parsed.append({
                'name': item.get('name') or '',
                'address': item.get('address') or '',
                'adcode': str(item.get('countyCode') or item.get('adminCode') or ''),
                'pname': item.get('province') or '',
                'cityname': item.get('city') or '',
                'adname': item.get('county') or '',
                'type': item.get('typeName') or '',
                'typecode': item.get('typeCode') or '',
                'lon': round(wlon, 6),
                'lat': round(wlat, 6),
            })
        return parsed

    @staticmethod
    def _match_score(keyword, item):
        expected = ''.join(str(keyword).split())
        actual = ''.join(str(item.get('name') or '').split())
        if actual == expected:
            return 100
        if expected and (expected in actual or actual in expected):
            return 95
        return 80

    def geocode(self, keyword, city=''):
        """地理编码；实测旧版 geocoder 优先，V2 搜索作为兼容补充。"""
        first_error = None
        legacy_data = {'keyWord': keyword}
        if city:
            legacy_data['city'] = city
        try:
            data = self._request('/geocoder', {
                'ds': json.dumps(legacy_data, ensure_ascii=False, separators=(',', ':')),
                'tk': self.key,
            })
        except (HttpRequestError, TiandituServiceError) as exc:
            first_error = exc
        else:
            location = data.get('location')
            if isinstance(location, dict) and location.get('lon') is not None \
                    and location.get('lat') is not None:
                lon, lat = cgcs2000_to_wgs84(float(location['lon']), float(location['lat']))
                return (
                    round(lon, 6), round(lat, 6), int(location.get('score') or 0),
                    location.get('level') or '',
                )

        if isinstance(first_error, HttpRequestError) and first_error.status_code == 418:
            raise first_error
        try:
            data = self._v2_search(keyword, city=city, page=1, count=10)
            pois = self._parse_v2_pois(data)
            if pois:
                best = max(pois, key=lambda item: self._match_score(keyword, item))
                return (
                    best['lon'], best['lat'], self._match_score(keyword, best),
                    best['address'] or best['name'],
                )
        except (HttpRequestError, TiandituServiceError):
            if first_error is not None:
                raise first_error
            raise
        return None

    def poi_search(self, keyword, city='', types=None, page=1, offset=100):
        """官方 V2 行政区域/分类搜索。"""
        if types:
            count = max(1, min(int(offset), 300))
            request_data = {'keyWord': keyword or '', 'queryType': 13, 'start': (page - 1) * count,
                            'count': count, 'show': 2, 'specify': city, 'dataTypes': types}
            data = self._request('/v2/search', {'postStr': json.dumps(request_data, ensure_ascii=False, separators=(',', ':')),
                                                'type': 'query', 'tk': self.key})
        else:
            data = self._v2_search(keyword, city=city, page=page, count=offset)
        pois = self._parse_v2_pois(data)
        try:
            total = int(data.get('count') or len(pois))
        except (TypeError, ValueError):
            total = len(pois)
        return pois, total

    def around_search(self, lon, lat, radius, keyword='', types=None, page=1, offset=100):
        if int(radius) > 10000:
            raise SourceUnavailable('天地图周边搜索最大半径为10000米，已切换备用查询源')
        count = max(1, min(int(offset), 300))
        request_data = {'keyWord': keyword or '', 'queryType': 3, 'start': (page - 1) * count,
                        'count': count, 'show': 2, 'pointLonlat': f'{lon},{lat}',
                        'queryRadius': int(radius)}
        if types:
            request_data['dataTypes'] = types
        data = self._request('/v2/search', {'postStr': json.dumps(request_data, ensure_ascii=False, separators=(',', ':')),
                                            'type': 'query', 'tk': self.key})
        pois = self._parse_v2_pois(data)
        try:
            total = int(data.get('count') or len(pois))
        except (TypeError, ValueError):
            total = len(pois)
        return pois, total
