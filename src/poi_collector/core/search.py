# -*- coding: utf-8 -*-
"""搜索策略引擎（POI 模式核心）：逐区县下钻 + 分页 + 去重 + 强制 city 限定。

铁律：city 参数必填且 citylimit=true —— 无 city 限定会全国同名错配
（广西项目实测：不带 city，"三塘镇"匹配到湖南衡阳）。
"""
import hashlib
import json
import os

from core.config import build_sources
from core.category import load_categories, find_node
from core.quota import QuotaManager
from core.region import RegionFetcher, PROVINCES
from core.store import PoiStore
from sources.base import QuotaExceeded, SourceUnavailable


class PoiSearchEngine:
    """POI 模式：对每个区县 × 每个小类码分页搜索，去重后输出带来源的 POI 列表。"""

    def __init__(self, cfg, province_name, leaf_codes, keyword, data_dir, output_dir,
                 city_name='', district_name=''):
        self.cfg = cfg
        self.province_name = province_name
        self.leaf_codes = leaf_codes  # 高德小类码列表
        self.keyword = keyword or ''
        self.data_dir = data_dir
        self.output_dir = output_dir
        self.city_name = city_name or ''
        self.district_name = '' if district_name == '全部区县' else (district_name or '')
        self.sources = build_sources(cfg)
        self.active_sources = [name for name, source in self.sources.items()
                               if source.key and getattr(source, 'supports_poi', False)]
        self.session_unavailable_sources = set()
        self.source_failures = {name: 0 for name in self.active_sources}
        self.quota = QuotaManager(cfg['defaults'].get('daily_caps', {}),
                                  cfg.get('source_priority'),
                                  os.path.join(output_dir, 'checkpoints', 'quota_state.json'))
        categories = load_categories()
        self.type_names = {
            code: (find_node(categories, code) or {}).get('name', code)
            for code in leaf_codes
        }

    def _load_districts(self):
        """加载目标省的区县级节点列表（level=3）。"""
        province_code = PROVINCES.get(self.province_name)
        region_file = os.path.join(self.data_dir, 'divisions', f'{province_code}.json')
        if not os.path.exists(region_file):
            fetcher = RegionFetcher(os.path.join(self.data_dir, 'divisions'),
                                    amap_key=self.cfg.get('keys', {}).get('amap', ''))
            nodes = fetcher.build_tree(province_code, max_level=4)
        else:
            with open(region_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
                nodes = cached.get('nodes', []) if isinstance(cached, dict) else cached
        by_code = {str(n.get('code') or ''): n for n in nodes}
        output = []
        for node in nodes:
            if node.get('level') != 3:
                continue
            enriched = dict(node)
            enriched['city'] = (by_code.get(str(node.get('parent') or '')) or {}).get('name', '')
            output.append(enriched)
        if self.city_name:
            output = [item for item in output if item.get('city') == self.city_name]
        if self.district_name:
            output = [item for item in output if item.get('name') == self.district_name]
        return output

    def run(self, progress_cb, quota_cb, log_cb, status_cb, is_stopped):
        log_cb(f'[信息] 开始 POI 模式采集：{self.province_name}（小类 {len(self.leaf_codes)} 个）')
        status_cb(f'运行中 · {self.province_name} POI', 'running')

        if not self.active_sources:
            return {'error': '没有已配置且支持 POI 搜索的数据源'}

        districts = self._load_districts()
        if not districts:
            return {'error': f'未找到 {self.province_name} 的区县数据，请先在区划模式采集一次'}

        signature = hashlib.sha1('|'.join((self.province_name, self.city_name,
                                          self.district_name, *self.leaf_codes)).encode('utf-8')).hexdigest()[:10]
        store_path = os.path.join(self.output_dir, 'checkpoints',
                                  f'{self.province_name}_分类搜索_{signature}.sqlite3')
        store = PoiStore(store_path)
        total_tasks = len(districts) * len(self.leaf_codes)
        task_done = 0

        result = None
        try:
            for district in districts:
                for type_code in self.leaf_codes:
                    task_key = f'{district.get("code", "")}:{type_code}:{self.keyword}'
                    if store.task_done(task_key):
                        task_done += 1
                        progress_cb(task_done, total_tasks, '断点恢复')
                        continue
                    if is_stopped():
                        log_cb('[警告] 用户停止，SQLite 断点已保存')
                        return self._result(store, store_path, total_tasks, stopped=True)
                    if self.quota.all_exhausted(self.active_sources):
                        log_cb('[错误] 配额用尽，任务断点已保存，可在配额恢复后续跑')
                        status_cb('配额用尽', 'error')
                        return self._result(store, store_path, total_tasks, quota_exhausted=True)

                    pois, provider, completed = self._search_district_type(
                        district, type_code, log_cb, is_stopped)
                    rows = []
                    for poi in pois:
                        rows.append({
                            'key': self._dedup_key(poi),
                            'province': self.province_name,
                            'city': district.get('city', ''),
                            'name': poi.get('name', ''),
                            'type': poi.get('type', ''),
                            'typecode': poi.get('typecode', '') or type_code,
                            'district': district.get('name', ''),
                            'adcode': poi.get('adcode', ''),
                            'lon': poi.get('lon'), 'lat': poi.get('lat'),
                            'address': poi.get('address', ''),
                            'source': provider,
                            'confidence': '中',  # 单源命中 + 区县严格限定
                        })
                    inserted = store.insert_pois(rows)
                    if completed:
                        store.mark_task_done(task_key, provider, inserted)
                        task_done += 1
                    else:
                        log_cb(f'[警告] {district["name"]} {type_code} 无可用图源，保留为未完成任务')
                        if self.quota.all_exhausted(self.active_sources):
                            return self._result(store, store_path, total_tasks, quota_exhausted=True)
                    progress_cb(task_done, total_tasks, f'{district["name"]} {type_code}')
                    quota_cb(self.quota.snapshot())
            result = self._result(store, store_path, total_tasks)
        finally:
            current_count = store.count()
            store.close()

        log_cb(f'[完成] 数据库累计 {current_count} 条 POI')
        progress_cb(total_tasks, total_tasks, '查询完成，正在整理结果')
        status_cb('查询完成，结果可导出；后台质检即将开始', 'idle')
        result['qc_pending'] = True
        return result

    def _result(self, store, store_path, total_tasks, **flags):
        count = store.count()
        result = {
            'mode': 'poi', 'nodes': store.preview(3000), 'store_path': store_path,
            'done': count, 'matched': count, 'total': total_tasks,
            'province': self.province_name,
        }
        result.update(flags)
        return result

    def _search_district_type(self, district, type_code, log_cb, is_stopped):
        """对 district×type_code：多源轮换 + 分页。搜不到自动切下一源。"""
        city = district.get('name', '')
        attempted = False
        for src_name in self.quota.source_priority:
            if is_stopped():
                return [], '', False
            if self.quota.exhausted.get(src_name):
                continue
            if src_name in self.session_unavailable_sources:
                continue
            src = self.sources.get(src_name)
            if src is None or not src.key or not getattr(src, 'supports_poi', False):
                continue
            pois_all = []
            page = 1
            page_size = 20
            while True:
                if is_stopped():
                    return pois_all, src_name, False
                try:
                    if src_name == 'amap':
                        query, provider_types = self.keyword, type_code
                    elif src_name == 'tianditu':
                        query, provider_types = '', self.type_names.get(type_code, '')
                    else:
                        query, provider_types = self.keyword or self.type_names.get(type_code, ''), None
                    pois, count = src.poi_search(query, city=city, types=provider_types,
                                                 page=page, offset=page_size)
                    self.quota.record_call(src_name)
                    self.source_failures[src_name] = 0
                    attempted = True
                except QuotaExceeded:
                    log_cb(f'[限流] {src_name} 配额用尽，切换下一源')
                    self.quota.mark_exhausted(src_name)
                    break
                except SourceUnavailable as exc:
                    log_cb(f'[换源] {src_name} 暂不可用：{exc}')
                    self.source_failures[src_name] = self.source_failures.get(src_name, 0) + 1
                    if 'HTTP 418' in str(exc) or self.source_failures[src_name] >= 2:
                        self.session_unavailable_sources.add(src_name)
                        log_cb(f'[换源] 本轮任务暂停使用 {src_name}，避免逐区县重复等待')
                    break
                if not pois:
                    break
                verified = []
                for p in pois:
                    returned_district = str(p.get('adname') or '').strip()
                    if returned_district and returned_district != city:
                        continue
                    p['来源'] = src_name
                    verified.append(p)
                pois_all.extend(verified)
                if page * page_size >= count or page >= 100:
                    break
                page += 1
            if pois_all:
                return pois_all, src_name, True
            # 当前源搜不到，继续下一个源
        return [], '', attempted

    @staticmethod
    def _dedup_key(poi):
        lon = float(poi.get('lon') or 0)
        lat = float(poi.get('lat') or 0)
        return f"{poi.get('name', '')}_{poi.get('adcode', '')}_{lon:.5f}_{lat:.5f}"
