import csv

import pytest

from core.village_import import import_village_csv


def test_import_village_csv_atomic_validation(tmp_path):
    source = tmp_path / 'villages.csv'
    with open(source, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['编码', '名称', '乡镇编码', '数据版本'])
        writer.writeheader()
        writer.writerow({'编码': '450102001001', '名称': '甲村',
                         '乡镇编码': '450102001', '数据版本': '2023'})
    result = import_village_csv(source, '广西壮族自治区', tmp_path / 'data')
    assert result['count'] == 1
    assert result['version'] == '2023'


def test_import_village_csv_rejects_wrong_province(tmp_path):
    source = tmp_path / 'bad.csv'
    source.write_text('编码,名称\n430102001001,外省村\n', encoding='utf-8-sig')
    with pytest.raises(ValueError):
        import_village_csv(source, '广西壮族自治区', tmp_path / 'data')
    assert not (tmp_path / 'data' / 'villages' / '450000000.csv').exists()
