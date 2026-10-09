import os

from core.store import PoiStore
from core.qc import QcEngine


def test_poi_store_dedup_and_resume(tmp_path):
    path = tmp_path / 'poi.sqlite3'
    store = PoiStore(path)
    rows = [{
        'key': 'a', 'name': '学校A', 'type': '学校', 'district': '青秀区',
        'lon': 108.3, 'lat': 22.8, 'source': 'amap',
    }, {
        'key': 'a', 'name': '学校A', 'type': '学校', 'district': '青秀区',
        'lon': 108.3, 'lat': 22.8, 'source': 'amap',
    }]
    assert store.insert_pois(rows) == 1
    store.mark_task_done('district:type', 'amap', 1)
    assert store.count() == 1
    store.close()

    reopened = PoiStore(path)
    assert reopened.task_done('district:type')
    assert reopened.count() == 1
    assert reopened.preview(10)[0]['name'] == '学校A'
    reopened.close()


def test_poi_store_summary(tmp_path):
    store = PoiStore(tmp_path / 'summary.sqlite3')
    store.insert_pois([
        {'key': 'a', 'name': 'A', 'district': '甲区', 'lon': 1, 'lat': 1},
        {'key': 'b', 'name': 'B', 'district': '甲区', 'lon': 2, 'lat': 2},
        {'key': 'c', 'name': 'C', 'district': '乙区', 'lon': 3, 'lat': 3},
    ])
    assert dict(store.summary()) == {'甲区': 2, '乙区': 1}
    store.close()


def test_store_cross_sample_promotes_agreeing_point(tmp_path, monkeypatch):
    path = tmp_path / 'qc.sqlite3'
    store = PoiStore(path)
    store.insert_pois([{
        'key': 'a', 'name': '学校A', 'district': '青秀区',
        'lon': 108.3000, 'lat': 22.8000, 'source': 'amap', 'confidence': '中',
    }])
    store.close()

    class FakeSource:
        key = 'configured'
        supports_poi = True

        def poi_search(self, keyword, city='', page=1, offset=20):
            return ([{'name': '学校A', 'adname': '青秀区',
                      'lon': 108.3001, 'lat': 22.8001}], 1)

    monkeypatch.setattr('core.qc.build_sources', lambda cfg: {'baidu': FakeSource()})
    cfg = {'keys': {}, 'defaults': {}, 'source_priority': ['baidu']}
    result = QcEngine(cfg).store_sample_verify(path, sample_count=10)
    assert result['high'] == 1
    reopened = PoiStore(path)
    assert reopened.preview(1)[0]['置信度'] == '高'
    reopened.close()
