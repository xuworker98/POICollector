# -*- coding: utf-8 -*-
"""配额管理 + 断点续传 + 日预算停机"""
import csv
import json
import os
from datetime import date


class QuotaManager:
    """四源日配额管理：轮换 + 耗尽停机。"""

    def __init__(self, daily_caps=None, source_priority=None, state_path=None):
        self.daily_caps = daily_caps or {}
        self.source_priority = source_priority or ['tianditu', 'amap', 'baidu', 'tencent']
        self.used = {s: 0 for s in self.source_priority}
        self.exhausted = {s: False for s in self.source_priority}
        self._date = date.today()
        self.state_path = state_path
        self._load_state()

    def _load_state(self):
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, 'r', encoding='utf-8') as stream:
                state = json.load(stream)
            if state.get('date') != date.today().isoformat():
                return
            for source in self.source_priority:
                self.used[source] = int((state.get('used') or {}).get(source, 0))
                self.exhausted[source] = bool((state.get('exhausted') or {}).get(source, False))
        except (OSError, ValueError, TypeError):
            return

    def _save_state(self):
        if not self.state_path:
            return
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
        temporary = self.state_path + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump({'date': self._date.isoformat(), 'used': self.used,
                       'exhausted': self.exhausted}, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, self.state_path)

    def _reset_if_new_day(self):
        today = date.today()
        if today != self._date:
            self._date = today
            self.used = {s: 0 for s in self.source_priority}
            self.exhausted = {s: False for s in self.source_priority}
            self._save_state()

    def current_source(self):
        """返回第一个未耗尽的源；全部耗尽返回 None（触发停机）。"""
        self._reset_if_new_day()
        for s in self.source_priority:
            if not self.exhausted[s]:
                return s
        return None

    def record_call(self, source):
        """记录一次成功调用，达到上限自动标记耗尽。"""
        self.used[source] = self.used.get(source, 0) + 1
        cap = self.daily_caps.get(source)
        if cap and self.used[source] >= cap:
            self.exhausted[source] = True
        self._save_state()

    def mark_exhausted(self, source):
        self.exhausted[source] = True
        self._save_state()

    def all_exhausted(self, sources=None):
        selected = list(sources) if sources is not None else list(self.exhausted)
        return bool(selected) and all(self.exhausted.get(source, True) for source in selected)

    def snapshot(self):
        """返回四源配额快照（供 UI 配额监控条展示）。"""
        return {
            s: {
                'used': self.used[s],
                'cap': self.daily_caps.get(s, 0),
                'exhausted': self.exhausted[s],
            }
            for s in self.source_priority
        }


class Checkpoint:
    """断点文件：CSV append 模式记录已完成条目，重启时读 done_keys 跳过。

    区划模式以「编码」为去重键，POI 模式以「(name, adcode, 坐标4位小数) 三元组」为去重键。
    每 flush_every 条写盘一次，任务结束/停机时调用 flush() 兜底。
    """

    def __init__(self, path, columns, key_col='_key', flush_every=100):
        self.path = path
        self.columns = columns
        self.key_col = key_col
        self.flush_every = flush_every
        self.done_keys = set()
        self._buffer = []
        self._loaded = False

    def load(self):
        """加载已完成的去重键集合。"""
        self.done_keys = set()
        if os.path.exists(self.path):
            with open(self.path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    k = row.get(self.key_col)
                    if k:
                        self.done_keys.add(k)
        self._loaded = True

    def load_all(self):
        """加载所有已完成记录，返回 {key: row_dict}（含坐标等完整字段，供断点续传恢复）。"""
        records = {}
        if os.path.exists(self.path):
            with open(self.path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    k = row.get(self.key_col)
                    if k:
                        records[k] = row
        return records

    def is_done(self, key):
        if not self._loaded:
            self.load()
        return key in self.done_keys

    def append(self, row):
        """追加一条已完成记录（缓冲，每 flush_every 条写盘）。"""
        self._buffer.append(row)
        if len(self._buffer) >= self.flush_every:
            self.flush()

    def flush(self):
        """将缓冲写入磁盘（任务结束/停机/每100条时调用）。"""
        if not self._buffer:
            return
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        need_header = not os.path.exists(self.path)
        with open(self.path, 'a', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=self.columns)
            if need_header:
                writer.writeheader()
            for row in self._buffer:
                writer.writerow(row)
        for row in self._buffer:
            self.done_keys.add(row.get(self.key_col, ''))
        self._buffer = []
