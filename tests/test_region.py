# -*- coding: utf-8 -*-
"""M3 区划框架 + Excel 输出 单测（纯逻辑，mock 网络）"""
import os

from core.region import pad_code, PROVINCES, RegionFetcher, load_villages
from core.excel_out import build_division_tables, build_report_text


def test_pad_code_right_pad():
    """9位码右侧补零（不是 zfill 左侧补零）"""
    assert pad_code('4501') == '450100000'
    assert pad_code(4501) == '450100000'
    assert pad_code('450100') == '450100000'


def test_provinces_count():
    assert len(PROVINCES) == 34
    assert PROVINCES['广西壮族自治区'] == '450000000'
    assert PROVINCES['湖南省'] == '430000000'


def test_build_tree_bfs(tmp_path):
    """mock fetch_children，验证 BFS 下钻 + 右侧补零 + 缓存写盘"""
    fetcher = RegionFetcher(cache_dir=str(tmp_path))

    fake = {
        '450000000': [{'code': '4501', 'name': '南宁市', 'level': 2},
                      {'code': '4502', 'name': '柳州市', 'level': 2}],
        '450100000': [{'code': '450102', 'name': '兴宁区', 'level': 3}],
        '450200000': [{'code': '450202', 'name': '城中区', 'level': 3}],
        '450102000': [{'code': '450102001', 'name': '某街道', 'level': 4}],
        '450202000': [],
    }

    def fake_fetch(parent_code, parent_name='', parent_level=1, **kw):
        return fake.get(parent_code, [])

    fetcher.fetch_children = fake_fetch
    nodes = fetcher.build_tree('450000000', max_level=4)

    codes = [n['code'] for n in nodes]
    assert '450100000' in codes  # 南宁市（右侧补零）
    assert '450102000' in codes  # 兴宁区
    assert '450102001' in codes  # 某街道
    assert os.path.exists(fetcher.cache_path('450000000'))  # 缓存已写


def test_build_tree_cache_hit(tmp_path):
    """缓存命中：第二次 build_tree 不再走网络"""
    fetcher = RegionFetcher(cache_dir=str(tmp_path))
    calls = {'n': 0}

    def fake_fetch(parent_code, parent_name='', parent_level=1, **kw):
        calls['n'] += 1
        if parent_code == '450000000':
            return [{'code': '4501', 'name': '南宁市', 'level': 2}]  # 返回 1 个地市，缓存 >1 节点
        return []

    fetcher.fetch_children = fake_fetch
    fetcher.build_tree('450000000', max_level=4)
    first_calls = calls['n']
    fetcher.build_tree('450000000', max_level=4)
    assert calls['n'] == first_calls  # 第二次命中缓存，无新网络请求


def test_load_villages(tmp_path):
    csv_path = os.path.join(tmp_path, 'v.csv')
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write('编码,名称\n450102001,某村\n450102002,某二村\n')
    villages = load_villages(csv_path)
    assert len(villages) == 2
    assert villages[0]['code'] == '450102001000'
    assert villages[0]['parent'] == '450102001'
    assert villages[0]['level'] == 5


def test_build_division_tables():
    nodes = {
        2: [{'code': '450100000', 'name': '南宁市', 'parent': '450000000'}],
        3: [{'code': '450102000', 'name': '兴宁区', 'parent': '450100000'}],
        4: [{'code': '450102001', 'name': '某街道', 'parent': '450102000'}],
    }
    villages = [{'code': '450102001001', 'name': '某村', '经度(WGS84)': 108.3, '纬度(WGS84)': 22.8}]
    tables = build_division_tables(nodes, villages)
    assert '地市表' in tables
    assert '汇总表' in tables
    assert '校验表' in tables
    summary = tables['汇总表']
    assert summary.iloc[-1]['地市'] == '合计'


def test_build_report_text():
    txt = build_report_text('广西区划', {'村级总数': 16681}, {'区划': '民政部20251231'})
    assert '广西区划' in txt
    assert '16681' in txt
    assert 'WGS84' in txt


def test_mca_uses_form_post_and_normalizes(monkeypatch, tmp_path):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {'data': [
                {'code': '45', 'name': '广西壮族自治区'},
                {'code': '450100', 'name': '南宁市'},
            ]}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr('core.region.requests.post', fake_post)
    fetcher = RegionFetcher(str(tmp_path), rate_limit=0)
    rows = fetcher._fetch_mca('450000000', 1, 'Xzqh20251231', 500)
    assert captured['data']['parentCode'] == '45'
    assert 'json' not in captured
    assert captured['verify'] is False
    assert rows == [{'code': '450100', 'name': '南宁市', 'level': 2,
                     'source': '民政部国家地名信息库'}]


def test_reference_cache_has_priority(tmp_path):
    reference = tmp_path / '450000000_reference_v1.json'
    ordinary = tmp_path / '450000000.json'
    reference.write_text('{}', encoding='utf-8')
    ordinary.write_text('{}', encoding='utf-8')
    assert RegionFetcher(str(tmp_path)).cache_path('450000000') == str(reference)


def test_reference_template_headers():
    tables = build_division_tables({
        1: [{'code': '450000000', 'name': '广西壮族自治区', 'level': 1}],
        2: [], 3: [], 4: [], 5: [],
    })
    assert list(tables) == ['地市表', '区县表', '乡镇表', '行政村详细清单', '汇总表', '校验表']
    assert tables['行政村详细清单'].headers == [
        '省份名称', '省份编码', '地市名称', '地市编码', '区县名称', '区县编码',
        '乡镇名称', '乡镇编码', '行政村名称', '行政村编码', '村级分类',
        '经度(WGS84)', '纬度(WGS84)', '数据来源',
    ]
