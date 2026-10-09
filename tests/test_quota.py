# -*- coding: utf-8 -*-
"""M2 配额管理 + 断点续传 单测（纯逻辑，不依赖网络）"""
import os

import pytest

import core.quota as quota_mod
from core.quota import QuotaManager, Checkpoint


@pytest.fixture
def qm():
    return QuotaManager(
        daily_caps={'tianditu': 3, 'amap': 2, 'baidu': 2, 'tencent': 1},
        source_priority=['tianditu', 'amap', 'baidu', 'tencent'],
    )


def test_current_source_priority_order(qm):
    assert qm.current_source() == 'tianditu'


def test_record_call_reaches_cap_auto_exhaust(qm):
    qm.record_call('tianditu')
    qm.record_call('tianditu')
    qm.record_call('tianditu')  # 达 cap=3
    assert qm.exhausted['tianditu'] is True
    assert qm.current_source() == 'amap'


def test_rotation_after_exhaust(qm):
    qm.mark_exhausted('tianditu')
    qm.mark_exhausted('amap')
    assert qm.current_source() == 'baidu'


def test_all_exhausted_returns_none(qm):
    for s in ['tianditu', 'amap', 'baidu', 'tencent']:
        qm.mark_exhausted(s)
    assert qm.current_source() is None
    assert qm.all_exhausted() is True


def test_new_day_resets(monkeypatch, qm):
    qm.mark_exhausted('tianditu')
    # 模拟跨天
    from datetime import date, timedelta
    tomorrow = date.today() + timedelta(days=1)
    monkeypatch.setattr(quota_mod, 'date', _FakeDate(tomorrow))
    assert qm.current_source() == 'tianditu'
    assert qm.exhausted['tianditu'] is False


class _FakeDate:
    def __init__(self, d):
        self._d = d

    def today(self):
        return self._d


def test_checkpoint_append_flush_load(tmp_path):
    path = os.path.join(tmp_path, 'checkpoints', 'task.csv')
    columns = ['_key', '编码', '名称', '经度', '纬度']
    cp = Checkpoint(path, columns, key_col='_key', flush_every=2)

    cp.append({'_key': '4501', '编码': '4501', '名称': '南宁市', '经度': 108.3, '纬度': 22.8})
    assert not os.path.exists(path)  # 未达 flush_every 不写盘
    cp.append({'_key': '4502', '编码': '4502', '名称': '柳州市', '经度': 109.4, '纬度': 24.3})
    assert os.path.exists(path)      # 达到 2 条，自动 flush

    cp.append({'_key': '4503', '编码': '4503', '名称': '桂林市', '经度': 110.2, '纬度': 25.2})
    cp.flush()  # 兜底写盘

    # 重新加载（模拟重启）
    cp2 = Checkpoint(path, columns, key_col='_key')
    cp2.load()
    assert cp2.done_keys == {'4501', '4502', '4503'}
    assert cp2.is_done('4501') is True
    assert cp2.is_done('9999') is False


def test_checkpoint_no_duplicate_on_restart(tmp_path):
    """断点不重：重启后已完成的 key 被跳过，不会重复处理。"""
    path = os.path.join(tmp_path, 'checkpoints', 'task.csv')
    columns = ['_key', '名称']
    cp = Checkpoint(path, columns, flush_every=1)
    cp.append({'_key': 'A', '名称': '甲'})
    cp.append({'_key': 'B', '名称': '乙'})

    cp2 = Checkpoint(path, columns)
    cp2.load()
    # 模拟重启后重跑：A/B 应跳过，只有 C 是新任务
    assert cp2.is_done('A')
    assert cp2.is_done('B')
    assert not cp2.is_done('C')
