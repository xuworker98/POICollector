# -*- coding: utf-8 -*-
"""M4 分类树解析 单测"""
from core import category
from core.category import (
    load_categories, find_node, collect_leaf_codes,
    resolve_to_leaf_codes, types_param,
)


def test_load_categories():
    cats = load_categories()
    assert len(cats) == 23  # 23 大类
    names = [c['name'] for c in cats]
    assert '科教文化服务' in names
    assert '医疗保健服务' in names


def test_school_codes():
    """学校编码与文档验证一致：141201 高等院校 等"""
    cats = load_categories()
    school = find_node(cats, '1412')
    assert school is not None
    assert school['name'] == '学校'
    leaves = collect_leaf_codes(school)
    assert '141201' in leaves  # 高等院校
    assert '141202' in leaves  # 中学
    assert '141203' in leaves  # 小学
    assert '141204' in leaves  # 幼儿园


def test_resolve_middle_to_leaves():
    """选中类「学校」= 全选其下所有小类"""
    cats = load_categories()
    leaves = resolve_to_leaf_codes(cats, ['1412'])
    assert len(leaves) == 8  # 学校下 8 个小类
    assert '141201' in leaves


def test_resolve_top_to_leaves():
    """选大类「科教文化服务」= 全选其下所有小类"""
    cats = load_categories()
    leaves = resolve_to_leaf_codes(cats, ['14'])
    assert len(leaves) > 8


def test_resolve_leaf_direct():
    """直接选小类码，返回自身"""
    cats = load_categories()
    leaves = resolve_to_leaf_codes(cats, ['141201'])
    assert leaves == ['141201']


def test_types_param():
    assert types_param(['141201', '141202', '141203']) == '141201|141202|141203'
