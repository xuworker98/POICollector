# -*- coding: utf-8 -*-
"""数据源抽象基类 + 限速器 + HTTP 封装"""
import random
import time

import requests


class QuotaExceeded(Exception):
    """日配额用尽 / QPS 持续超限（触发停机或换源）"""


class SourceUnavailable(RuntimeError):
    """数据源暂时不可用或拒绝请求，可安全切换到下一图源。"""


class HttpRequestError(SourceUnavailable):
    """HTTP 请求最终失败；错误信息不包含可能携带 KEY 的完整 URL。"""

    def __init__(self, message, status_code=None, response_excerpt=''):
        super().__init__(message)
        self.status_code = status_code
        self.response_excerpt = response_excerpt


class RateLimiter:
    """请求最小间隔限速器。

    经验值：高德 0.42s / 天地图 0.36s / 民政部 0.40s。
    """

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self):
        now = time.time()
        d = now - self._last
        if d < self.min_interval:
            time.sleep(self.min_interval - d + random.random() * 0.05)
        self._last = time.time()


def http_get_json(url, headers=None, timeout=15, retries=3, raise_last=False, verify=True):
    """带重试的 GET JSON。

    默认保持旧行为（最终失败返回 ``None``）。诊断要求较高的调用方可设置
    ``raise_last=True``，此时抛出的异常会隐藏完整 URL，避免日志泄露 KEY。
    """
    last_error = None
    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout, verify=verify)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last_error = exc
            response = getattr(exc, 'response', None)
            status = getattr(response, 'status_code', None)
            # 权限、参数和 CloudWAF 拒绝不会因原样重试而恢复，立即换源。
            if raise_last and status in {400, 401, 403, 404, 418}:
                excerpt = (getattr(response, 'text', '') or '')[:160]
                raise HttpRequestError(
                    f'HTTP {status}，服务端拒绝或网络出口被拦截', status, excerpt,
                ) from None
            if i == retries - 1:
                if not raise_last:
                    return None
                excerpt = ''
                if response is not None:
                    excerpt = (getattr(response, 'text', '') or '')[:160]
                if status:
                    raise HttpRequestError(
                        f'HTTP {status}，服务端拒绝或网络出口被拦截', status, excerpt,
                    ) from None
                raise HttpRequestError(f'网络请求失败：{type(exc).__name__}') from None
            time.sleep(1.5 * (i + 1) + random.random())
    if raise_last and last_error:
        raise HttpRequestError(f'网络请求失败：{type(last_error).__name__}') from None
    return None


class SourceBase:
    """四源抽象基类。子类实现 geocode / poi_search，内部负责各自坐标系归一为 WGS84。"""

    name = "base"
    crs = "WGS84"  # 原始坐标系：CGCS2000 / GCJ-02 / BD-09
    supports_geocode = False
    supports_poi = False
    supports_around = False
    supports_reverse = False

    def __init__(self, key, rate_limit_sec=0.4):
        self.key = key
        self.limiter = RateLimiter(rate_limit_sec)

    def geocode(self, address, city=""):
        """地理编码：返回 (wgs84_lon, wgs84_lat, level, formatted) 或 None；配额用尽抛 QuotaExceeded。"""
        raise NotImplementedError

    def poi_search(self, keyword, city="", types=None, page=1, offset=100):
        """POI 搜索：返回 (pois, total_count)，pois 为已转 WGS84 的 dict 列表。"""
        raise NotImplementedError

    def around_search(self, lon, lat, radius, keyword='', types=None, page=1, offset=100):
        """中心点周边搜索；keyword 是目标 POI，types 仅为可选过滤。"""
        raise NotImplementedError
