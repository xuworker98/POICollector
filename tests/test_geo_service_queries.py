from core import geo_service


class FakeSource:
    name = 'fake'

    def __init__(self):
        self.calls = []

    def poi_search(self, keyword, city='', types=None, page=1, offset=20):
        self.calls.append(('text', keyword, city, types, page, offset))
        if page > 2:
            return [], 3
        start = (page - 1) * 2
        count = 2 if page == 1 else 1
        return [dict(name=f'点{start+i}', adcode='450103', lon=108.3+i/1000,
                     lat=22.8, address='', type='', typecode='') for i in range(count)], 3

    def around_search(self, lon, lat, radius, keyword='', types=None, page=1, offset=20):
        self.calls.append(('around', keyword, radius, types, page, offset))
        return ([dict(name='基站', adcode='450103', lon=lon, lat=lat,
                      address='', type='', typecode='')] if page == 1 else []), 1


def test_text_search_paginates_and_deduplicates(monkeypatch):
    source = FakeSource()
    monkeypatch.setattr(geo_service, '_get_sources', lambda *_args, **_kwargs: [source])
    rows, total, provider = geo_service.text_search('通信基站', '青秀区', offset=2)
    assert len(rows) == 3
    assert total == 3
    assert provider == 'fake'
    assert [call[4] for call in source.calls] == [1, 2]


def test_around_search_passes_target_keyword_not_category(monkeypatch):
    source = FakeSource()
    monkeypatch.setattr(geo_service, '_get_sources', lambda *_args, **_kwargs: [source])
    rows, total, provider = geo_service.around_search(
        108.3, 22.8, 3000, keyword='通信基站', types=None)
    assert len(rows) == 1 and total == 1 and provider == 'fake'
    assert source.calls[0][1:4] == ('通信基站', 3000, None)


def test_around_category_adapts_amap_codes(monkeypatch):
    source = FakeSource()
    source.name = 'amap'
    monkeypatch.setattr(geo_service, '_get_sources', lambda *_args, **_kwargs: [source])
    geo_service.around_search(108.3, 22.8, 3000, types='070101|070102',
                              category_names=['汽车服务', '加油站'])
    assert source.calls[0][1:4] == ('', 3000, '070101|070102')


def test_around_category_adapts_baidu_to_chinese_names(monkeypatch):
    source = FakeSource()
    source.name = 'baidu'
    monkeypatch.setattr(geo_service, '_get_sources', lambda *_args, **_kwargs: [source])
    geo_service.around_search(108.3, 22.8, 3000, types='070101|070102',
                              category_names=['汽车服务', '加油站'])
    assert source.calls[0][1:4] == ('汽车服务', 3000, None)
    assert source.calls[1][1:4] == ('加油站', 3000, None)
