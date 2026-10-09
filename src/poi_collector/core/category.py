# -*- coding: utf-8 -*-
"""分类树加载 + 统一分类层映射"""
import json
import os

from core.config import PROJECT_ROOT

CATEGORY_PATH = os.path.join(PROJECT_ROOT, 'data', 'categories', 'amap_categories.json')


def load_categories():
    with open(CATEGORY_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def find_node(categories, code):
    """按 code 递归查找节点。"""
    for cat in categories:
        if cat.get('code') == code:
            return cat
        if cat.get('children'):
            found = find_node(cat['children'], code)
            if found:
                return found
    return None


def collect_leaf_codes(node):
    """收集某节点（大类/中类）下所有小类码（叶子 code）。"""
    children = node.get('children')
    if not children:
        return [node['code']]
    codes = []
    for c in children:
        codes.extend(collect_leaf_codes(c))
    return codes


def resolve_to_leaf_codes(categories, selected_codes):
    """把用户选中的大类/中类/小类 code 解析为叶子小类码列表（去重保序）。"""
    leaf_codes = []
    seen = set()
    for code in selected_codes:
        node = find_node(categories, code)
        if node is None:
            continue
        for leaf in collect_leaf_codes(node):
            if leaf not in seen:
                seen.add(leaf)
                leaf_codes.append(leaf)
    return leaf_codes


def types_param(leaf_codes):
    """高德 types 参数：小类码用 | 分隔。"""
    return '|'.join(leaf_codes)


def flatten_names(selected_codes, categories):
    """返回选中项的展示名（如「科教文化服务 › 学校 › 小学」）。"""
    names = []
    for code in selected_codes:
        node = find_node(categories, code)
        if node:
            names.append(node['name'])
    return '、'.join(names)
