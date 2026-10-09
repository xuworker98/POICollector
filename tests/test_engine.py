# -*- coding: utf-8 -*-
"""采集引擎多源切换测试：天地图搜不到/低分必须切高德，不能遗漏。"""
from core.engine import DivisionEngine, kw_variants


class _FakeSrc:
    """假源：按名称返回预设结果。"""
    def __init__(self, name, key='k', results=None):
        self.name = name
        self.key = key
        self.results = results or {}   # {查询词: (lon,lat,score) 或 None}

    def geocode(self, keyword, city=''):
        return self.results.get(keyword)


def _make_engine(srcs):
    e = DivisionEngine.__new__(DivisionEngine)
    e.sources = {s.name: s for s in srcs}
    e.quota = _FakeQuota(['tianditu', 'amap', 'baidu', 'tencent'])
    return e


class _FakeQuota:
    def __init__(self, source_priority):
        self.source_priority = source_priority
        self.exhausted = {s: False for s in source_priority}

    def record_call(self, s):
        pass

    def mark_exhausted(self, s):
        self.exhausted[s] = True


def test_tianditu_miss_falls_back_to_amap():
    """天地图搜不到 -> 必须切高德命中，不能遗漏。"""
    e = _make_engine([
        _FakeSrc('tianditu', results={'钦北区政府': None}),       # 搜不到
        _FakeSrc('amap', results={'钦北区政府': (108.6, 22.1, 0)}),
        _FakeSrc('baidu', results={}),
        _FakeSrc('tencent', results={}),
    ])
    r = e._geocode_with_rotation('钦北区政府', '钦州市', lambda *a: None)
    assert r is not None
    assert r[2] == 'amap'  # 高德命中


def test_tianditu_low_score_falls_back():
    """天地图低分（<90）-> 切高德。"""
    e = _make_engine([
        _FakeSrc('tianditu', results={'钦北区政府': (108.6, 22.1, 50)}),  # 低分
        _FakeSrc('amap', results={'钦北区政府': (108.6, 22.1, 0)}),
        _FakeSrc('baidu', results={}),
        _FakeSrc('tencent', results={}),
    ])
    r = e._geocode_with_rotation('钦北区政府', '钦州市', lambda *a: None)
    assert r[2] == 'amap'


def test_all_miss_returns_none():
    """所有源都搜不到 -> 返回 None。"""
    e = _make_engine([
        _FakeSrc('tianditu', results={}),
        _FakeSrc('amap', results={}),
        _FakeSrc('baidu', results={}),
        _FakeSrc('tencent', results={}),
    ])
    r = e._geocode_with_rotation('不存在的政府', '某市', lambda *a: None)
    assert r is None


def test_kw_variants_suffix():
    assert kw_variants('张三村委会') == ['张三村委会', '张三']
