# -*- coding: utf-8 -*-
"""core.utils 度分秒解析 / 坐标校验测试。"""
import pytest

from core.utils import parse_coordinate_str, validate_coordinate


def test_parse_decimal():
    assert parse_coordinate_str('113.123456') == pytest.approx(113.123456)
    assert parse_coordinate_str(' 22.8167 ') == pytest.approx(22.8167)


def test_parse_dms():
    """度分秒格式"""
    assert parse_coordinate_str('113°22′00″E') == pytest.approx(113.3666667, abs=1e-6)
    assert parse_coordinate_str('113°22\'00"') == pytest.approx(113.3666667, abs=1e-6)
    assert parse_coordinate_str('113度22分30秒') == pytest.approx(113.375, abs=1e-6)


def test_parse_colon():
    assert parse_coordinate_str('113:22:00') == pytest.approx(113.3666667, abs=1e-6)


def test_parse_direction():
    """方向字母 S/W 为负"""
    assert parse_coordinate_str('22°30′00″S') == pytest.approx(-22.5, abs=1e-6)
    assert parse_coordinate_str('113.123456W') == pytest.approx(-113.123456)


def test_parse_invalid():
    assert parse_coordinate_str('') is None
    assert parse_coordinate_str('abc') is None


def test_validate_coordinate():
    assert validate_coordinate(116.39, 39.90) is True
    assert validate_coordinate(200, 39.90) is False
    assert validate_coordinate(116.39, 100) is False
