# -*- coding: utf-8 -*-
"""用户图层导入：pyogrio 解析 + 坐标系检测 + 转 WGS84。

⚠ 坐标系判断错误会导致边界校验全错——这是最易翻车环节。
导入时强制坐标系检测（读 .prj / 元数据），检测失败拒绝入库。
"""
import os


def detect_crs(path):
    """读取图层坐标系，返回 EPSG 字符串（如 'EPSG:4326'）或 None。"""
    try:
        import pyogrio
        info = pyogrio.read_info(path)
        crs = info.get('crs') or info.get('crs_wkt')
        return crs
    except Exception:
        return None


def list_layers(path):
    """列出一个文件可包含的多个图层。"""
    try:
        import pyogrio
        return pyogrio.list_layers(path)
    except Exception:
        return []


def import_layer_to_wgs84(path, source_crs=None):
    """读取图层所有要素，统一转 WGS84，返回 [{geometry: GeoJSON, properties: dict}]。

    source_crs: 可选覆盖值；默认读取图层元数据。西安80/北京54必须有明确分带定义。
    """
    import pyogrio
    from pyproj import CRS, Transformer
    from shapely.ops import transform as shapely_transform

    gdf = pyogrio.read_dataframe(path)
    features = []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        geojson = geom.__geo_interface__
        chosen_crs = source_crs or getattr(gdf, 'crs', None)
        # 坐标系归一
        if str(chosen_crs).upper().startswith('GCJ'):
            geojson = _geojson_gcj_to_wgs84(geojson)
        else:
            aliases = {'WGS84': 'EPSG:4326', 'CGCS2000': 'EPSG:4490'}
            chosen_crs = aliases.get(str(chosen_crs).upper(), chosen_crs)
            if str(chosen_crs).upper() in ('西安80', '北京54', 'XIAN80', 'BEIJING54'):
                raise ValueError('西安80/北京54存在多个分带，请提供图层.prj或明确EPSG/PROJ字符串，禁止猜测')
            if not chosen_crs:
                raise ValueError('无法识别图层坐标系，已拒绝导入')
            source = CRS.from_user_input(chosen_crs)
            if source != CRS.from_epsg(4326):
                transformer = Transformer.from_crs(source, 'EPSG:4326', always_xy=True)
                geom = shapely_transform(transformer.transform, geom)
                geojson = geom.__geo_interface__
        features.append({'geometry': geojson, 'properties': {k: v for k, v in row.items() if k != 'geometry'}})
    return features


def _geojson_gcj_to_wgs84(geojson):
    from core.coords import gcj02_to_wgs84
    gtype = geojson.get('type')
    if gtype == 'Point':
        lon, lat = geojson['coordinates']
        return {'type': 'Point', 'coordinates': list(gcj02_to_wgs84(lon, lat))}
    if gtype in ('Polygon', 'MultiPolygon'):
        def conv_ring(ring):
            return [list(gcj02_to_wgs84(lon, lat)) for lon, lat in ring]
        if gtype == 'Polygon':
            return {'type': 'Polygon', 'coordinates': [conv_ring(r) for r in geojson['coordinates']]}
        return {'type': 'MultiPolygon',
                'coordinates': [[conv_ring(r) for r in poly] for poly in geojson['coordinates']]}
    return geojson
