# -*- coding: utf-8 -*-
"""使用独立百度通道复核参考表与程序查询偏差大于 300 米的样本。"""
from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / 'src' / 'poi_collector'))
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from compare_reference_samples import query_variants
from core.config import build_sources, load_config
from core.coords import haversine_m
from sources.base import QuotaExceeded, SourceUnavailable

INPUT_JSON = PROJECT_ROOT / 'process_test' / 'reference_sample_query_results.json'
OUTPUT_JSON = PROJECT_ROOT / 'process_test' / 'reference_sample_query_results_crosschecked.json'
_local = threading.local()


def baidu_source():
    if not hasattr(_local, 'source'):
        _local.source = build_sources(load_config())['baidu']
    return _local.source


def crosscheck(row):
    result = dict(row)
    result.update({
        'cross_provider': '', 'cross_lon': None, 'cross_lat': None,
        'cross_to_reference_m': None, 'cross_to_program_m': None,
        'analysis': '',
    })
    if row.get('distance_m') is None or row['distance_m'] <= 300:
        result['analysis'] = '程序与参考表一致（≤300m）'
        return result
    source = baidu_source()
    for keyword in query_variants(row):
        try:
            found = source.geocode(keyword, city=row['city'])
        except (QuotaExceeded, SourceUnavailable):
            continue
        if not found:
            continue
        lon, lat = float(found[0]), float(found[1])
        d_ref = haversine_m(row['reference_lon'], row['reference_lat'], lon, lat)
        d_program = haversine_m(row['query_lon'], row['query_lat'], lon, lat)
        result.update({
            'cross_provider': 'baidu',
            'cross_lon': round(lon, 6), 'cross_lat': round(lat, 6),
            'cross_to_reference_m': round(d_ref, 3),
            'cross_to_program_m': round(d_program, 3),
        })
        if d_ref <= 300 < d_program:
            result['analysis'] = '独立百度更支持参考表坐标'
        elif d_program <= 300 < d_ref:
            result['analysis'] = '独立百度更支持程序查询坐标'
        elif d_ref <= 300 and d_program <= 300:
            result['analysis'] = '三者基本一致'
        elif d_ref + 200 < d_program:
            result['analysis'] = '独立百度较接近参考表，建议保留参考值'
        elif d_program + 200 < d_ref:
            result['analysis'] = '独立百度较接近程序，建议复核参考值'
        else:
            result['analysis'] = '独立源仍有分歧，需人工/边界复核'
        return result
    result['analysis'] = '百度未命中，暂无法独立裁决'
    return result


def main():
    rows = json.loads(INPUT_JSON.read_text(encoding='utf-8'))['results']
    checked = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(crosscheck, row): row for row in rows}
        for done, future in enumerate(as_completed(futures), start=1):
            checked.append(future.result())
            if done % 25 == 0 or done == len(rows):
                print(f'progress={done}/{len(rows)}', flush=True)
    checked.sort(key=lambda row: (
        ('地市表', '区县表', '乡镇表', '行政村详细清单').index(row['sheet']),
        row['sample_no'],
    ))
    OUTPUT_JSON.write_text(
        json.dumps({'results': checked}, ensure_ascii=False, indent=1), encoding='utf-8',
    )
    print('saved', OUTPUT_JSON, flush=True)


if __name__ == '__main__':
    main()
