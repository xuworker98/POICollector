# -*- coding: utf-8 -*-
"""从参考工作簿四张行政区划清单系统抽样，并用程序当前数据源链查询比对。"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src' / 'poi_collector'))

from core.config import build_sources, load_config
from core.coords import haversine_m
from sources.base import QuotaExceeded, SourceUnavailable

EXTRACTED_JSON = PROJECT_ROOT / 'temp' / 'spreadsheet_analysis' / 'reference' / 'values.json'
OUTPUT_JSON = PROJECT_ROOT / 'process_test' / 'reference_sample_query_results.json'
SHEET_LIMITS = {
    '地市表': 100,
    '区县表': 100,
    '乡镇表': 100,
    '行政村详细清单': 100,
}
PROVIDER_ORDER = ('tianditu', 'amap', 'baidu', 'tencent')
GUANGXI_BBOX = (104.3, 20.7, 112.2, 26.5)
_thread_local = threading.local()


def systematic_indexes(total, wanted):
    """覆盖整张表的确定性等距抽样；不足 wanted 时取全部。"""
    count = min(total, wanted)
    if count <= 0:
        return []
    if count == 1:
        return [0]
    return sorted({round(i * (total - 1) / (count - 1)) for i in range(count)})


def value(row, headers, name, default=''):
    try:
        item = row[headers.index(name)]
    except (ValueError, IndexError):
        return default
    return '' if item is None else item


def code_text(raw):
    if raw in (None, ''):
        return ''
    if isinstance(raw, float) and raw.is_integer():
        return str(int(raw))
    text = str(raw).strip()
    if 'e+' in text.lower():
        try:
            return str(int(float(text)))
        except ValueError:
            pass
    return text


def build_samples():
    payload = json.loads(EXTRACTED_JSON.read_text(encoding='utf-8'))
    samples = []
    for sheet in payload['sheets']:
        sheet_name = sheet['name']
        if sheet_name not in SHEET_LIMITS:
            continue
        rows = sheet['values']
        headers = [str(item or '').strip() for item in rows[0]]
        data_rows = rows[1:]
        for sample_no, index in enumerate(
                systematic_indexes(len(data_rows), SHEET_LIMITS[sheet_name]), start=1):
            row = data_rows[index]
            if sheet_name == '地市表':
                level, name_col, code_col = 2, '地市名称', '地市编码'
                lon_col, lat_col = '政府驻地经度(WGS84)', '政府驻地纬度(WGS84)'
            elif sheet_name == '区县表':
                level, name_col, code_col = 3, '区县名称', '区划编码'
                lon_col, lat_col = '政府驻地经度(WGS84)', '政府驻地纬度(WGS84)'
            elif sheet_name == '乡镇表':
                level, name_col, code_col = 4, '乡镇名称', '乡镇编码'
                lon_col, lat_col = '政府驻地经度(WGS84)', '政府驻地纬度(WGS84)'
            else:
                level, name_col, code_col = 5, '行政村名称', '行政村编码'
                lon_col, lat_col = '经度(WGS84)', '纬度(WGS84)'
            samples.append({
                'sheet': sheet_name,
                'sample_no': sample_no,
                'source_row': index + 2,
                'level': level,
                'province': str(value(row, headers, '省份名称')),
                'city': str(value(row, headers, '地市名称')),
                'district': str(value(row, headers, '区县名称')),
                'town': str(value(row, headers, '乡镇名称')),
                'name': str(value(row, headers, name_col)),
                'code': code_text(value(row, headers, code_col)),
                'reference_address': str(value(row, headers, '政府驻地地址')),
                'reference_lon': float(value(row, headers, lon_col)),
                'reference_lat': float(value(row, headers, lat_col)),
                'reference_source': str(value(row, headers, '数据来源')),
            })
    return samples


def query_variants(sample):
    ancestor_fields = {
        2: ('province',),
        3: ('province', 'city'),
        4: ('province', 'city', 'district'),
        5: ('province', 'city', 'district', 'town'),
    }[sample['level']]
    hierarchy = ''.join(sample[field] for field in ancestor_fields if sample[field])
    name = sample['name']
    variants = []
    if sample['level'] <= 4:
        variants.extend((f'{hierarchy}{name}人民政府', f'{name}人民政府'))
    variants.extend((f'{hierarchy}{name}', name))
    suffixes = ('村民委员会', '居民委员会', '村委会', '居委会')
    for suffix in suffixes:
        if name.endswith(suffix):
            base = name[:-len(suffix)]
            variants.extend((f'{hierarchy}{base}', base))
            break
    return list(dict.fromkeys(item for item in variants if item))


def sources_for_thread():
    if not hasattr(_thread_local, 'sources'):
        _thread_local.sources = build_sources(load_config())
    return _thread_local.sources


def within_guangxi(result):
    lon, lat = float(result[0]), float(result[1])
    return GUANGXI_BBOX[0] <= lon <= GUANGXI_BBOX[2] \
        and GUANGXI_BBOX[1] <= lat <= GUANGXI_BBOX[3]


def query_one(sample):
    sources = sources_for_thread()
    errors = []
    for keyword in query_variants(sample):
        for provider in PROVIDER_ORDER:
            source = sources.get(provider)
            if source is None or not source.key or not source.supports_geocode:
                continue
            try:
                result = source.geocode(keyword, city=sample['city'])
            except QuotaExceeded as exc:
                errors.append(f'{provider}:quota:{exc}')
                continue
            except SourceUnavailable as exc:
                errors.append(f'{provider}:network:{exc}')
                continue
            except Exception as exc:
                errors.append(f'{provider}:error:{type(exc).__name__}')
                continue
            if not result or not within_guangxi(result):
                continue
            if provider == 'tianditu' and len(result) > 2 \
                    and isinstance(result[2], (int, float)) and result[2] < 90:
                continue
            lon, lat = float(result[0]), float(result[1])
            distance = haversine_m(
                sample['reference_lon'], sample['reference_lat'], lon, lat,
            )
            return {
                **sample,
                'query_keyword': keyword,
                'query_lon': round(lon, 6),
                'query_lat': round(lat, 6),
                'provider': provider,
                'provider_detail': str(result[3]) if len(result) > 3 else '',
                'distance_m': round(distance, 3),
                'matched': True,
                'errors': errors,
            }
    return {
        **sample,
        'query_keyword': '', 'query_lon': None, 'query_lat': None,
        'provider': '', 'provider_detail': '', 'distance_m': None,
        'matched': False, 'errors': errors,
    }


def main():
    samples = build_samples()
    print(f'samples={len(samples)}', flush=True)
    completed = []
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(query_one, sample): sample for sample in samples}
        for done, future in enumerate(as_completed(futures), start=1):
            completed.append(future.result())
            if done % 10 == 0 or done == len(samples):
                completed.sort(key=lambda row: (
                    list(SHEET_LIMITS).index(row['sheet']), row['sample_no'],
                ))
                OUTPUT_JSON.write_text(
                    json.dumps({'results': completed}, ensure_ascii=False, indent=1),
                    encoding='utf-8',
                )
                print(f'progress={done}/{len(samples)}', flush=True)
    matched = sum(1 for row in completed if row['matched'])
    under_300 = sum(1 for row in completed if row['distance_m'] is not None and row['distance_m'] <= 300)
    print(f'matched={matched} under_300m={under_300}', flush=True)


if __name__ == '__main__':
    main()
