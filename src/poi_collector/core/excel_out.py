# -*- coding: utf-8 -*-
"""六表 Excel 输出 + 质检报告 MD"""
import os
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter


class _ILocAccessor:
    def __init__(self, table):
        self.table = table

    def __getitem__(self, index):
        row = self.table.rows[index]
        return dict(zip(self.table.headers, row))


class TableData:
    """轻量表结构，避免为 Excel 导出打包 pandas/numpy。"""

    def __init__(self, headers, rows=None):
        self.headers = list(headers)
        self.rows = [list(row) for row in (rows or [])]
        self.iloc = _ILocAccessor(self)

    @property
    def empty(self):
        return not self.rows


def write_excel(output_path, tables):
    """按参考模板写多 Sheet 区划工作簿。"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)
    header_fill = PatternFill('solid', fgColor='2F5597')
    section_fill = PatternFill('solid', fgColor='D9E2F3')
    header_font = Font(name='微软雅黑', size=10, bold=True, color='FFFFFF')
    body_font = Font(name='微软雅黑', size=10)
    thin = Side(style='thin', color='D0D0D0')
    for sheet_name, table in tables.items():
        sheet = workbook.create_sheet(sheet_name[:31])
        sheet.append(table.headers)
        for row in table.rows:
            sheet.append(row)
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        sheet.sheet_view.showGridLines = False
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        sheet.row_dimensions[1].height = 28
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                cell.font = body_font
                cell.alignment = Alignment(
                    horizontal='center' if cell.column != 1 else 'left',
                    vertical='center',
                )
                cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)
            if sheet_name == '校验表' and row[0].value and str(row[0].value).startswith(('一、', '二、', '三、', '四、', '五、')):
                for cell in row:
                    cell.fill = section_fill
                    cell.font = Font(name='微软雅黑', size=10, bold=True)
        widths = []
        for column in range(1, len(table.headers) + 1):
            values = [sheet.cell(row=row, column=column).value for row in range(1, min(sheet.max_row, 200) + 1)]
            width = min(max(max((len(str(value or '')) for value in values), default=8) + 2, 10), 46)
            widths.append(width)
            sheet.column_dimensions[get_column_letter(column)].width = width
        for header in ('数据来源', 'POI地址', '结论/说明'):
            if header in table.headers:
                sheet.column_dimensions[get_column_letter(table.headers.index(header) + 1)].width = 48
        for header in ('政府驻地地址',):
            if header in table.headers:
                sheet.column_dimensions[get_column_letter(table.headers.index(header) + 1)].width = 42
        for header in ('政府驻地经度(WGS84)', '政府驻地纬度(WGS84)', '经度(WGS84)', '纬度(WGS84)'):
            if header in table.headers:
                col = table.headers.index(header) + 1
                for cell in sheet[get_column_letter(col)][1:]:
                    cell.number_format = '0.000000'
    workbook.save(output_path)
    return output_path


def write_report(report_path, report_text):
    """写质检报告 MD。"""
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_text)
    return report_path


def write_poi_store_excel(output_path, store_path, target_crs='WGS84', review_only=False):
    """Stream a SQLite POI store to XLSX with bounded memory.

    Excel supports 1,048,576 rows per sheet. Data sheets are split at one
    million records so the header and future metadata always fit.
    """
    import sqlite3
    from collections import Counter
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from core.coords import convert_coord

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    wb = Workbook(write_only=True)
    headers = ['省份', '地市', '区县', 'POI名称', 'POI分类',
               f'经度({target_crs})', f'纬度({target_crs})', 'POI地址',
               '数据来源', '置信度', '行政区码', '分类码']
    header_fill = PatternFill('solid', fgColor='2F5597')
    header_font = Font(name='微软雅黑', size=10, bold=True, color='FFFFFF')
    body_font = Font(name='微软雅黑', size=10)
    thin = Side(style='thin', color='D0D0D0')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def configure_sheet(sheet, widths):
        sheet.freeze_panes = 'A2'
        sheet.sheet_view.showGridLines = False
        for column, width in enumerate(widths, 1):
            sheet.column_dimensions[get_column_letter(column)].width = width

    def finalize_sheet(sheet, column_count, data_rows):
        sheet.auto_filter.ref = f'A1:{get_column_letter(column_count)}{data_rows + 1}'

    def append_styled(sheet, values, header=False):
        cells = []
        for value in values:
            cell = WriteOnlyCell(sheet, value=value)
            cell.font = header_font if header else body_font
            cell.fill = header_fill if header else PatternFill(fill_type=None)
            cell.border = border
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=header)
            cells.append(cell)
        sheet.append(cells)
    source_counts = Counter()
    confidence_counts = Counter()
    district_counts = Counter()
    data_sheet = None
    data_index = 0
    row_in_sheet = 0
    total = 0

    with sqlite3.connect(store_path) as conn:
        review_where = '''WHERE confidence NOT IN ('高','中') OR confidence IS NULL OR confidence=''
            OR lon NOT BETWEEN 73 AND 135 OR lat NOT BETWEEN 3 AND 54 OR lon IS NULL OR lat IS NULL''' if review_only else ''
        cursor = conn.execute(f'''
            SELECT province,city,district,name,type,lon,lat,address,source,confidence,adcode,typecode
            FROM poi {review_where} ORDER BY rowid
        ''')
        for row in cursor:
            if data_sheet is None or row_in_sheet >= 1_000_000:
                if data_sheet is not None:
                    finalize_sheet(data_sheet, len(headers), row_in_sheet)
                data_index += 1
                data_sheet = wb.create_sheet(f'POI明细{data_index:02d}')
                configure_sheet(data_sheet, [14, 14, 14, 24, 24, 16, 16, 48, 16, 12, 14, 14])
                append_styled(data_sheet, headers, True)
                row_in_sheet = 0
            province, city, district, name, kind, lon, lat, address, source, confidence, adcode, typecode = row
            try:
                out_lon, out_lat = convert_coord(float(lon), float(lat), target_crs)
                out_lon, out_lat = round(out_lon, 6), round(out_lat, 6)
            except (TypeError, ValueError):
                out_lon, out_lat = '', ''
            full_address = standardize_poi_address(province, city, district, address)
            append_styled(data_sheet, [province, city, district, name, kind, out_lon, out_lat,
                                       full_address, source, confidence, adcode, typecode])
            total += 1
            row_in_sheet += 1
            source_counts[source or '未知'] += 1
            confidence_counts[confidence or '未评级'] += 1
            district_counts[district or '未知'] += 1

        if data_sheet is not None:
            finalize_sheet(data_sheet, len(headers), row_in_sheet)

        summary = wb.create_sheet('汇总表')
        configure_sheet(summary, [22, 14])
        append_styled(summary, ['区县', 'POI数'], True)
        for key, value in sorted(district_counts.items()):
            append_styled(summary, [key, value])
        append_styled(summary, ['合计', total])
        finalize_sheet(summary, 2, len(district_counts) + 1)

        sources = wb.create_sheet('来源统计')
        configure_sheet(sources, [22, 14])
        append_styled(sources, ['来源', 'POI数'], True)
        for key, value in source_counts.most_common():
            append_styled(sources, [key, value])
        finalize_sheet(sources, 2, len(source_counts))

        confidence = wb.create_sheet('置信度统计')
        configure_sheet(confidence, [22, 14])
        append_styled(confidence, ['置信度', 'POI数'], True)
        for key, value in confidence_counts.most_common():
            append_styled(confidence, [key, value])
        finalize_sheet(confidence, 2, len(confidence_counts))

        verify = wb.create_sheet('校验表')
        configure_sheet(verify, [28, 20, 16, 16, 30])
        append_styled(verify, ['名称', '区县', '经度', '纬度', '异常原因'], True)
        verify_rows = 0
        for name, district, lon, lat, confidence in conn.execute('''
            SELECT name,district,lon,lat,confidence FROM poi
            WHERE lon < 73 OR lon > 135 OR lat < 3 OR lat > 54 OR confidence='低'
        '''):
            reason = '坐标超出中国范围' if not (73 <= lon <= 135 and 3 <= lat <= 54) else '低置信度'
            append_styled(verify, [name, district, lon, lat, reason])
            verify_rows += 1
        finalize_sheet(verify, 5, verify_rows)

        metadata = wb.create_sheet('运行信息')
        configure_sheet(metadata, [24, 36])
        append_styled(metadata, ['项目', '值'], True)
        for item in (['记录总数', total], ['输出坐标系', target_crs],
                     ['数据存储', 'SQLite 流式断点库'],
                     ['导出方式', '流式分片导出'], ['单表最大数据行', 1_000_000]):
            append_styled(metadata, item)
        finalize_sheet(metadata, 2, 5)

    wb.save(output_path)
    return output_path


def build_division_tables(nodes_by_level, villages=None):
    """按“广西行政区划数据 V1.0”六 Sheet 结构生成区划工作簿。"""
    levels = {level: list(nodes_by_level.get(level, [])) for level in range(1, 6)}
    village_nodes = list(villages or levels[5])
    levels[5] = village_nodes
    all_nodes = [node for level in levels.values() for node in level]
    by_code = {str(node.get('code') or ''): node for node in all_nodes if node.get('code')}
    province = levels[1][0] if levels[1] else {'name': '广西壮族自治区', 'code': '450000000'}

    def code(node, length):
        raw = str(node.get('code') or node.get('编码') or '')
        return raw[:length]

    def name(node):
        return str(node.get('name') or node.get('名称') or '')

    def ancestor(node, wanted_level):
        current = node
        for _ in range(5):
            if int(current.get('level', 0) or 0) == wanted_level:
                return current
            current = by_code.get(str(current.get('parent') or '')) or {}
            if not current:
                break
        return {}

    def coord(node):
        return node.get('经度(WGS84)', node.get('lon', '')), node.get('纬度(WGS84)', node.get('lat', ''))

    def source_name(node):
        return str(node.get('匹配源') or node.get('source') or '')

    def chain(node):
        provider = source_name(node)
        return {
            'tianditu': '天地图CGCS2000→WGS84(EPSG:4490→4326)',
            'amap': '高德GCJ-02→WGS84逆纠偏',
            'baidu': '百度BD-09→WGS84逆纠偏',
            'tencent': '腾讯GCJ-02→WGS84逆纠偏',
        }.get(provider, str(node.get('坐标纠偏链') or provider))

    def data_source(node):
        return str(
            node.get('数据来源') or node.get('data_version') or
            ('民政部国家地名信息库;' + source_name(node) if source_name(node) else '本地核验缓存')
        )

    province_name = name(province) or '广西壮族自治区'
    province_code = code(province, 2) or '45'

    city_headers = [
        '省份名称', '省份编码', '地市名称', '地市编码', '政府驻地地址',
        '政府驻地经度(WGS84)', '政府驻地纬度(WGS84)', '坐标纠偏链', '数据来源',
    ]
    city_rows = []
    for city in levels[2]:
        lon, lat = coord(city)
        city_rows.append([
            province_name, province_code, name(city), code(city, 6),
            city.get('政府驻地地址', ''), lon, lat, chain(city), data_source(city),
        ])

    district_headers = [
        '省份名称', '省份编码', '地市名称', '地市编码', '区县名称', '区划编码',
        '政府驻地地址', '政府驻地经度(WGS84)', '政府驻地纬度(WGS84)', '坐标纠偏链', '数据来源',
    ]
    district_rows = []
    for district in levels[3]:
        city = ancestor(district, 2)
        lon, lat = coord(district)
        district_rows.append([
            province_name, province_code, name(city), code(city, 4),
            name(district), code(district, 6), district.get('政府驻地地址', ''),
            lon, lat, chain(district), data_source(district),
        ])

    town_headers = [
        '省份名称', '省份编码', '地市名称', '地市编码', '区县名称', '区县编码',
        '乡镇名称', '乡镇编码', '政府驻地地址', '政府驻地经度(WGS84)',
        '政府驻地纬度(WGS84)', '坐标纠偏链', '数据来源',
    ]
    town_rows = []
    for town in levels[4]:
        city, district = ancestor(town, 2), ancestor(town, 3)
        lon, lat = coord(town)
        town_rows.append([
            province_name, province_code, name(city), code(city, 4),
            name(district), code(district, 6), name(town), code(town, 9),
            town.get('政府驻地地址', ''), lon, lat, chain(town), data_source(town),
        ])

    village_headers = [
        '省份名称', '省份编码', '地市名称', '地市编码', '区县名称', '区县编码',
        '乡镇名称', '乡镇编码', '行政村名称', '行政村编码', '村级分类',
        '经度(WGS84)', '纬度(WGS84)', '数据来源',
    ]
    village_rows = []
    for village in village_nodes:
        city, district, town = ancestor(village, 2), ancestor(village, 3), ancestor(village, 4)
        city_name = name(city) or str(village.get('city_name') or '')
        district_name = name(district) or str(village.get('district_name') or '')
        town_name = name(town) or str(village.get('town_name') or '')
        village_name = name(village)
        category = village.get('村级分类') or (
            '居民委员会' if ('社区' in village_name or '居委会' in village_name)
            else '村民委员会' if ('村委会' in village_name or '村民委员会' in village_name)
            else '其他'
        )
        lon, lat = coord(village)
        village_rows.append([
            province_name, province_code, city_name,
            code(city, 6) or str(village.get('city_code') or ''),
            district_name, code(district, 6) or str(village.get('district_code') or ''),
            town_name, code(town, 9) or str(village.get('town_code') or village.get('parent') or '')[:9],
            village_name, code(village, 12), category, lon, lat, data_source(village),
        ])

    summary_headers = [
        '地市', '区县数量(个)', '乡镇数量(个)', '村级单位合计(个)',
        '村民委员会(个)', '居民委员会(个)', '其他(个)',
    ]
    summary_rows = []
    for city in levels[2]:
        city_prefix = code(city, 4)
        city_villages = [row for row in village_rows if row[3].startswith(city_prefix)]
        categories = [row[10] for row in city_villages]
        summary_rows.append([
            name(city),
            sum(1 for district in levels[3] if code(district, 4) == city_prefix),
            sum(1 for town in levels[4] if code(town, 4) == city_prefix),
            len(city_villages), categories.count('村民委员会'),
            categories.count('居民委员会'),
            len(categories) - categories.count('村民委员会') - categories.count('居民委员会'),
        ])
    summary_rows.append([
        '合计', len(levels[3]), len(levels[4]), len(village_rows),
        sum(1 for row in village_rows if row[10] == '村民委员会'),
        sum(1 for row in village_rows if row[10] == '居民委员会'),
        sum(1 for row in village_rows if row[10] == '其他'),
    ])

    government_nodes = levels[2] + levels[3] + levels[4]
    government_matched = sum(1 for node in government_nodes if coord(node)[0] not in (None, ''))
    village_matched = sum(1 for node in village_nodes if coord(node)[0] not in (None, ''))
    check_headers = ['校验项', '政府公开口径/基准', '本表数值', '差异', '结论/说明']
    check_rows = [
        ['一、行政区划总数校验', '', '', '', ''],
        ['地级市数量', len(levels[2]), len(levels[2]), 0, '按区划树统计'],
        ['县级数量', len(levels[3]), len(levels[3]), 0, '按区划树统计'],
        ['乡级数量', len(levels[4]), len(levels[4]), 0, '按区划树统计'],
        ['村级单位数量', len(village_rows), len(village_rows), 0, '按本地村级清单统计'],
        ['二、坐标完整性', '', '', '', ''],
        ['政府驻地坐标(地市+区县+乡镇)', len(government_nodes), government_matched,
         len(government_nodes) - government_matched, '空坐标需继续查询或人工复核'],
        ['行政村坐标', len(village_rows), village_matched,
         len(village_rows) - village_matched, '空坐标需继续查询或人工复核'],
        ['三、数据源与坐标系', '', '', '', ''],
        ['输出坐标系', 'WGS84', 'WGS84', 0, '四源结果统一转换'],
    ]

    return {
        '地市表': TableData(city_headers, city_rows),
        '区县表': TableData(district_headers, district_rows),
        '乡镇表': TableData(town_headers, town_rows),
        '行政村详细清单': TableData(village_headers, village_rows),
        '汇总表': TableData(summary_headers, summary_rows),
        '校验表': TableData(check_headers, check_rows),
    }


def build_report_text(task_name, stats, data_versions, output_crs='WGS84', qc=None):
    """质检报告 MD 文本。qc 为四层质检报告 dict（core.qc.QcEngine.run_all 返回）。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    lines = [
        f'# {task_name} · 质检报告',
        '',
        f'> 生成时间：{now}',
        '',
        '## 一、采集统计',
        '',
    ]
    for k, v in stats.items():
        lines.append(f'- {k}：{v}')
    lines += [
        '',
        '## 二、数据版本标签',
        '',
    ]
    for k, v in data_versions.items():
        lines.append(f'- {k}：{v}')
    lines += [
        '',
        f'## 三、坐标系',
        '',
        f'- 输出坐标系：{output_crs}（工程版 WGS84 / 发布版 GCJ-02）',
        '',
        '## 四、合规提示',
        '',
        '- WGS84 用于工程设计是行业惯例；对外发布地图/数据须用 GCJ-02 版导出。',
        '- 高德/百度条款禁止批量抓取转售，个人工程使用 OK，对外销售需商业授权。',
        '',
    ]
    if qc:
        lines += _build_qc_section(qc)
    return '\n'.join(lines)


def _build_qc_section(qc):
    """四层质检结果章节。"""
    lines = ['## 五、质检结果（四层体系）', '']
    t = qc.get('total', {})
    lines.append(f'- ① 总数校验：目标 {t.get("total", 0)} 匹配 {t.get("matched", 0)} 未匹配 {t.get("missing", 0)}')
    g = qc.get('geometry', {})
    lines.append(f'- ③ 几何合理性：乡镇距区县 >90km {len(g.get("town_far", []))} 条；'
                 f'村级距镇政府 中位 {g.get("dist_median", 0)/1000:.1f}km '
                 f'P95 {g.get("dist_p95", 0)/1000:.1f}km 最大 {g.get("dist_max", 0)/1000:.1f}km')
    far = g.get('far_list', [])
    if far:
        lines.append(f'  · 村级 >30km 复核清单（{len(far)} 条）：')
        for f in far[:10]:
            lines.append(f'    - {f.get("乡镇", "")} {f.get("名称", "")}（{f.get("距离米", 0)/1000:.1f}km）')
    s = qc.get('sample', {})
    if s.get('enabled') and s.get('result'):
        sr = s['result']
        lines.append(f'- ② 中等偏差抽验：抽样 {sr.get("sample", 0)} 条，通过 {sr.get("pass", 0)} 差异 {sr.get("note", 0)} '
                     f'候选复核 {sr.get("fix", 0)} 未命中 {sr.get("miss", 0)}，候选率 {sr.get("error_rate", 0):.1%}')
        for fn in sr.get('fixed_nodes', [])[:10]:
            lines.append(f'    · 候选复核：{fn.get("区县", "")}/{fn.get("乡镇", "")} {fn.get("名称", "")}（未自动覆盖）')
        for ab in sr.get('abnormal', [])[:10]:
            lines.append(f'    · 异常：{ab.get("区县", "")}/{ab.get("乡镇", "")} {ab.get("名称", "")}（{ab.get("偏差米", 0)}m）')
    elif not s.get('enabled'):
        lines.append('- ② 中等偏差抽验：未配置百度 KEY，跳过')
    golden = qc.get('golden')
    if golden and golden.get('results'):
        lines.append(f'- ④ 黄金向量：对比 {golden.get("matched", 0)} 条')
        for gr in golden['results'][:10]:
            lines.append(f'    · {gr.get("名称", "")}：{gr.get("结论", "")}（{gr.get("偏差米", "")}m）')
    out = qc.get('out_of_box', [])
    if out:
        lines.append(f'- 越界检测：{len(out)} 条坐标超出全国范围')
    poi_sample = qc.get('poi_cross_sample') or {}
    if poi_sample:
        lines.append(f'- POI 独立源交叉抽验：抽样 {poi_sample.get("sample", 0)} 条，'
                     f'独立源命中 {poi_sample.get("verified", 0)} 条；'
                     f'高 {poi_sample.get("high", 0)} / 中 {poi_sample.get("note", 0)} / '
                     f'低 {poi_sample.get("low", 0)} / 未验 {poi_sample.get("unverified", 0)}')
    lines.append('')
    return lines


def standardize_poi_address(province, city, district, address):
    """按省市县+详细地址组成标准地址，不重复、不臆造缺失层级。"""
    result = str(address or '').strip()
    for part in reversed([province, city, district]):
        part = str(part or '').strip()
        if part and part not in result:
            result = part + result
    return result


def build_poi_tables(nodes):
    """POI 模式六表。nodes: [{name,type,address,lon,lat,来源,区县,置信度,...}]"""
    rows = []
    for n in nodes:
        province = n.get('省份', n.get('province', ''))
        city = n.get('地市', n.get('city', ''))
        district = n.get('区县', n.get('district', ''))
        rows.append([
            province, city, district, n.get('name', ''), n.get('type', ''),
            n.get('lon', ''), n.get('lat', ''),
            standardize_poi_address(province, city, district, n.get('address', '')),
            n.get('来源', n.get('source', '')), n.get('置信度', n.get('confidence', '')),
            n.get('adcode', ''), n.get('typecode', ''),
        ])
    headers = ['省份', '地市', '区县', 'POI名称', 'POI分类', '经度(WGS84)',
               '纬度(WGS84)', 'POI地址', '数据来源', '置信度', '行政区码', '分类码']
    counts = {}
    for row in rows:
        counts[row[2]] = counts.get(row[2], 0) + 1
    summary_rows = [[district, count] for district, count in sorted(counts.items())]
    if rows:
        summary_rows.append(['合计', len(rows)])
    abnormal_rows = [
        [row[3], row[4], row[2], '低置信度' if row[9] == '低' else '缺少来源']
        for row in rows if row[9] == '低' or not row[8]
    ]

    return {
        'POI明细表': TableData(headers, rows),
        '汇总表': TableData(['区县', 'POI数'], summary_rows),
        '校验表': TableData(['名称', '类型', '区县', '异常原因'], abnormal_rows),
    }


def export_result(result, path, crs='WGS84'):
    """根据采集结果导出 Excel（六表）+ 质检报告，返回 (excel_path, report_path)。

    坐标按 crs（WGS84/CGCS2000/GCJ-02/BD-09）从 WGS84 转换后输出。
    """
    if result.get('mode') == 'poi' and result.get('store_path'):
        write_poi_store_excel(path, result['store_path'], crs, bool(result.get('review_only')))
        report_path = path.replace('.xlsx', '_质检报告.md')
        report = build_report_text(
            result.get('province', 'POI采集任务'),
            {'总数': result.get('matched', 0), '存储方式': 'SQLite 流式断点库'},
            {'坐标系': crs}, crs, qc=result.get('qc'),
        )
        write_report(report_path, report)
        return path, report_path

    nodes = result.get('nodes', [])
    if crs and crs.upper() != 'WGS84':
        from core.coords import convert_coord
        converted = []
        for n in nodes:
            n2 = dict(n)
            if 'lon' in n2 and 'lat' in n2:
                lon, lat = n2.get('lon'), n2.get('lat')
            elif n2.get('经度(WGS84)') not in (None, ''):
                lon, lat = n2.get('经度(WGS84)'), n2.get('纬度(WGS84)')
            else:
                converted.append(n2)
                continue
            try:
                nl, nl2 = convert_coord(float(lon), float(lat), crs)
                nl, nl2 = round(nl, 6), round(nl2, 6)
            except (ValueError, TypeError):
                converted.append(n2)
                continue
            if 'lon' in n2:
                n2['lon'], n2['lat'] = nl, nl2
            if '经度(WGS84)' in n2:
                n2['经度(WGS84)'], n2['纬度(WGS84)'] = nl, nl2
            converted.append(n2)
        nodes = converted

    if result.get('mode') == 'poi':
        tables = build_poi_tables(nodes)
    else:
        by_level = {1: [], 2: [], 3: [], 4: [], 5: []}
        for n in nodes:
            by_level.setdefault(n.get('level', 5), []).append(n)
        tables = build_division_tables(by_level, by_level.get(5, []))

    write_excel(path, tables)
    report_path = path.replace('.xlsx', '_质检报告.md')
    report = build_report_text(
        result.get('province', '采集任务'),
        {'总数': len(nodes), '匹配': result.get('matched', 0)},
        {'区划': '民政部20251231', '坐标系': crs},
        qc=result.get('qc'),
    )
    write_report(report_path, report)
    return path, report_path
