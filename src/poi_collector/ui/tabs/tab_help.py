# -*- coding: utf-8 -*-
"""使用帮助：说明书式正文 + 公开问题反馈入口。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel, QTextBrowser


class TabHelp(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(10)
        self.browser = QTextBrowser()
        self.browser.setOpenExternalLinks(True)
        self.browser.setHtml(self._html())
        self._format_blocks()
        layout.addWidget(self.browser, 1)
        layout.addWidget(self._contact_card())

    def _format_blocks(self):
        headings = {
            '通信工程POI数据采集器（POICollector）V2.0',
            '软件简介', '功能特点', 'KEY申请', '操作说明', '注意事项', '问题反馈',
            '区划查询', '分类搜索', '周边搜索', '坐标转换', '地址互转', '基本设置',
        }
        block = self.browser.document().begin()
        while block.isValid():
            text = block.text().strip()
            cursor = QTextCursor(block)
            fmt = block.blockFormat()
            fmt.setLineHeight(125.0, QTextBlockFormat.ProportionalHeight.value)
            in_table = cursor.currentTable() is not None
            is_heading = text in headings
            if text and not is_heading and not in_table:
                if not block.textList():
                    fmt.setTextIndent(28.0)
            else:
                fmt.setTextIndent(0.0)
            cursor.setBlockFormat(fmt)
            block = block.next()

    def _contact_card(self):
        card = QFrame()
        card.setProperty('card', True)
        row = QHBoxLayout(card)
        row.setContentsMargins(18, 10, 14, 10)
        row.setSpacing(14)
        row.addStretch(1)
        self.contact_info = QLabel(
            '<b style="color:#1769aa">问题反馈</b><br>'
            '请通过 <a href="https://github.com/xuworker98/POICollector/issues">GitHub Issues</a> '
            '提交脱敏后的复现步骤与样例。'
        )
        self.contact_info.setOpenExternalLinks(True)
        self.contact_info.setTextFormat(Qt.RichText)
        row.addWidget(self.contact_info, 0, Qt.AlignRight | Qt.AlignVCenter)
        return card

    @staticmethod
    def _html():
        return """
        <html><head><style>
        body { font-family:'Microsoft YaHei UI'; font-size:14px; color:#2d3436; background:#fff; margin:16px 22px; }
        h1 { font-size:20px; color:#1f2937; margin:0 0 6px 0; }
        h2 { font-size:16px; color:#1769aa; background:#eef6ff; margin:18px 0 8px 0; padding:7px 10px; }
        h3 { font-size:14px; color:#1f4f7a; margin:14px 0 6px 0; padding-left:8px; border-left:3px solid #2f80ed; }
        p { margin:7px 0 11px 0; line-height:125%; }
        .lead { color:#636e72; }
        ol,ul { margin:8px 0 14px 28px; padding-left:0; }
        li { margin:0 0 9px 0; line-height:125%; }
        table { border-collapse:collapse; margin:8px 0 14px 0; width:100%; }
        th,td { border:1px solid #dcdde1; padding:7px 10px; text-align:left; }
        th { background:#305496; color:#fff; font-weight:bold; }
        tr:nth-child(even) { background:#f7f9fb; }
        a { color:#0984e3; text-decoration:none; }
        </style></head><body>
        <h1>通信工程POI数据采集器（POICollector）V2.0</h1>
        <p class="lead">空间查询工作台 · 多图源底图 · 自动换源 · 交叉验真 · 流式导出</p>
        <h2>软件简介</h2>
        <p>通信工程POI数据采集器面向通信规划、无线优化和网络维护场景，将行政区划、分类POI和中心点周边查询集中在地图工作台内。查询结果直接形成地图点图层，坐标统一归一为WGS84，并可导出规范Excel和质检结果。</p>
        <p>软件将查询服务与地图底图分开管理：查询KEY负责检索POI和地址，底图负责地图显示。查询服务异常时可按优先级换源，底图异常时可切换ArcGIS、OpenStreetMap、天地图或用户自定义XYZ/TMS地址。</p>

        <h2>功能特点</h2>
        <table width="100%" cellspacing="0" cellpadding="0"><tr><th width="20%">功能</th><th width="80%">说明</th></tr>
        <tr><td>区划采集</td><td>采集省、市、区县、乡镇、行政村及驻地信息，并按层级工作表规范导出。</td></tr>
        <tr><td>分类搜索</td><td>按省、市、区县和一个或多个POI分类检索，不要求额外输入关键字。</td></tr>
        <tr><td>周边搜索</td><td>支持地图选点、坐标输入和框选范围，按中心点、半径及分类检索附近POI。</td></tr>
        <tr><td>坐标处理</td><td>支持WGS84、GCJ-02、BD-09等坐标系转换，以及地址与经纬度批量互转。</td></tr>
        <tr><td>质量校验</td><td>校验坐标范围、行政区归属和数据完整性，保留数据来源、置信度及待复核标识。</td></tr>
        <tr><td>批量处理</td><td>后台分页、可取消任务、SQLite流式暂存和有限点位绘制，降低大数据运行时的界面卡顿。</td></tr></table>

        <h2>KEY申请</h2>
        <p>本软件使用的是服务端查询接口。高德请选择“Web服务”，百度请选择“服务端”，腾讯请选择“WebService”，天地图需在控制台开通搜索或地理编码权限。纯Qt地图不使用浏览器端JavaScript KEY。</p>
        <table width="100%" cellspacing="0" cellpadding="0"><tr><th width="14%">平台</th><th width="20%">查询类型</th><th width="22%">底图方式</th><th width="18%">申请入口</th><th width="26%">说明</th></tr>
        <tr><td>天地图</td><td>服务端KEY</td><td>地图服务KEY</td><td><a href="https://cloudcenter.tianditu.gov.cn/center/development/myApp">进入控制台</a></td><td>建议按用途分别创建；能否兼用以应用类型、已开通权限和实测结果为准。</td></tr>
        <tr><td>高德</td><td>Web服务Key</td><td>本程序不直接调用其JS底图</td><td><a href="https://console.amap.com/dev/key/app">进入控制台</a></td><td>用于POI、行政区和地理编码；请配置调用安全策略。</td></tr>
        <tr><td>百度</td><td>服务端AK</td><td>本程序不直接调用其JS底图</td><td><a href="https://lbsyun.baidu.com/apiconsole/key">进入控制台</a></td><td>创建应用时选择“服务端”，并启用所需Web服务。</td></tr>
        <tr><td>腾讯</td><td>WebService Key</td><td>本程序不直接调用其JS底图</td><td><a href="https://lbs.qq.com/dev/console/application/mine">进入控制台</a></td><td>用于地点搜索和地址解析；按控制台要求设置配额与白名单。</td></tr>
        <tr><td>XYZ图源</td><td>无需查询KEY</td><td>XYZ/TMS瓦片地址</td><td>在“基本设置”填写</td><td>可使用免KEY公开底图或带令牌的合法图源，只负责地图显示。</td></tr></table>
        <p>KEY保存后以加密形式写入本机配置。公开发布软件时不要内置个人KEY；若密钥已经泄露，请到对应平台删除并重新申请。各平台申请规则和免费配额可能调整，请以控制台最新说明为准。</p>

        <h2>操作说明</h2>
        <h3>区划查询</h3>
        <table width="100%" cellspacing="0" cellpadding="0"><tr><th width="22%">参数</th><th width="28%">示例</th><th width="50%">说明</th></tr>
        <tr><td>目标省份</td><td>广西壮族自治区</td><td>选择需要建立区划树的省级区域。</td></tr>
        <tr><td>目标地市</td><td>南宁市</td><td>选择地市；需要全省时可选择全部地市。</td></tr>
        <tr><td>目标区县</td><td>青秀区</td><td>可选单一区县或全部区县。</td></tr>
        <tr><td>采集级别</td><td>地市、区县、乡镇</td><td>按实际需求勾选；村级数据量较大，建议使用已核验离线数据。</td></tr>
        <tr><td>数据来源 / 坐标系</td><td>自动优选 / WGS84</td><td>自动优选按设置顺序切换查询源，内部坐标统一校验。</td></tr></table>
        <p>设置完成后点击“开始查询”。右侧地图呈现已取得坐标的驻地点；查询完成后点击“导出结果”，Excel按地市、区县、乡镇、行政村等工作表规范输出。</p>
        <h3>分类搜索</h3>
        <table width="100%" cellspacing="0" cellpadding="0"><tr><th width="22%">参数</th><th width="28%">示例</th><th width="50%">说明</th></tr>
        <tr><td>目标区域</td><td>广西 / 南宁 / 全部区县</td><td>软件逐区县查询，避免同名地点跨区域误入。</td></tr>
        <tr><td>POI分类</td><td>公园、省级景点、国家级景点</td><td>点击“选择分类”可多选；不需要再输入关键字。</td></tr>
        <tr><td>数据来源</td><td>自动优选</td><td>首选源无结果、不可用或限流时，按优先级尝试其他查询源。</td></tr>
        <tr><td>输出坐标系</td><td>WGS84</td><td>用于导出；地图内部始终使用标准经纬度。</td></tr></table>
        <p>点击“开始查询”后，进度按“区县 × 分类”任务推进。检索完成的结果会立即在地图上形成点图层并开放导出；联网交叉质检在后台继续，不再阻塞地图和Excel导出。</p>
        <h3>周边搜索</h3>
        <table width="100%" cellspacing="0" cellpadding="0"><tr><th width="22%">参数</th><th width="28%">示例</th><th width="50%">说明</th></tr>
        <tr><td>目标区域</td><td>广西 / 南宁 / 青秀区</td><td>用于限制结果归属；可按实际范围选择。</td></tr>
        <tr><td>中心点</td><td>地图选点，或108.366 / 22.817</td><td>地图选点、定位中心和框选范围都会自动回填坐标并反查地址。</td></tr>
        <tr><td>搜索半径</td><td>3000米</td><td>允许100—50000米；框选后自动估算覆盖半径。</td></tr>
        <tr><td>POI分类</td><td>通信基站或公园</td><td>可多选；分类文字较多时左侧参数区出现滚动条。</td></tr></table>
        <p>点击“开始查询”，系统只保留缓冲区半径内且符合行政区限制的结果。地图右侧竖排工具依次用于放大、缩小、定位中心、框选范围、地图切换和显示全部。</p>
        <h3>坐标转换</h3>
        <p>点击“浏览”选择XLSX、XLS或CSV文件后，程序会自动读取表头和数据，无需再次点击导入。选择经度列、纬度列、源坐标系和目标坐标系，再点击“开始转换”；需要中止时点击“取消”，完成后可点击“打开文件夹”。</p>
        <h3>地址互转</h3>
        <p>在批量地址转坐标或坐标转地址页面选择数据文件，检查地址列或经纬度列，选择查询平台后开始转换。建议先用少量记录核对城市、标准地址和坐标，再执行大批量任务。</p>
        <h3>基本设置</h3>
        <p>填写各平台查询KEY并逐项测试，设置查询源优先级；再选择内置底图或填写自定义XYZ/TMS地址。查询源与底图彼此独立，其中一项不可用不会阻止另一项切换。</p>

        <h2>注意事项</h2>
        <ul>
          <li><b>网络访问：</b>境外VPN出口可能被国内地图平台拦截，出现HTTP 418、超时或域名连接失败时，可关闭境外VPN后重试或切换查询源。</li>
          <li><b>调用配额：</b>并发线程过多会触发限流。请遵守各平台许可和配额，先进行小批量测试，再逐步提高并发。</li>
          <li><b>底图授权：</b>ArcGIS、OpenStreetMap和自定义XYZ/TMS仅提供地图背景，不提供POI查询；请遵守图源的使用条款和署名要求。</li>
          <li><b>坐标核对：</b>内部结果统一保存为WGS84。GCJ-02或BD-09数据必须正确选择源坐标系，重复纠偏会造成位置偏移。</li>
          <li><b>结果质检：</b>程序执行格式、坐标和行政区归属校验，但第三方数据仍可能缺失或更新滞后；低置信度和待复核记录应人工抽查。</li>
          <li><b>大批数据：</b>百万行任务建议使用本地固态硬盘，关闭正在占用的结果文件，减少不必要字段，并避免一次性在地图上绘制全部点位。</li>
          <li><b>异常反馈：</b>请保留软件版本、查询区域、模式、分类、状态栏信息、运行日志及少量脱敏样例，便于复现问题。</li>
        </ul>
        <h2>问题反馈</h2>
        <p>如需反馈问题或提出功能建议，请通过GitHub Issues提交软件版本、操作系统、查询区域、查询模式、分类、状态栏提示，以及可复现问题的少量脱敏样例数据。请勿提交API KEY、个人地址或未经授权的数据。</p>
        </body></html>
        """
