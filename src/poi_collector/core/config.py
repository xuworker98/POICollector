# -*- coding: utf-8 -*-
"""Application settings, encrypted API keys and source factory."""
import os
import shutil
import sys
from copy import deepcopy
from pathlib import Path

import yaml

from sources.tianditu import TiandituSource
from sources.amap import AmapSource
from sources.baidu import BaiduSource
from sources.tencent import TencentSource
from core.secure_store import load_encrypted_json, save_encrypted_json

IS_FROZEN = bool(getattr(sys, 'frozen', False))
LOCAL_ROOT = Path(os.environ.get('LOCALAPPDATA', Path(__file__).resolve().parents[3])) / 'POICollector'
if IS_FROZEN:
    BUNDLE_ROOT = Path(sys._MEIPASS)
    PACKAGE_ROOT = BUNDLE_ROOT
    PROJECT_ROOT = str(LOCAL_ROOT)
    RES_DIR = str(BUNDLE_ROOT)
    BUNDLED_DATA_DIR = BUNDLE_ROOT / 'data'
else:
    PACKAGE_ROOT = Path(__file__).resolve().parents[1]
    PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
    RES_DIR = str(PACKAGE_ROOT / 'res')
    BUNDLED_DATA_DIR = Path(PROJECT_ROOT) / 'data'

CONFIG_DIR = Path(os.environ.get(
    'POICOLLECTOR_CONFIG_DIR',
    LOCAL_ROOT,
))
CONFIG_PATH = str(CONFIG_DIR / 'settings.yaml')
SECRETS_PATH = str(CONFIG_DIR / 'keys.dpapi')


def resource_path(name):
    """资源文件路径，兼容 PyInstaller onefile 打包。"""
    if getattr(sys, 'frozen', False):
        return os.path.join(sys._MEIPASS, name)
    return os.path.join(RES_DIR, name)


def prepare_runtime_data():
    """将内置基础数据首次复制到可写目录；不覆盖用户已更新的数据。"""
    if not IS_FROZEN or not BUNDLED_DATA_DIR.exists():
        return
    runtime_data = Path(PROJECT_ROOT) / 'data'
    for source in BUNDLED_DATA_DIR.rglob('*'):
        if not source.is_file():
            continue
        target = runtime_data / source.relative_to(BUNDLED_DATA_DIR)
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


prepare_runtime_data()

DEFAULT_CONFIG = {
    'keys': {'tianditu': '', 'amap': '', 'baidu': '', 'tencent': ''},
    'map_keys': {
        'tianditu': '', 'amap_js': '', 'amap_security': '',
        'baidu_browser': '', 'tencent_js': '',
    },
    'basemap': {
        'active_source': 'arcgis_hybrid',
        'fallback_priority': [
            'arcgis_hybrid', 'arcgis_imagery', 'arcgis_street', 'osm_standard',
        ],
        'custom_sources': [],
        'tile_timeout_sec': 10,
        'cache_mb': 256,
    },
    'defaults': {
        'output_crs': 'WGS84',
        'province': '广西壮族自治区',
        'city': '南宁市',
        'search_radius': 3000,
        'preferred_provider': 'tianditu',
        'qc_sample_count': 500,
        'golden_file': '',
        'daily_caps': {'tianditu': 7000, 'amap': 5000, 'baidu': 5000, 'tencent': 10000},
        'rate_limit_sec': {'amap': 0.42, 'tianditu': 0.36, 'mca': 0.40},
    },
    'source_priority': ['tianditu', 'amap', 'baidu', 'tencent'],
}


def load_config():
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
    try:
        encrypted = load_encrypted_json(SECRETS_PATH)
    except Exception:
        encrypted = {}
    # Legacy migration: the old encrypted file was a flat provider->key mapping.
    if 'query_keys' in encrypted or 'map_keys' in encrypted or 'basemap_secrets' in encrypted:
        encrypted_keys = encrypted.get('query_keys') or {}
        encrypted_map_keys = encrypted.get('map_keys') or {}
        basemap_secrets = encrypted.get('basemap_secrets') or {}
    else:
        encrypted_keys, encrypted_map_keys, basemap_secrets = encrypted, {}, {}
    # 与默认值合并，容忍缺字段（defaults 逐字段深合并）
    merged = deepcopy(DEFAULT_CONFIG)
    merged['keys'] = {**DEFAULT_CONFIG['keys'], **encrypted_keys}
    merged['map_keys'] = {**DEFAULT_CONFIG['map_keys'], **encrypted_map_keys}
    merged['defaults'] = {**DEFAULT_CONFIG['defaults'], **(cfg.get('defaults') or {})}
    merged['source_priority'] = cfg.get('source_priority') or DEFAULT_CONFIG['source_priority']
    public_basemap = cfg.get('basemap') or {}
    merged['basemap'] = {
        **DEFAULT_CONFIG['basemap'],
        **public_basemap,
        **basemap_secrets,
    }
    return merged


def save_config(cfg):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    basemap = deepcopy(cfg.get('basemap') or {})
    # Custom URLs may contain access tokens, so keep them in DPAPI storage.
    custom_sources = basemap.pop('custom_sources', [])
    save_encrypted_json(SECRETS_PATH, {
        'query_keys': cfg.get('keys') or {},
        'map_keys': cfg.get('map_keys') or {},
        'basemap_secrets': {'custom_sources': custom_sources},
    })
    public_cfg = {
        'defaults': cfg.get('defaults') or {},
        'source_priority': cfg.get('source_priority') or DEFAULT_CONFIG['source_priority'],
        'basemap': basemap,
    }
    temporary = CONFIG_DIR / 'settings.yaml.tmp'
    with open(temporary, 'w', encoding='utf-8') as f:
        yaml.safe_dump(public_cfg, f, allow_unicode=True, sort_keys=False)
    os.replace(temporary, CONFIG_PATH)


def build_sources(cfg):
    """根据 config 构建四源 source 对象（key 为空时对象仍可用，只是请求会失败）。"""
    keys = cfg.get('keys', {})
    defaults = cfg.get('defaults', {})
    caps = defaults.get('daily_caps', {})
    rates = defaults.get('rate_limit_sec', {})
    return {
        'tianditu': TiandituSource(keys.get('tianditu', ''), rates.get('tianditu', 0.36)),
        'amap': AmapSource(keys.get('amap', ''), rates.get('amap', 0.42)),
        'baidu': BaiduSource(keys.get('baidu', ''), rates.get('baidu', 0.40)),
        'tencent': TencentSource(keys.get('tencent', ''), rates.get('tencent', 0.40)),
    }
