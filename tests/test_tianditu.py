import pytest

import sources.tianditu as module
from sources.base import QuotaExceeded
from sources.tianditu import TiandituServiceError, TiandituSource


def test_v2_geocode_and_poi(monkeypatch):
    payload = {
        'status': {'infocode': 1000, 'cndesc': 'OK'},
        'count': 1,
        'pois': [{
            'name': '北京市人民政府', 'lonlat': '116.4074,39.9042',
            'address': '北京市通州区', 'province': '北京市',
            'city': '北京市', 'county': '通州区', 'countyCode': '110112',
        }],
    }
    monkeypatch.setattr(module, 'http_get_json', lambda *a, **k: payload)
    source = TiandituSource('test-key', 0)
    result = source.geocode('北京市人民政府', '北京市')
    assert result[:3] == (116.4074, 39.9042, 100)
    pois, total = source.poi_search('人民政府', '通州区', offset=20)
    assert total == 1
    assert pois[0]['adname'] == '通州区'


def test_legacy_geocoder_fallback(monkeypatch):
    def fake_get(url, **kwargs):
        if '/v2/search' in url:
            return {'status': {'infocode': 3001, 'cndesc': '没有找到数据'}, 'pois': []}
        return {'location': {'lon': 108.3, 'lat': 22.8, 'score': 96, 'level': '区县'}}

    monkeypatch.setattr(module, 'http_get_json', fake_get)
    result = TiandituSource('test-key', 0).geocode('测试地点', '南宁市')
    assert result == (108.3, 22.8, 96, '区县')


def test_response_status_classification():
    with pytest.raises(QuotaExceeded):
        TiandituSource._validate_response({'code': 301001, 'msg': '次数超限'})
    with pytest.raises(TiandituServiceError):
        TiandituSource._validate_response({'code': 301013, 'msg': '权限类型错误'})


def test_category_and_around_use_official_v2_query_types(monkeypatch):
    calls = []
    source = TiandituSource('test-key', 0)

    def fake_request(endpoint, params):
        calls.append(__import__('json').loads(params['postStr']))
        return {'status': {'infocode': 1000}, 'count': 0, 'pois': []}

    monkeypatch.setattr(source, '_request', fake_request)
    source.poi_search('', '青秀区', types='通信设施', page=1, offset=20)
    source.around_search(108.3, 22.8, 3000, types='通信设施', page=1, offset=20)
    assert calls[0]['queryType'] == 13 and calls[0]['dataTypes'] == '通信设施'
    assert calls[1]['queryType'] == 3 and calls[1]['queryRadius'] == 3000
