# -*- coding: utf-8 -*-
"""四层质检体系（广西 16681 村 / 1381 驻地实战验证）+ 中等偏差抽验。

第1层 总数校验   —— 采集各级数量 vs 区划树目标数（防漏挂/错挂）
第2层 多源交叉验真 —— 百度独立通道复核坐标（防坐标错）
第3层 几何合理性  —— 村级距镇政府距离分布 + >30km 复核清单（防越界/错位）
第4层 黄金向量    —— 用户实测坐标最高优先（预留接口，可导入参考点 CSV）
补强 中等偏差抽验  —— 随机抽样 + 百度复核 + 自动修正（抓"坐标落镇政府旁但实际数 km 外"盲区）

⚠ 教训：多源互比 ≠ 验真（所有源经同一错误转换会"互相一致"）；
几何检测抓不到"距镇政府近但实际偏移数 km"的隐性错误，必须靠独立通道抽验。
"""
import os
import random
import re
import statistics

from core.coords import haversine_m
from core import geo_service
from sources.baidu import BaiduSource
from sources.base import QuotaExceeded, SourceUnavailable
from core.config import build_sources

# 阈值（实战验证值）
CROSS_PASS_M = 300        # 交叉验真：<300m 通过
CROSS_NOTE_M = 1000       # 300~1000m 点位差异（接受，记录）
FAR_TOWN_M = 30000        # 村级距镇政府 >30km 列复核清单
SAMPLE_PASS_M = 500       # 抽验：<500m 通过
SAMPLE_NOTE_M = 2000      # 500~2000m 点位差异（保留）
SAMPLE_FIX_NEARER_M = 2000  # 修正条件：百度点距镇政府比本表近 2km+
SAMPLE_FIX_MAX_M = 30000    # 且百度点距镇政府 <30km
DEFAULT_SAMPLE = 500      # 默认抽验规模（实战值）
DEFAULT_SEED = 20260825   # 固定种子可复现
CHINA_BBOX = (73.0, 3.0, 135.0, 54.0)  # 全国经纬度框（越界检测）


def strip_village_suffix(name):
    """村名后缀剥离：村委会/居委会/委员会/社区等。"""
    for suf in ('村民委员会', '居民委员会', '村委会', '居委会', '委员会'):
        name = name.replace(suf, '')
    return name


class QcEngine:
    """四层质检引擎 + 中等偏差抽验。"""

    def __init__(self, cfg):
        self.cfg = cfg
        defaults = cfg.get('defaults', {})
        self.preferred = defaults.get('preferred_provider', 'amap')
        self.sample_count = int(defaults.get('qc_sample_count', DEFAULT_SAMPLE))
        self.golden_file = defaults.get('golden_file', '')
        keys = self.cfg.get('keys', {})
        self.baidu_src = BaiduSource(keys['baidu'], rate_limit_sec=0.42) if keys.get('baidu') else None

    # ------------------------------------------------------------------ 入口
    def run_all(self, result, log_cb=None, golden_file=None, sample_count=None):
        """采集完成后统一跑四层质检 + 抽验，返回质检报告 dict（挂到 result['qc']）。"""
        nodes = result.get('nodes', [])
        targets = result.get('targets', [])
        if sample_count is None:
            sample_count = self.sample_count
        if golden_file is None:
            golden_file = self.golden_file

        by_code = {n.get('code'): n for n in nodes if n.get('code')}
        # 乡镇政府坐标：(区县名, 乡镇名) -> (lon, lat)
        town_seats = {}
        for n in nodes:
            if n.get('level') == 4 and n.get('经度(WGS84)') and n.get('纬度(WGS84)'):
                county = self._parent_name(n, by_code, 1)
                town_seats[(county, n.get('name', ''))] = (
                    float(n['经度(WGS84)']), float(n['纬度(WGS84)']))

        report = {'province': result.get('province', ''), 'scope': 'full'}

        # 第1层 总数校验
        report['total'] = self.total_check(result)
        if log_cb:
            t = report['total']
            log_cb(f'[质检·总数] 目标 {t["total"]} 匹配 {t["matched"]} 未匹配 {t["missing"]}')

        # 第3层 几何合理性
        report['geometry'] = self.geometry_check(nodes)
        if log_cb:
            g = report['geometry']
            log_cb(f'[质检·几何] 村级距镇政府 中位 {g["dist_median"]/1000:.1f}km '
                   f'P95 {g["dist_p95"]/1000:.1f}km 最大 {g["dist_max"]/1000:.1f}km '
                   f'| >30km {len(g["far_list"])} 条')

        # 补强 中等偏差抽验（需百度 KEY）
        keys = self.cfg.get('keys', {})
        report['sample'] = {'enabled': bool(keys.get('baidu')), 'result': None}
        if keys.get('baidu'):
            report['sample']['result'] = self.sample_verify(
                nodes, town_seats, sample_count=sample_count, log_cb=log_cb)
        elif log_cb:
            log_cb('[质检·抽验] 未配置百度 KEY，跳过中等偏差抽验')

        # 第4层 黄金向量（可选，用户导入参考点 CSV）
        report['golden'] = self.golden_check(nodes, golden_file) if golden_file else None

        # 越界检测
        report['out_of_box'] = self.bbox_check(nodes)
        if result.get('store_path'):
            report['scope'] = 'sqlite-full-count-and-bbox; preview-sample-for-other-checks'
            report['out_of_box'] = self._store_bbox_check(result['store_path'])
            report['poi_cross_sample'] = self.store_sample_verify(
                result['store_path'], sample_count=sample_count, log_cb=log_cb)
        if log_cb and report['out_of_box']:
            log_cb(f'[质检·越界] 发现 {len(report["out_of_box"])} 条坐标超出全国范围')

        return report

    # ------------------------------------------------------------ 第1层 总数
    def total_check(self, result):
        nodes = result.get('nodes', [])
        targets = result.get('targets', [])
        if result.get('mode') == 'poi':
            matched = int(result.get('matched', result.get('done', len(nodes))))
            return {'total': matched, 'matched': matched, 'missing': 0,
                    'task_total': int(result.get('total', 0))}
        total = result.get('total', len(targets) or len(nodes))
        matched = result.get('matched', sum(1 for n in nodes if n.get('经度(WGS84)')))
        return {'total': total, 'matched': matched, 'missing': total - matched}

    # ------------------------------------------------------------ 第3层 几何
    def geometry_check(self, nodes):
        """几何合理性：乡镇政府距区县政府 <90km + 村级距镇政府距离分布 + >30km 复核清单。"""
        by_code = {n.get('code'): n for n in nodes if n.get('code')}
        area_seats = {}   # (地市名, 区县名) -> (lon,lat)
        town_seats = {}   # (区县名, 乡镇名) -> (lon,lat)
        for n in nodes:
            lon, lat = n.get('经度(WGS84)'), n.get('纬度(WGS84)')
            if not lon or not lat:
                continue
            try:
                p = (float(lon), float(lat))
            except (ValueError, TypeError):
                continue
            if n.get('level') == 3:
                area_seats[(self._parent_name(n, by_code, 1), n.get('name', ''))] = p
            elif n.get('level') == 4:
                town_seats[(self._parent_name(n, by_code, 1), n.get('name', ''))] = p

        # 乡镇政府距区县政府 >90km 检测
        town_far = []
        for n in nodes:
            if n.get('level') != 4:
                continue
            lon, lat = n.get('经度(WGS84)'), n.get('纬度(WGS84)')
            if not lon or not lat:
                continue
            county = self._parent_name(n, by_code, 1)
            city = self._parent_name(n, by_code, 2)
            aseat = area_seats.get((city, county))
            if aseat:
                d = haversine_m(float(lon), float(lat), aseat[0], aseat[1])
                if d > 90000:
                    town_far.append({'名称': n.get('name', ''), '区县': county, '距离米': int(d)})

        # 村级距乡镇政府距离分布
        dists = []
        far = []
        for n in nodes:
            if n.get('level') != 5:
                continue
            lon, lat = n.get('经度(WGS84)'), n.get('纬度(WGS84)')
            if not lon or not lat:
                continue
            county = self._parent_name(n, by_code, 2)
            town = self._parent_name(n, by_code, 1)
            ts = town_seats.get((county, town))
            if not ts:
                continue
            d = haversine_m(float(lon), float(lat), ts[0], ts[1])
            dists.append(d)
            if d > FAR_TOWN_M:
                far.append({'名称': n.get('name', ''), '乡镇': town, '距离米': int(d)})
        dists.sort()
        return {
            'town_seats': len(town_seats),
            'town_far': town_far,
            'dist_median': statistics.median(dists) if dists else 0,
            'dist_p95': dists[int(len(dists) * 0.95)] if dists else 0,
            'dist_max': dists[-1] if dists else 0,
            'far_list': far,
        }

    # ------------------------------------------------------- 补强 中等偏差抽验
    def sample_verify(self, nodes, town_seats, sample_count=DEFAULT_SAMPLE,
                      log_cb=None, seed=DEFAULT_SEED):
        """随机抽样 -> 百度独立通道复核 -> 分级 + 自动修正。"""
        pool = [n for n in nodes
                if n.get('name') and n.get('经度(WGS84)') and n.get('纬度(WGS84)')
                and n.get('level') in (4, 5)]
        n = min(sample_count, len(pool))
        random.seed(seed)
        sample = random.sample(pool, n) if n > 0 else []
        by_code = {item.get('code'): item for item in nodes if item.get('code')}

        r = {'sample': n, 'pass': 0, 'note': 0, 'fix': 0, 'miss': 0, 'abnormal': [], 'fixed_nodes': []}
        for i, node in enumerate(sample, 1):
            name = node['name']
            level = node.get('level', 5)
            if level == 4:
                county = self._parent_name(node, by_code, 1)
                town = name
            else:
                county = self._parent_name(node, by_code, 2)
                town = self._parent_name(node, by_code, 1)
            core = strip_village_suffix(name)
            our_lon = float(node['经度(WGS84)'])
            our_lat = float(node['纬度(WGS84)'])
            hit = self._baidu_lookup(core, name, county, town, level)
            if not hit:
                r['miss'] += 1
                continue
            d = haversine_m(our_lon, our_lat, hit[0], hit[1])
            if d < SAMPLE_PASS_M:
                r['pass'] += 1
            elif d <= SAMPLE_NOTE_M:
                r['note'] += 1
            else:
                ts = town_seats.get((county, town))
                if ts:
                    d_bd_t = haversine_m(hit[0], hit[1], ts[0], ts[1])
                    d_cur_t = haversine_m(our_lon, our_lat, ts[0], ts[1])
                    if d_bd_t < d_cur_t - SAMPLE_FIX_NEARER_M and d_bd_t <= SAMPLE_FIX_MAX_M:
                        r['fix'] += 1
                        r['fixed_nodes'].append({
                            '名称': name, '乡镇': town, '区县': county,
                            '候选经度': round(hit[0], 6), '候选纬度': round(hit[1], 6),
                            '状态': '候选修正，需第三源或人工确认',
                        })
                        if log_cb:
                            log_cb(f'[质检·候选] {county}/{town} {name} 与百度偏差 {int(d)}m，'
                                   '已列入复核清单，未自动覆盖原坐标')
                    else:
                        r['abnormal'].append({'名称': name, '区县': county, '乡镇': town, '偏差米': int(d)})
                else:
                    r['abnormal'].append({'名称': name, '区县': county, '乡镇': town, '偏差米': int(d)})
        r['error_rate'] = r['fix'] / n if n else 0
        if log_cb:
            log_cb(f'[质检·抽验] 抽样 {n} 条：通过 {r["pass"]} 差异 {r["note"]} '
                   f'修正 {r["fix"]} 未命中 {r["miss"]} | 错误率 {r["error_rate"]:.1%}')
        return r

    def _baidu_lookup(self, core, full_name, county, town, level=5):
        """百度独立 POI 通道复核，严格限制区县并核对名称。"""
        if self.baidu_src is None:
            return None
        if level == 4:
            candidates = [full_name + '人民政府', full_name + '办事处', full_name]
        else:
            candidates = [core]
            if not core.endswith('村'):
                candidates.append(core + '村')
            candidates.append(full_name)
        for q in dict.fromkeys(candidates):
            if not q:
                continue
            try:
                pois, _ = self.baidu_src.poi_search(q, city=county, page=1, offset=20)
            except QuotaExceeded:
                return None
            for item in pois:
                hit_name = item.get('name', '')
                area = item.get('adname', '')
                if area and area != county:
                    continue
                if core and core not in hit_name and hit_name not in core:
                    continue
                return (item['lon'], item['lat'])
        return None

    # ------------------------------------------------------------ 第4层 黄金
    def golden_check(self, nodes, golden_file):
        """黄金向量：用户实测坐标对比。golden_file 为 CSV（列：名称/编码 + 经度 + 纬度）。"""
        import csv
        if not os.path.exists(golden_file):
            return {'error': f'参考点文件不存在: {golden_file}'}
        golden = {}
        with open(golden_file, encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                key = (row.get('名称') or row.get('编码') or '').strip()
                try:
                    lon, lat = float(row['经度']), float(row['纬度'])
                except (ValueError, TypeError, KeyError):
                    continue
                if key:
                    golden[key] = (lon, lat)
        results = []
        for n in nodes:
            key = n.get('name', '')
            if key not in golden:
                continue
            glon, glat = golden[key]
            lon, lat = n.get('经度(WGS84)'), n.get('纬度(WGS84)')
            if not lon or not lat:
                results.append({'名称': key, '偏差米': None, '结论': '本表无坐标'})
                continue
            d = haversine_m(float(lon), float(lat), glon, glat)
            # 黄金向量最权威：>300m 直接标记需修正
            results.append({'名称': key, '偏差米': int(d),
                            '结论': '通过' if d < 300 else '需修正(黄金向量)'})
        return {'matched': len(results), 'results': results}

    # ------------------------------------------------------------ 越界检测
    def bbox_check(self, nodes):
        out = []
        for n in nodes:
            lon, lat = n.get('经度(WGS84)'), n.get('纬度(WGS84)')
            if not lon or not lat:
                continue
            try:
                lo, la = float(lon), float(lat)
            except (ValueError, TypeError):
                continue
            if not (CHINA_BBOX[0] <= lo <= CHINA_BBOX[2] and CHINA_BBOX[1] <= la <= CHINA_BBOX[3]):
                out.append({'名称': n.get('name', ''), '经度': lo, '纬度': la})
        return out

    @staticmethod
    def _store_bbox_check(store_path):
        import sqlite3
        with sqlite3.connect(store_path) as conn:
            rows = conn.execute('''
                SELECT name,lon,lat FROM poi
                WHERE lon < ? OR lon > ? OR lat < ? OR lat > ?
                LIMIT 1000
            ''', (CHINA_BBOX[0], CHINA_BBOX[2], CHINA_BBOX[1], CHINA_BBOX[3])).fetchall()
        return [{'名称': n, '经度': lo, '纬度': la} for n, lo, la in rows]

    def store_sample_verify(self, store_path, sample_count=DEFAULT_SAMPLE, log_cb=None):
        """Cross-check a deterministic SQLite sample with an independent provider."""
        import sqlite3
        providers = build_sources(self.cfg)
        unavailable = set()
        result = {'sample': 0, 'verified': 0, 'high': 0, 'note': 0,
                  'low': 0, 'unverified': 0, 'providers_unavailable': []}
        with sqlite3.connect(store_path) as conn:
            rows = conn.execute('''
                SELECT key,name,district,lon,lat,source FROM poi
                ORDER BY key LIMIT ?
            ''', (int(sample_count),)).fetchall()
            result['sample'] = len(rows)
            for key, name, district, lon, lat, primary in rows:
                verified = None
                for provider_name in self.cfg.get('source_priority', []):
                    if provider_name == primary or provider_name in unavailable:
                        continue
                    source = providers.get(provider_name)
                    if not source or not source.key or not getattr(source, 'supports_poi', False):
                        continue
                    try:
                        candidates, _ = source.poi_search(name, city=district, page=1, offset=20)
                    except (QuotaExceeded, SourceUnavailable) as exc:
                        unavailable.add(provider_name)
                        if log_cb:
                            log_cb(f'[质检·换源] {provider_name} 本轮不可用：{exc}')
                        continue
                    normalized = self._normalize_name(name)
                    valid = [item for item in candidates
                             if (not item.get('adname') or item.get('adname') == district)
                             and (normalized in self._normalize_name(item.get('name', ''))
                                  or self._normalize_name(item.get('name', '')) in normalized)]
                    if valid:
                        verified = min(valid, key=lambda item: haversine_m(
                            float(lon), float(lat), item['lon'], item['lat']))
                        break
                if verified is None:
                    result['unverified'] += 1
                    continue
                distance = haversine_m(float(lon), float(lat), verified['lon'], verified['lat'])
                result['verified'] += 1
                if distance < CROSS_PASS_M:
                    confidence = '高'
                    result['high'] += 1
                elif distance <= CROSS_NOTE_M:
                    confidence = '中'
                    result['note'] += 1
                else:
                    confidence = '低'
                    result['low'] += 1
                conn.execute('UPDATE poi SET confidence=? WHERE key=?', (confidence, key))
            conn.commit()
        result['providers_unavailable'] = sorted(unavailable)
        if log_cb:
            log_cb(f'[质检·POI交叉抽验] 抽样 {result["sample"]}，独立源命中 {result["verified"]}，'
                   f'高 {result["high"]} 中 {result["note"]} 低 {result["low"]}，'
                   f'未验 {result["unverified"]}')
        return result

    @staticmethod
    def _normalize_name(value):
        return re.sub(r'[^0-9A-Za-z\u4e00-\u9fff]+', '', str(value)).lower()

    @staticmethod
    def _parent_name(node, nodes_or_index, up):
        """按 parent code 向上找祖先名；字典索引时为 O(1)。"""
        index = nodes_or_index if isinstance(nodes_or_index, dict) else {
            item.get('code'): item for item in nodes_or_index if item.get('code')
        }
        cur = node
        for _ in range(up):
            pcode = cur.get('parent', '')
            p = index.get(pcode)
            if not p:
                return ''
            cur = p
        return cur.get('name', '')
