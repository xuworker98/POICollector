import os

import pytest

from core.secure_store import load_encrypted_json, save_encrypted_json
from core import config


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI only')
def test_dpapi_roundtrip_and_no_plaintext(tmp_path):
    path = tmp_path / 'keys.dpapi'
    value = {'amap': 'secret-example-value'}
    save_encrypted_json(path, value)
    assert load_encrypted_json(path) == value
    assert b'secret-example-value' not in path.read_bytes()


@pytest.mark.skipif(os.name != 'nt', reason='Windows DPAPI only')
def test_query_map_keys_and_tokenized_xyz_are_not_written_to_yaml(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_DIR', tmp_path)
    monkeypatch.setattr(config, 'CONFIG_PATH', str(tmp_path / 'settings.yaml'))
    monkeypatch.setattr(config, 'SECRETS_PATH', str(tmp_path / 'keys.dpapi'))
    cfg = config.load_config()
    cfg['keys']['amap'] = 'query-secret'
    cfg['map_keys']['amap_js'] = 'map-secret'
    cfg['basemap']['custom_sources'] = [{
        'id': 'custom_1', 'name': 'token source',
        'url': 'https://example.com/{z}/{x}/{y}.png?token=tile-secret',
        'kind': 'xyz', 'min_zoom': 0, 'max_zoom': 19,
    }]
    config.save_config(cfg)
    public = (tmp_path / 'settings.yaml').read_text(encoding='utf-8')
    assert 'query-secret' not in public
    assert 'map-secret' not in public
    assert 'tile-secret' not in public
    loaded = config.load_config()
    assert loaded['keys']['amap'] == 'query-secret'
    assert loaded['map_keys']['amap_js'] == 'map-secret'
    assert 'tile-secret' in loaded['basemap']['custom_sources'][0]['url']
