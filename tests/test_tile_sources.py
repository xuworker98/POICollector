import pytest

from core.config import DEFAULT_CONFIG
from core.tile_sources import available_tile_sources, validate_tile_source


def test_anonymous_fallback_sources_are_always_available():
    sources = available_tile_sources(DEFAULT_CONFIG)
    ids = {source['id'] for source in sources}
    assert {'arcgis_imagery', 'arcgis_hybrid', 'arcgis_street', 'osm_standard'} <= ids


def test_custom_xyz_is_validated_and_preserved():
    source = validate_tile_source({
        'name': '测试图源',
        'url': 'https://example.com/tiles/{z}/{x}/{y}.png',
        'kind': 'xyz',
        'min_zoom': 1,
        'max_zoom': 18,
        'attribution': 'Example',
    })
    assert source['name'] == '测试图源'
    assert source['max_zoom'] == 18


@pytest.mark.parametrize('url', [
    'https://example.com/{z}/{x}.png',
    'file:///tiles/{z}/{x}/{y}.png',
])
def test_invalid_custom_xyz_is_rejected(url):
    with pytest.raises(ValueError):
        validate_tile_source({'name': 'bad', 'url': url})


def test_tianditu_display_key_adds_presets():
    cfg = dict(DEFAULT_CONFIG)
    cfg['map_keys'] = {**DEFAULT_CONFIG['map_keys'], 'tianditu': 'sample-key'}
    ids = {source['id'] for source in available_tile_sources(cfg)}
    assert {'tianditu_vector', 'tianditu_imagery'} <= ids


def test_browser_js_keys_are_ignored_by_pure_qt_renderer():
    cfg = dict(DEFAULT_CONFIG)
    cfg['map_keys'] = {
        **DEFAULT_CONFIG['map_keys'],
        'amap_js': 'a', 'amap_security': 's',
        'baidu_browser': 'b', 'tencent_js': 't',
    }
    ids = {source['id'] for source in available_tile_sources(cfg)}
    assert not {'amap_official', 'baidu_official', 'tencent_official'} & ids
