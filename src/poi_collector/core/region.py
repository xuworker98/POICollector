# -*- coding: utf-8 -*-
"""区划框架：民政部 5 级下钻 + 村级镜像合并 + 本地缓存。

容错设计（核心原则）：静态数据一次下载、永久本地缓存，
绝不把"每次运行都要联网"设计进工具。
主源降级链：民政部 → 国家统计局 → 高德 district API（区县级）→ 本地缓存。
村级清单首次下载后存本地 data/ 缓存，之后离线可用。
"""
import json
import os
import random
import time
import urllib.parse
from datetime import datetime

import requests
import urllib3

MCA_URL = 'https://dmfw.mca.gov.cn/xzqh/getCodeList'
DEFAULT_TABLE = 'Xzqh20251231'

# 34 个省级行政区：名称 -> 9位省级码（前缀码 + 右侧补零）
PROVINCES = {
    '北京市': '110000000', '天津市': '120000000', '河北省': '130000000',
    '山西省': '140000000', '内蒙古自治区': '150000000', '辽宁省': '210000000',
    '吉林省': '220000000', '黑龙江省': '230000000', '上海市': '310000000',
    '江苏省': '320000000', '浙江省': '330000000', '安徽省': '340000000',
    '福建省': '350000000', '江西省': '360000000', '山东省': '370000000',
    '河南省': '410000000', '湖北省': '420000000', '湖南省': '430000000',
    '广东省': '440000000', '广西壮族自治区': '450000000', '海南省': '460000000',
    '重庆市': '500000000', '四川省': '510000000', '贵州省': '520000000',
    '云南省': '530000000', '西藏自治区': '540000000', '陕西省': '610000000',
    '甘肃省': '620000000', '青海省': '630000000', '宁夏回族自治区': '640000000',
    '新疆维吾尔自治区': '650000000', '台湾省': '710000000',
    '香港特别行政区': '810000000', '澳门特别行政区': '820000000',
}

# 级别 -> 名称（1=省 2=市 3=区县 4=乡镇 5=村）
LEVEL_NAMES = {1: 'province', 2: 'city', 3: 'district', 4: 'town', 5: 'village'}


def pad_code(code):
    """9位行政码右侧补零（⚠ 不是 zfill 左侧补零！zfill 会错码）。"""
    return str(code).ljust(9, '0')


class RegionFetcher:
    """民政部区划下钻器：BFS 拉取 5 级树（村级另从镜像读），本地缓存优先。"""

    def __init__(self, cache_dir, rate_limit=0.4, amap_key=''):
        self.cache_dir = cache_dir
        self.rate_limit = rate_limit
        self.amap_key = amap_key
        self._last = 0.0
        self._mca_blocked_reason = ''

    def _wait(self):
        now = time.time()
        d = now - self._last
        if d < self.rate_limit:
            time.sleep(self.rate_limit - d + random.random() * 0.05)
        self._last = time.time()

    def fetch_children(self, parent_code, parent_name='', parent_level=1,
                       table_name=DEFAULT_TABLE, page_size=500):
        """拉某父级子级：民政部优先，失败降级高德 district API。返回 [{code,name,level}]。"""
        results = self._fetch_mca(parent_code, parent_level, table_name, page_size)
        if results:
            return results
        return self._fetch_amap(parent_name, parent_level)

    def _fetch_mca(self, parent_code, parent_level, table_name, page_size):
        """民政部接口（表单 POST 分页）。失败后本次任务熔断并交给高德。"""
        if self._mca_blocked_reason:
            return []
        results = []
        page_num = 1
        request_parent = str(parent_code).rstrip('0') or str(parent_code)
        while True:
            payload = {
                'parentCode': request_parent,
                'placeCode': '',
                'title': '',
                'pageNum': str(page_num),
                'pageSize': str(page_size),
                'tableName': table_name,
                'type': '2',
            }
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0',
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest',
            }
            self._wait()
            try:
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                r = requests.post(
                    MCA_URL, data=payload, headers=headers, timeout=30, verify=False,
                )
                r.raise_for_status()
                data = r.json()
            except requests.RequestException as exc:
                self._mca_blocked_reason = (
                    f'{type(exc).__name__}；如正在使用境外 VPN，请关闭后重试'
                )
                return results
            except (TypeError, ValueError):
                return results
            if isinstance(data, dict):
                if data.get('status') == 500 or data.get('error'):
                    return results  # 服务器错误，交给高德降级
                data = data.get('data') or data.get('result') or data.get('rows') or []
            if not data:
                break
            normalized = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                code = str(
                    item.get('code') or item.get('placeCode') or
                    item.get('xzqhCode') or item.get('dm') or ''
                ).strip()
                name = str(
                    item.get('name') or item.get('placeName') or
                    item.get('xzqhName') or item.get('mc') or item.get('title') or ''
                ).strip()
                if not code or not name or (code.rstrip('0') or code) == request_parent:
                    continue
                normalized.append({
                    'code': code,
                    'name': name,
                    'level': parent_level + 1,
                    'source': '民政部国家地名信息库',
                })
            results.extend(normalized)
            if len(data) < page_size:
                break
            page_num += 1
        return results

    def _fetch_amap(self, parent_name, parent_level):
        """高德 district API 下钻一级。返回 [{code,name,level}]（code 为 6 位 adcode）。"""
        if not self.amap_key or not parent_name:
            return []
        url = (f'https://restapi.amap.com/v3/config/district'
               f'?keywords={urllib.parse.quote(parent_name)}&subdistrict=1&key={self.amap_key}')
        self._wait()
        try:
            r = requests.get(url, timeout=15)
            data = r.json()
        except Exception:
            return []
        if data.get('status') != '1':
            return []
        districts = data.get('districts') or []
        if not districts:
            return []
        children = districts[0].get('districts') or []
        return [{
            'code': c.get('adcode', ''),
            'name': c.get('name', ''),
            'level': parent_level + 1,
        } for c in children if c.get('adcode') and c.get('name')]

    def cache_path(self, province_code):
        reference = os.path.join(self.cache_dir, f'{province_code}_reference_v1.json')
        if os.path.exists(reference):
            return reference
        return os.path.join(self.cache_dir, f'{province_code}.json')

    def build_tree(self, province_code, max_level=4, table_name=DEFAULT_TABLE):
        """从省级码 BFS 下钻构建树（1省→2市→3区县→4乡镇；村级第5级从镜像读）。

        返回 list[dict]，每项 {code,name,level,parent}。
        先读本地缓存；残缺缓存（仅省级节点）视为无效，重新下钻。
        """
        cache = self.cache_path(province_code)
        if os.path.exists(cache):
            with open(cache, 'r', encoding='utf-8') as f:
                cached = json.load(f)
            if isinstance(cached, dict):
                nodes = cached.get('nodes') or []
                meta = cached.get('meta') or {}
                if meta.get('complete') and int(meta.get('max_level', 0)) >= max_level:
                    return nodes
            elif self._legacy_cache_complete(cached, max_level):
                return cached

        nodes = []
        province_name = next((n for n, c in PROVINCES.items() if c == province_code), '')
        # 省级节点（level=1）
        queue = [{'code': province_code, 'name': province_name, 'level': 1}]
        nodes.extend(queue)

        while queue:
            cur = queue.pop(0)
            if cur['level'] >= max_level:
                continue
            children = self.fetch_children(cur['code'], cur['name'], cur['level'],
                                           table_name=table_name)
            # 乡镇按名称排序，保证序号稳定（不依赖接口返回顺序，避免断点续传 code 漂移）
            if cur['level'] == 3:
                children = sorted(children, key=lambda c: c.get('name', ''))
            for idx, c in enumerate(children, 1):
                level = int(c.get('level', cur['level'] + 1))
                raw_code = str(c.get('code', '')).strip()
                code = pad_code(raw_code)
                if level >= 4 and (len(raw_code) < 9 or code == pad_code(cur['code'])):
                    # 乡镇/街道 adcode 与区县相同（高德 6 位码无乡镇级），用序号生成唯一码
                    code = pad_code(f'{str(cur["code"])[:6]}{idx:03d}')
                node = {
                    'code': code,
                    'name': c.get('name', ''),
                    'level': level,
                    'parent': cur['code'],
                }
                nodes.append(node)
                if node['level'] < max_level:
                    queue.append(node)
            # 每完成一层写缓存（断点续传：中途失败下次从缓存续）
            self._save_cache(cache, nodes, max_level=max_level, complete=False)

        self._save_cache(cache, nodes, max_level=max_level, complete=True)
        return nodes

    @staticmethod
    def _legacy_cache_complete(nodes, max_level):
        """Accept old list caches only when all requested levels are represented."""
        if not isinstance(nodes, list) or not nodes:
            return False
        levels = {int(n.get('level', 0)) for n in nodes if isinstance(n, dict)}
        return all(level in levels for level in range(1, max_level + 1))

    def _save_cache(self, cache, nodes, max_level, complete):
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        payload = {
            'meta': {
                'complete': bool(complete),
                'max_level': int(max_level),
                'updated_at': datetime.now().isoformat(timespec='seconds'),
                'source': '民政部→高德降级链',
            },
            'nodes': nodes,
        }
        temporary = cache + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(temporary, cache)


def load_villages(village_csv):
    """从本地村级清单 CSV 读取（fulldb 存档，列须含 编码/名称 或 code/name）。"""
    import csv
    if not os.path.exists(village_csv):
        return []
    villages = []
    with open(village_csv, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = str(row.get('编码') or row.get('行政村编码') or row.get('code') or '').strip()
            name = str(row.get('名称') or row.get('行政村名称') or row.get('name') or '').strip()
            if code and name:
                normalized = code.ljust(12, '0') if len(code) < 12 else code
                parent = str(row.get('乡镇编码') or row.get('parent') or normalized[:9]).strip()
                villages.append({
                    'code': normalized,
                    'name': name,
                    'level': 5,
                    'parent': pad_code(parent),
                    'city_name': row.get('地市名称') or row.get('city_name') or '',
                    'district_name': row.get('区县名称') or row.get('district_name') or '',
                    'town_name': row.get('乡镇名称') or row.get('town_name') or '',
                    'data_version': row.get('数据版本') or row.get('data_version') or '用户导入',
                    '经度(WGS84)': row.get('经度(WGS84)') or row.get('lon') or '',
                    '纬度(WGS84)': row.get('纬度(WGS84)') or row.get('lat') or '',
                    '匹配源': row.get('匹配源') or row.get('source') or '本地核验缓存',
                    '村级分类': row.get('村级分类') or '',
                    '数据来源': row.get('数据来源') or row.get('data_source') or '',
                })
    return villages
