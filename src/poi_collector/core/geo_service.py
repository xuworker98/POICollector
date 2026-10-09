# -*- coding: utf-8 -*-
"""地理编码统一服务层：多 provider 自动切换 + 三级解析策略。

供「地址坐标互转」「周边搜索」「分类搜索」共用。
所有坐标统一为 WGS84，输出时再按需转换。
"""
from core.config import load_config, build_sources
from core.coords import convert_coord
from sources.base import QuotaExceeded, SourceUnavailable

_SOURCE_CACHE = {}


def _get_sources(preferred='amap', capability='supports_geocode'):
    """Build configured providers and order by preference and configured priority."""
    cfg = load_config()
    signature = tuple((name, cfg.get('keys', {}).get(name, ''))
                      for name in ('tianditu', 'amap', 'baidu', 'tencent'))
    cache_key = (signature, preferred, capability)
    if cache_key in _SOURCE_CACHE:
        return _SOURCE_CACHE[cache_key]
    built = build_sources(cfg)
    priority = cfg.get('source_priority') or list(built)
    sources = [built[name] for name in priority
               if name in built and built[name].key and getattr(built[name], capability, False)]
    sources.sort(key=lambda source: source.name != preferred)
    _SOURCE_CACHE.clear()  # keep only the active key set; never retain old keys
    _SOURCE_CACHE[cache_key] = sources
    return sources


def clear_source_cache():
    _SOURCE_CACHE.clear()


def geocode_full(address, city='', preferred='tianditu'):
    """地址 -> 坐标。返回 WGS84/GCJ02/BD09 三套坐标 + 标准地址 + 来源 provider。"""
    sources = _get_sources(preferred, 'supports_geocode')
    for src in sources:
        try:
            res = src.geocode(address, city)
        except (QuotaExceeded, SourceUnavailable):
            continue
        if res is None:
            continue
        wlon, wlat, _level, formatted = res
        return {
            'wgs84': (wlon, wlat),
            'gcj02': convert_coord(wlon, wlat, 'GCJ-02'),
            'bd09': convert_coord(wlon, wlat, 'BD-09'),
            'formatted': formatted,
            'provider': src.name,
        }
    return None


def reverse_full(lon, lat, preferred='tianditu'):
    """坐标 -> 结构化地址（多 provider 自动切换）。"""
    sources = _get_sources(preferred, 'supports_reverse')
    for src in sources:
        try:
            res = src.reverse_geocode(lon, lat)
        except (QuotaExceeded, SourceUnavailable):
            continue
        if res:
            res['provider'] = src.name
            return res
    return None


def around_search(lon, lat, radius, keyword='', types=None, category_names=None, preferred='tianditu',
                  offset=20, progress_cb=None, cancel_cb=None, max_pages=100):
    """周边搜索（多 provider）。返回 (pois, total, provider)。"""
    sources = _get_sources(preferred, 'supports_around')
    for src in sources:
        try:
            collected, total = [], 0
            names = ','.join(category_names or [])
            queries = [(keyword, types)]
            if src.name == 'tianditu':
                queries = [('', names)]
            elif src.name in ('baidu', 'tencent'):
                queries = [(name, None) for name in (category_names or [])] or [(keyword, None)]
            for provider_keyword, provider_types in queries:
                page, query_total = 1, 0
                while page <= max_pages and not (cancel_cb and cancel_cb()):
                    pois, query_total = src.around_search(
                        lon, lat, radius, keyword=provider_keyword, types=provider_types,
                        page=page, offset=offset)
                    if not pois:
                        break
                    collected.extend(pois)
                    if progress_cb:
                        progress_cb(len(collected), max(total + query_total, len(collected)), src.name)
                    if page * offset >= query_total:
                        break
                    page += 1
                total += query_total
        except (QuotaExceeded, SourceUnavailable):
            continue
        if collected:
            return _deduplicate(collected), total, src.name
    return [], 0, ''


def text_search(keyword, city='', types=None, preferred='tianditu', offset=20,
                progress_cb=None, cancel_cb=None, max_pages=100):
    """文本/分类搜索（多 provider）。返回 (pois, total, provider)。"""
    sources = _get_sources(preferred, 'supports_poi')
    for src in sources:
        try:
            collected, page, total = [], 1, 0
            while page <= max_pages and not (cancel_cb and cancel_cb()):
                pois, total = src.poi_search(keyword, city, types=types,
                                             page=page, offset=offset)
                if not pois:
                    break
                collected.extend(pois)
                if progress_cb:
                    progress_cb(len(collected), max(total, len(collected)), src.name)
                if page * offset >= total:
                    break
                page += 1
        except (QuotaExceeded, SourceUnavailable):
            continue
        if collected:
            return _deduplicate(collected), total, src.name
    return [], 0, ''


def _deduplicate(items):
    seen, output = set(), []
    for item in items:
        key = (str(item.get('name', '')).strip(), str(item.get('adcode', '')).strip(),
               round(float(item.get('lon') or 0), 5), round(float(item.get('lat') or 0), 5))
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output


def geocode_with_fallback(address, city='', province='', preferred='tianditu'):
    """三级解析策略：原始地址 -> 拼接省市区 -> 失败返回 None。"""
    # 级别1：原始地址 + city 限定
    r = geocode_full(address, city, preferred)
    if r:
        return r
    # 级别2：拼接省市区
    parts = [p for p in [province, city, address] if p]
    full = ''.join(parts)
    if full != address:
        r = geocode_full(full, city, preferred)
        if r:
            return r
    return None
