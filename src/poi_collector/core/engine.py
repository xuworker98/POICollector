# -*- coding: utf-8 -*-
"""采集引擎：区划模式（POI 模式见 core/search.py，M4）"""
import os
import re

from core.config import build_sources
from core.quota import QuotaManager, Checkpoint
from core.region import RegionFetcher, PROVINCES, load_villages
from core.coords import haversine_m
from sources.base import QuotaExceeded, SourceUnavailable

LEVEL_MAP = {'province': 1, 'city': 2, 'district': 3, 'town': 4, 'village': 5}


def kw_variants(name):
    """查询词变体（广西实战）：全拼 + 村名后缀剥离 + 居委会→社区。

    村名常有"村委会/居委会/社区/生活区"多种后缀，直接查常不命中。
    """
    variants = [name]
    if name.endswith('村民委员会'):
        variants.append(name[:-5])
    elif name.endswith('村委会'):
        variants.append(name[:-3])
    elif name.endswith('居委会'):
        base = name[:-3]
        if not base.endswith('社区'):
            base += '社区'
        variants.append(base)
    return [v for v in variants if v]


class DivisionEngine:
    """区划模式：下钻区划树 → 逐节点地理编码（四源轮换）→ 断点 + 配额 → 结果"""

    def __init__(self, cfg, province_name, levels, data_dir, output_dir,
                 city_name='', district_name=''):
        self.cfg = cfg
        self.province_name = province_name
        self.level_names = levels  # 如 ['city','district','town']
        self.data_dir = data_dir
        self.output_dir = output_dir
        self.city_name = city_name or ''
        self.district_name = '' if district_name == '全部区县' else (district_name or '')
        self.sources = build_sources(cfg)
        self.active_sources = [name for name, source in self.sources.items()
                               if source.key and getattr(source, 'supports_geocode', False)]
        self.task_unavailable_sources = set()
        self.quota = QuotaManager(cfg['defaults'].get('daily_caps', {}),
                                  cfg.get('source_priority'),
                                  os.path.join(output_dir, 'checkpoints', 'quota_state.json'))

    def run(self, progress_cb, quota_cb, log_cb, status_cb, is_stopped):
        log_cb(f'[信息] 开始区划模式采集：{self.province_name}（级别：{"、".join(self.level_names)}）')
        status_cb(f'运行中 · {self.province_name}', 'running')

        if not self.active_sources:
            return {'error': '没有已配置且支持地理编码的数据源'}

        province_code = PROVINCES.get(self.province_name)
        if not province_code:
            return {'error': f'未知省份：{self.province_name}'}

        fetcher = RegionFetcher(os.path.join(self.data_dir, 'divisions'),
                                amap_key=self.cfg.get('keys', {}).get('amap', ''))
        log_cb('[信息] 下钻区划树（民政部接口，本地缓存优先）…')
        nodes = fetcher.build_tree(province_code, max_level=4)

        if 'village' in self.level_names:
            village_file = os.path.join(self.data_dir, 'villages', f'{province_code}.csv')
            villages = load_villages(village_file)
            if not villages:
                message = (
                    f'缺少五级村级清单：{village_file}。国家统计局自2024年10月起不再公开'
                    '具体统计区划代码，软件不会伪造村级名称或编码；请导入已核验的12位村级CSV。'
                )
                log_cb(f'[错误] {message}')
                status_cb('缺少村级基础数据', 'error')
                return {'error': message, 'nodes': [], 'total': 0, 'matched': 0}
            nodes.extend(villages)

        by_code = {n['code']: n for n in nodes}

        def ancestry_names(node):
            names, current = [], node
            while current:
                names.append(current.get('name', ''))
                current = by_code.get(current.get('parent', ''))
            return names

        target_levels = [LEVEL_MAP[n] for n in self.level_names if n in LEVEL_MAP]
        targets = [n for n in nodes if n['level'] in target_levels]
        if self.city_name:
            targets = [n for n in targets if self.city_name in ancestry_names(n)]
        if self.district_name:
            targets = [n for n in targets if self.district_name in ancestry_names(n)]

        def parent_name(n):
            p = by_code.get(n.get('parent', ''))
            return p['name'] if p else ''

        def context(n):
            ancestors = []
            cur = n
            while cur.get('parent') and len(ancestors) < 4:
                cur = by_code.get(cur.get('parent')) or {}
                if not cur:
                    break
                ancestors.append(cur)
            ancestors.reverse()
            prefix = ''.join(item.get('name', '') for item in ancestors)
            county = next((item.get('name', '') for item in reversed(ancestors)
                           if item.get('level') == 3), '')
            city = next((item.get('name', '') for item in reversed(ancestors)
                         if item.get('level') == 2), '')
            return prefix, county or city or parent_name(n)

        checkpoint_cols = ['_key', '编码', '名称', '经度(WGS84)', '纬度(WGS84)', '匹配源']
        checkpoint = Checkpoint(
            os.path.join(self.output_dir, 'checkpoints', f'{self.province_name}_区划.csv'),
            checkpoint_cols, key_col='_key',
        )
        history = checkpoint.load_all()

        total = len(targets)
        results = []
        done = 0
        for i, node in enumerate(targets):
            if is_stopped():
                checkpoint.flush()
                log_cb('[警告] 用户停止，断点已保存')
                status_cb('已停止', 'idle')
                return {'stopped': True, 'done': done, 'total': total,
                        'nodes': results, 'targets': targets}

            key = node['code']
            if key in history:
                # 断点续传：恢复历史坐标（不重复 geocode）
                hist = history[key]
                node['经度(WGS84)'] = hist.get('经度(WGS84)', '')
                node['纬度(WGS84)'] = hist.get('纬度(WGS84)', '')
                node['匹配源'] = hist.get('匹配源', '')
                results.append(node)
                done += 1
                continue

            # 已核验的本地区划缓存可直接复用，VPN/官网不可用时仍可完整运行。
            cached_lon = node.get('经度(WGS84)')
            cached_lat = node.get('纬度(WGS84)')
            if cached_lon not in (None, '') and cached_lat not in (None, ''):
                node['匹配源'] = node.get('匹配源') or '本地核验缓存'
                results.append(node)
                done += 1
                checkpoint.append({
                    '_key': key, '编码': node['code'], '名称': node['name'],
                    '经度(WGS84)': cached_lon, '纬度(WGS84)': cached_lat,
                    '匹配源': node['匹配源'],
                })
                progress_cb(done, total, '本地核验缓存')
                if i % 100 == 0:
                    log_cb(f'[缓存] {done}/{total} · {node["name"]}')
                continue

            prefix, region = context(node)
            coord = self._geocode_with_rotation(
                node['name'], region, log_cb, level=node.get('level', 0), prefix=prefix)
            if coord:
                lon, lat, src = coord[:3]
                detail = coord[3] if len(coord) > 3 else ''
                node['经度(WGS84)'] = lon
                node['纬度(WGS84)'] = lat
                node['匹配源'] = src
                node['政府驻地地址'] = detail
                results.append(node)
            else:
                node['经度(WGS84)'] = ''
                node['纬度(WGS84)'] = ''
                node['匹配源'] = '未匹配'
                results.append(node)
            done += 1

            checkpoint.append({
                '_key': key, '编码': node['code'], '名称': node['name'],
                '经度(WGS84)': node.get('经度(WGS84)', ''),
                '纬度(WGS84)': node.get('纬度(WGS84)', ''),
                '匹配源': node.get('匹配源', ''),
            })

            if self.quota.all_exhausted(self.active_sources):
                checkpoint.flush()
                log_cb('[错误] 四源配额全部用尽，今日停机，断点已保存')
                status_cb('配额用尽，明日续跑', 'error')
                break

            progress_cb(done, total, '地理编码')
            quota_cb(self.quota.snapshot())
            if i % 10 == 0:
                log_cb(f'[进度] {done}/{total} · {node["name"]}')

        checkpoint.flush()
        matched = sum(1 for n in results if n.get('经度(WGS84)'))
        log_cb(f'[完成] 共 {total} 条，匹配 {matched} 条，未匹配 {total - matched} 条')
        status_cb('完成', 'idle')
        result = {
            'mode': 'division',
            'done': done, 'total': total, 'matched': matched,
            'nodes': results, 'targets': targets,
            'levels': self.level_names, 'province': self.province_name,
        }
        # 四层质检 + 中等偏差抽验（采集完成后自动触发）
        try:
            from core.qc import QcEngine
            log_cb('[质检] 开始四层质检 + 中等偏差抽验…')
            result['qc'] = QcEngine(self.cfg).run_all(result, log_cb=log_cb)
            log_cb('[质检] 质检完成，结果已纳入质检报告')
        except Exception as e:
            log_cb(f'[质检] 质检异常（不影响采集结果）：{e}')
        return result

    def _geocode_with_rotation(self, name, city, log_cb, level=0, prefix=''):
        """多源地理编码：查询词变体 + 按优先级遍历源（搜不到/低分自动换源）。

        关键：天地图搜不到或 score<90 时，必须继续尝试高德/百度/腾讯，而不是放弃。
        返回 (lon, lat, source) 或 None（所有源所有变体都试过仍未命中）。
        """
        base_variants = kw_variants(name)
        if level in (2, 3, 4):
            base_variants = [name + '人民政府', name] + base_variants
        variants = []
        for item in base_variants:
            for candidate in (prefix + item, item):
                if candidate and candidate not in variants:
                    variants.append(candidate)
        for kw in variants:
            for src_name in self.quota.source_priority:
                unavailable = getattr(self, 'task_unavailable_sources', set())
                if self.quota.exhausted.get(src_name) or src_name in unavailable:
                    continue
                src = self.sources.get(src_name)
                if src is None or not src.key:
                    continue
                try:
                    r = src.geocode(kw, city=city)
                    self.quota.record_call(src_name)
                except QuotaExceeded:
                    log_cb(f'[限流] {src_name} 配额用尽，切换下一源')
                    self.quota.mark_exhausted(src_name)
                    continue
                except SourceUnavailable as exc:
                    log_cb(f'[换源] {src_name} 暂不可用：{exc}')
                    # HTTP 418/网络出口封锁属于任务级故障；本任务不再逐条重复请求和刷日志。
                    if getattr(exc, 'status_code', None) == 418:
                        if not hasattr(self, 'task_unavailable_sources'):
                            self.task_unavailable_sources = set()
                        self.task_unavailable_sources.add(src_name)
                    continue
                if not r:
                    continue  # 当前源搜不到，换下一个源
                if src_name == 'tianditu' and r[2] < 90:
                    continue  # 天地图低分不可靠，换下一个源
                match_level = str(r[2] or '')
                if level == 5 and match_level in ('省', '城市', '区县', '乡镇', 'street', 'district'):
                    continue  # 村级不可降级采纳乡镇/区县中心点
                address = r[3] if len(r) > 3 else ''
                if level in (2, 3, 4) and not self._is_detailed_address(address, name):
                    address = self._enrich_government_address(
                        src, src_name, name, city, r[0], r[1], address, log_cb)
                return (r[0], r[1], src_name, address)
        return None

    @staticmethod
    def _is_detailed_address(address, name=''):
        """区分“南宁市人民政府”这类POI名称与可交付的门牌地址。"""
        text = str(address or '').strip()
        if not text or text in (name, name + '人民政府'):
            return False
        return bool(re.search(r'(路|街|巷|大道|道|弄|号|村|社区|屯|组)', text))

    def _enrich_government_address(self, src, src_name, name, city, lon, lat,
                                   fallback, log_cb):
        """用同源POI详情补齐政府驻地门牌；失败时保留原结果，不臆造地址。"""
        if not getattr(src, 'supports_poi', False):
            return fallback
        try:
            pois, _total = src.poi_search(name + '人民政府', city=city, page=1, offset=20)
            self.quota.record_call(src_name)
        except QuotaExceeded:
            self.quota.mark_exhausted(src_name)
            return fallback
        except SourceUnavailable as exc:
            if getattr(exc, 'status_code', None) == 418:
                self.task_unavailable_sources.add(src_name)
            return fallback
        candidates = []
        expected = re.sub(r'(人民政府|政府)$', '', name)
        for poi in pois or []:
            poi_name = str(poi.get('name') or '')
            if expected and expected not in poi_name:
                continue
            try:
                distance = haversine_m(float(lon), float(lat), float(poi['lon']), float(poi['lat']))
            except (KeyError, TypeError, ValueError):
                continue
            if distance <= 2000:
                candidates.append((distance, poi))
        if not candidates:
            return fallback
        poi = min(candidates, key=lambda item: item[0])[1]
        detail = str(poi.get('address') or '').strip()
        if not self._is_detailed_address(detail, name):
            return fallback
        full = detail
        for part in reversed((poi.get('pname'), poi.get('cityname'), poi.get('adname'))):
            part = str(part or '').strip()
            if part and part not in full:
                full = part + full
        log_cb(f'[地址] {name} 驻地门牌已由 {src_name} POI详情补齐')
        return full
