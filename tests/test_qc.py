# -*- coding: utf-8 -*-
"""质检引擎测试：后缀剥离 / 查询词变体 / 几何合理性（纯逻辑，不联网）。"""
from core.qc import strip_village_suffix, QcEngine
from core.engine import kw_variants
from core.store import PoiStore
from sources.base import SourceUnavailable


def test_strip_village_suffix():
    assert strip_village_suffix('张三村委会') == '张三'
    assert strip_village_suffix('李四居民委员会') == '李四'
    assert strip_village_suffix('王五社区') == '王五社区'


def test_kw_variants():
    assert '张三村委会' in kw_variants('张三村委会')
    assert '张三' in kw_variants('张三村委会')
    assert '李四社区' in kw_variants('李四居委会')
    assert kw_variants('王五村') == ['王五村']


def test_geometry_check():
    """构造 市/区县/乡镇/村 四级节点，验证几何合理性计算。"""
    nodes = [
        {'code': '450100000000', 'name': '南宁市', 'level': 2, 'parent': '450000000000',
         '经度(WGS84)': '108.3', '纬度(WGS84)': '22.8'},
        {'code': '450102000000', 'name': '兴宁区', 'level': 3, 'parent': '450100000000',
         '经度(WGS84)': '108.35', '纬度(WGS84)': '22.85'},
        {'code': '450102100000', 'name': '三塘镇', 'level': 4, 'parent': '450102000000',
         '经度(WGS84)': '108.4', '纬度(WGS84)': '22.9'},
        {'code': '450102100001', 'name': '降桥村', 'level': 5, 'parent': '450102100000',
         '经度(WGS84)': '108.41', '纬度(WGS84)': '22.91'},
    ]
    cfg = {'defaults': {}, 'keys': {}}
    geo = QcEngine(cfg).geometry_check(nodes)
    assert geo['town_seats'] == 1
    assert geo['dist_median'] < 30000  # 正常村级距镇政府 <30km
    assert len(geo['far_list']) == 0
    assert len(geo['town_far']) == 0   # 乡镇距区县 <90km


def test_total_check():
    result = {'total': 10, 'matched': 8,
              'nodes': [{'level': 3, '经度(WGS84)': '108'} for _ in range(8)],
              'targets': []}
    cfg = {'defaults': {}, 'keys': {}}
    t = QcEngine(cfg).total_check(result)
    assert t['total'] == 10
    assert t['matched'] == 8
    assert t['missing'] == 2


def test_poi_cross_check_skips_unavailable_provider(monkeypatch, tmp_path):
    class BlockedSource:
        key = 'configured'
        supports_poi = True

        def poi_search(self, *_args, **_kwargs):
            raise SourceUnavailable('HTTP 418')

    import core.qc as qc_module
    monkeypatch.setattr(qc_module, 'build_sources', lambda _cfg: {'tianditu': BlockedSource()})
    path = tmp_path / 'poi.sqlite3'
    store = PoiStore(path)
    store.insert_pois([{'key': 'one', 'name': '测试公园', 'district': '青秀区',
                        'lon': 108.3, 'lat': 22.8, 'source': 'amap'}])
    store.close()
    result = QcEngine({'defaults': {}, 'keys': {}, 'source_priority': ['tianditu']}).store_sample_verify(
        str(path), sample_count=1)
    assert result['unverified'] == 1
    assert result['providers_unavailable'] == ['tianditu']
