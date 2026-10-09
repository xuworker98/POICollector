from core.search import PoiSearchEngine
from sources.base import SourceUnavailable


def test_poi_search_returns_before_qc_and_skips_blocked_source(monkeypatch, tmp_path):
    class Blocked:
        key = 'key'
        supports_poi = True

        def __init__(self):
            self.calls = 0

        def poi_search(self, *_args, **_kwargs):
            self.calls += 1
            raise SourceUnavailable('HTTP 418')

    class Working:
        key = 'key'
        supports_poi = True

        def poi_search(self, _query, city, types=None, page=1, offset=20):
            return ([{'name': f'POI-{types}', 'type': '景点', 'typecode': types,
                      'adname': city, 'adcode': '450103', 'lon': 108.3, 'lat': 22.8,
                      'address': '测试地址'}], 1)

    blocked = Blocked()
    monkeypatch.setattr('core.search.build_sources',
                        lambda _cfg: {'tianditu': blocked, 'amap': Working()})
    cfg = {
        'keys': {'tianditu': 'key', 'amap': 'key'},
        'source_priority': ['tianditu', 'amap'],
        'defaults': {'daily_caps': {'tianditu': 100, 'amap': 100}},
    }
    engine = PoiSearchEngine(cfg, '广西壮族自治区', ['110101', '110102'], '',
                             str(tmp_path), str(tmp_path), city_name='南宁市')
    monkeypatch.setattr(engine, '_load_districts',
                        lambda: [{'code': '450103', 'name': '青秀区', 'city': '南宁市'}])
    result = engine.run(lambda *_: None, lambda *_: None, lambda *_: None,
                        lambda *_: None, lambda: False)
    assert result['matched'] == 2
    assert result['qc_pending'] is True
    assert 'qc' not in result
    assert blocked.calls == 1
