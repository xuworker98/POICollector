"""Generate and convert one million coordinates using the streaming pipeline."""
from __future__ import annotations

import csv
import json
import sys
import time
import tracemalloc
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
APP_SOURCE = PROJECT / 'src' / 'poi_collector'
sys.path.insert(0, str(APP_SOURCE))

from core.batch_pipeline import inspect_table, stream_coordinate_conversion


def main(rows=1_000_000):
    work = PROJECT / 'process_test' / 'million_rows'
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'input_1m.csv'
    target = work / 'output_1m.csv'
    report_path = work / 'benchmark.json'

    started = time.perf_counter()
    with open(source, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['点位名称', '源经度', '源纬度'])
        for index in range(rows):
            writer.writerow([f'P{index:07d}', 108.0 + (index % 10000) / 1_000_000,
                             22.0 + (index % 5000) / 1_000_000])
    generation_seconds = time.perf_counter() - started

    tracemalloc.start()
    started = time.perf_counter()
    result = stream_coordinate_conversion(source, target, 'WGS84', 'GCJ-02')
    conversion_seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    output_count = inspect_table(target, preview_rows=0)['count']
    report = {
        'rows': rows,
        'output_rows': output_count,
        'success': result['success'],
        'failed': result['failed'],
        'generation_seconds': round(generation_seconds, 3),
        'conversion_seconds': round(conversion_seconds, 3),
        'rows_per_second': round(rows / conversion_seconds, 1),
        'python_peak_memory_mb': round(peak / 1024 / 1024, 2),
        'input_bytes': source.stat().st_size,
        'output_bytes': target.stat().st_size,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000)
