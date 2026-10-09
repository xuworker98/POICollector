# -*- coding: utf-8 -*-
"""SQLite-backed result store for resumable million-row POI tasks."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


class PoiStore:
    COLUMNS = ('key', 'province', 'city', 'name', 'type', 'typecode', 'district', 'adcode',
               'lon', 'lat', 'address', 'source', 'confidence')

    def __init__(self, path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.execute('PRAGMA synchronous=NORMAL')
        self.conn.execute('PRAGMA temp_store=MEMORY')
        self.conn.executescript('''
            CREATE TABLE IF NOT EXISTS poi (
                key TEXT PRIMARY KEY,
                province TEXT, city TEXT, name TEXT, type TEXT, typecode TEXT, district TEXT, adcode TEXT,
                lon REAL, lat REAL, address TEXT, source TEXT, confidence TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_poi_district ON poi(district);
            CREATE INDEX IF NOT EXISTS idx_poi_confidence ON poi(confidence);
            CREATE TABLE IF NOT EXISTS tasks (
                task_key TEXT PRIMARY KEY,
                completed_at TEXT NOT NULL,
                provider TEXT,
                row_count INTEGER NOT NULL DEFAULT 0
            );
        ''')
        columns = {row[1] for row in self.conn.execute('PRAGMA table_info(poi)')}
        for column in ('province', 'city'):
            if column not in columns:
                self.conn.execute(f'ALTER TABLE poi ADD COLUMN {column} TEXT DEFAULT ""')
        self.conn.commit()

    def task_done(self, task_key):
        row = self.conn.execute('SELECT 1 FROM tasks WHERE task_key=?', (task_key,)).fetchone()
        return row is not None

    def insert_pois(self, rows):
        values = []
        for item in rows:
            values.append((
                item['key'], item.get('province', ''), item.get('city', ''),
                item.get('name', ''), item.get('type', ''),
                item.get('typecode', ''), item.get('district', ''),
                item.get('adcode', ''), item.get('lon'), item.get('lat'),
                item.get('address', ''), item.get('source', ''),
                item.get('confidence', '待复核'),
            ))
        if not values:
            return 0
        before = self.conn.total_changes
        self.conn.executemany('''
            INSERT OR IGNORE INTO poi
            (key,province,city,name,type,typecode,district,adcode,lon,lat,address,source,confidence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', values)
        self.conn.commit()
        return self.conn.total_changes - before

    def mark_task_done(self, task_key, provider, row_count):
        self.conn.execute(
            'INSERT OR REPLACE INTO tasks(task_key,completed_at,provider,row_count) VALUES(?,?,?,?)',
            (task_key, datetime.now().isoformat(timespec='seconds'), provider, int(row_count)),
        )
        self.conn.commit()

    def count(self):
        return int(self.conn.execute('SELECT COUNT(*) FROM poi').fetchone()[0])

    def preview(self, limit=500, offset=0):
        cursor = self.conn.execute('''
            SELECT province,city,district,name,type,lon,lat,address,source,confidence,adcode,typecode
            FROM poi ORDER BY rowid LIMIT ? OFFSET ?
        ''', (int(limit), int(offset)))
        keys = ('省份','地市','区县','name','type','lon','lat','address','来源','置信度','adcode','typecode')
        return [dict(zip(keys, row)) for row in cursor]

    def filtered_preview(self, filters=None, search='', limit=500, offset=0):
        """Return one filtered page without loading the complete result set."""
        where, params = self._filter_sql(filters or {}, search)
        cursor = self.conn.execute(f'''
            SELECT province,city,district,name,type,lon,lat,address,source,confidence,adcode,typecode
            FROM poi {where} ORDER BY rowid LIMIT ? OFFSET ?
        ''', (*params, int(limit), int(offset)))
        keys = ('省份','地市','区县','name','type','lon','lat','address','来源','置信度','adcode','typecode')
        return [dict(zip(keys, row)) for row in cursor]

    def filtered_count(self, filters=None, search=''):
        where, params = self._filter_sql(filters or {}, search)
        return int(self.conn.execute(f'SELECT COUNT(*) FROM poi {where}', params).fetchone()[0])

    @staticmethod
    def _filter_sql(filters, search):
        clauses, params = [], []
        columns = {'district': 'district', 'type': 'type', 'source': 'source', 'confidence': 'confidence'}
        for key, column in columns.items():
            value = str(filters.get(key) or '').strip()
            if value:
                clauses.append(f'{column}=?'); params.append(value)
        qc = str(filters.get('qc') or '')
        if qc == '有效':
            clauses.append("confidence IN ('高','中') AND lon BETWEEN 73 AND 135 AND lat BETWEEN 3 AND 54")
        elif qc == '待复核':
            clauses.append("(confidence NOT IN ('高','中') OR confidence IS NULL OR confidence='')")
        elif qc == '异常':
            clauses.append('(lon NOT BETWEEN 73 AND 135 OR lat NOT BETWEEN 3 AND 54 OR lon IS NULL OR lat IS NULL)')
        search = str(search or '').strip()
        if search:
            clauses.append('(name LIKE ? OR address LIKE ?)'); params.extend([f'%{search}%', f'%{search}%'])
        return ('WHERE ' + ' AND '.join(clauses) if clauses else ''), tuple(params)

    def quality_counts(self):
        row = self.conn.execute('''
            SELECT COUNT(*),
                   SUM(CASE WHEN confidence IN ('高','中') AND lon BETWEEN 73 AND 135 AND lat BETWEEN 3 AND 54 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN confidence NOT IN ('高','中') OR confidence IS NULL OR confidence='' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN lon NOT BETWEEN 73 AND 135 OR lat NOT BETWEEN 3 AND 54 OR lon IS NULL OR lat IS NULL THEN 1 ELSE 0 END)
            FROM poi
        ''').fetchone()
        return tuple(int(value or 0) for value in row)

    def iter_rows(self, batch_size=5000):
        cursor = self.conn.execute('''
            SELECT province,city,district,name,type,lon,lat,address,source,confidence,adcode,typecode
            FROM poi ORDER BY rowid
        ''')
        while True:
            batch = cursor.fetchmany(batch_size)
            if not batch:
                break
            yield from batch

    def summary(self):
        return list(self.conn.execute(
            'SELECT district,COUNT(*) FROM poi GROUP BY district ORDER BY district'
        ))

    def close(self):
        self.conn.close()
