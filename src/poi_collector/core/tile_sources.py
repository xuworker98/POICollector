# -*- coding: utf-8 -*-
"""Basemap presets and custom XYZ/TMS source validation.

Basemaps are deliberately independent from POI query providers.  A map can use
anonymous ArcGIS imagery while POI records are collected from Tianditu/Amap.
"""
from __future__ import annotations

from copy import deepcopy
from urllib.parse import urlparse


BUILTIN_TILE_SOURCES = [
    {
        "id": "arcgis_imagery",
        "name": "ArcGIS卫星影像",
        "kind": "xyz",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "min_zoom": 0,
        "max_zoom": 19,
        "attribution": "Esri, Maxar, Earthstar Geographics, GIS User Community",
        "requires_key": False,
    },
    {
        "id": "arcgis_hybrid",
        "name": "ArcGIS卫星混合",
        "kind": "xyz",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "overlay_url": "https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}",
        "min_zoom": 0,
        "max_zoom": 19,
        "attribution": "Esri, Maxar, Earthstar Geographics, GIS User Community",
        "requires_key": False,
    },
    {
        "id": "arcgis_street",
        "name": "ArcGIS街道图",
        "kind": "xyz",
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "min_zoom": 0,
        "max_zoom": 19,
        "attribution": "Esri and data providers",
        "requires_key": False,
    },
    {
        "id": "osm_standard",
        "name": "OpenStreetMap",
        "kind": "xyz",
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "min_zoom": 0,
        "max_zoom": 19,
        "attribution": "© OpenStreetMap contributors",
        "requires_key": False,
    },
]


def tianditu_sources(key: str) -> list[dict]:
    """Return Tianditu presets only when a display key is configured."""
    key = (key or "").strip()
    if not key:
        return []
    common = (
        "https://t{s}.tianditu.gov.cn/{layer}_w/wmts?SERVICE=WMTS&REQUEST=GetTile"
        "&VERSION=1.0.0&LAYER={layer}&STYLE=default&TILEMATRIXSET=w"
        "&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=" + key
    )
    return [
        {
            "id": "tianditu_vector",
            "name": "天地图矢量",
            "kind": "xyz",
            "url": common.format(layer="vec", s="{s}", z="{z}", y="{y}", x="{x}"),
            "overlay_url": common.format(layer="cva", s="{s}", z="{z}", y="{y}", x="{x}"),
            "subdomains": "01234567",
            "min_zoom": 1,
            "max_zoom": 18,
            "attribution": "天地图",
            "requires_key": True,
        },
        {
            "id": "tianditu_imagery",
            "name": "天地图影像",
            "kind": "xyz",
            "url": common.format(layer="img", s="{s}", z="{z}", y="{y}", x="{x}"),
            "overlay_url": common.format(layer="cia", s="{s}", z="{z}", y="{y}", x="{x}"),
            "subdomains": "01234567",
            "min_zoom": 1,
            "max_zoom": 18,
            "attribution": "天地图",
            "requires_key": True,
        },
    ]


def validate_tile_source(source: dict) -> dict:
    """Normalize and validate a user-defined XYZ/TMS source."""
    item = deepcopy(source)
    name = str(item.get("name") or "").strip()
    url = str(item.get("url") or "").strip()
    kind = str(item.get("kind") or "xyz").lower()
    if not name:
        raise ValueError("图源名称不能为空")
    if kind not in {"xyz", "tms"}:
        raise ValueError("当前版本自定义图源支持 XYZ 或 TMS")
    if not all(token in url for token in ("{z}", "{x}", "{y}")):
        raise ValueError("瓦片地址必须包含 {z}、{x}、{y}")
    parsed = urlparse(url.replace("{s}", "a").replace("{z}", "0").replace("{x}", "0").replace("{y}", "0"))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("瓦片地址必须是有效的 HTTP/HTTPS URL")
    min_zoom = int(item.get("min_zoom", 0))
    max_zoom = int(item.get("max_zoom", 19))
    if min_zoom < 0 or max_zoom > 24 or min_zoom > max_zoom:
        raise ValueError("缩放级别应满足 0 ≤ 最小级别 ≤ 最大级别 ≤ 24")
    item.update({
        "id": str(item.get("id") or "").strip(),
        "name": name,
        "url": url,
        "kind": kind,
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
        "subdomains": str(item.get("subdomains") or "abc"),
        "attribution": str(item.get("attribution") or "").strip(),
        "overlay_url": str(item.get("overlay_url") or "").strip(),
        "requires_key": bool(item.get("requires_key", False)),
    })
    return item


def available_tile_sources(cfg: dict) -> list[dict]:
    """Build the effective source list, skipping invalid custom entries."""
    result = deepcopy(BUILTIN_TILE_SOURCES)
    map_keys = cfg.get("map_keys") or {}
    tdt_key = map_keys.get("tianditu") or (cfg.get("keys") or {}).get("tianditu", "")
    result.extend(tianditu_sources(tdt_key))
    # Browser JavaScript SDK entries from V1.x/V2.0-WebEngine are intentionally
    # ignored. The native Qt renderer accepts deterministic raster XYZ/TMS only.
    for index, source in enumerate((cfg.get("basemap") or {}).get("custom_sources") or []):
        try:
            item = validate_tile_source(source)
        except (TypeError, ValueError):
            continue
        item["id"] = item.get("id") or f"custom_{index + 1}"
        result.append(item)
    return result


def source_by_id(cfg: dict, source_id: str) -> dict | None:
    return next((item for item in available_tile_sources(cfg) if item["id"] == source_id), None)
