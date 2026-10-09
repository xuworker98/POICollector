# -*- coding: utf-8 -*-
"""Validated import for authoritative 12-digit village-level division CSV."""
from __future__ import annotations

import csv
import os
from pathlib import Path

from core.region import PROVINCES

OUTPUT_FIELDS = ['编码', '名称', '乡镇编码', '地市名称', '区县名称', '乡镇名称', '数据版本']


def import_village_csv(source_path, province_name, data_dir, data_version='用户导入'):
    province_code = PROVINCES.get(province_name, '')
    if not province_code:
        raise ValueError(f'未知省份：{province_name}')
    prefix = province_code[:2]
    normalized = []
    invalid = []
    seen = set()
    with open(source_path, 'r', encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        for line, row in enumerate(reader, 2):
            code = str(row.get('编码') or row.get('行政村编码') or row.get('code') or '').strip()
            name = str(row.get('名称') or row.get('行政村名称') or row.get('name') or '').strip()
            if not (code.isdigit() and len(code) == 12 and code.startswith(prefix) and name):
                invalid.append({'行': line, '编码': code, '名称': name, '原因': '须为本省12位数字编码且名称非空'})
                continue
            if code in seen:
                invalid.append({'行': line, '编码': code, '名称': name, '原因': '编码重复'})
                continue
            seen.add(code)
            parent = str(row.get('乡镇编码') or row.get('parent') or code[:9]).strip()
            if not (parent.isdigit() and len(parent) == 9 and code.startswith(parent)):
                invalid.append({'行': line, '编码': code, '名称': name, '原因': '乡镇编码须为前9位父编码'})
                continue
            normalized.append({
                '编码': code, '名称': name, '乡镇编码': parent,
                '地市名称': row.get('地市名称') or row.get('city_name') or '',
                '区县名称': row.get('区县名称') or row.get('district_name') or '',
                '乡镇名称': row.get('乡镇名称') or row.get('town_name') or '',
                '数据版本': row.get('数据版本') or row.get('data_version') or data_version,
            })
    if not normalized:
        raise ValueError('没有通过校验的村级记录')
    if invalid:
        raise ValueError(f'发现 {len(invalid)} 条无效记录，示例：{invalid[:3]}；未导入任何数据')
    target = Path(data_dir) / 'villages' / f'{province_code}.csv'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix('.csv.tmp')
    with open(temporary, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(normalized)
    os.replace(temporary, target)
    return {'path': str(target), 'count': len(normalized), 'province': province_name,
            'version': normalized[0]['数据版本']}
