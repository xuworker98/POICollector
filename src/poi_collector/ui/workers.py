# -*- coding: utf-8 -*-
"""QThread 后台线程（UI 不卡死的关键）"""
from PySide6.QtCore import QThread, Signal


class TileTestWorker(QThread):
    """Fetch one representative tile without blocking the GUI thread."""
    result = Signal(bool, str)

    def __init__(self, source):
        super().__init__()
        self.source = dict(source)

    def run(self):
        import requests
        try:
            url = self.source['url']
            substitutions = {'{z}': '0', '{x}': '0', '{y}': '0', '{s}': '0'}
            for token, value in substitutions.items():
                url = url.replace(token, value)
            response = requests.get(
                url, timeout=12,
                headers={'User-Agent': 'POICollector/2.0 (desktop basemap test)'},
            )
            response.raise_for_status()
            content_type = response.headers.get('content-type', '').lower()
            data = response.content
            image_magic = data.startswith((b'\x89PNG', b'\xff\xd8\xff', b'RIFF'))
            if 'image/' not in content_type and not image_magic:
                raise ValueError(f'返回内容不是图片：{content_type or "未知类型"}')
            self.result.emit(True, f'可用 · HTTP {response.status_code} · {len(data) / 1024:.1f} KB')
        except Exception as exc:
            response = getattr(exc, 'response', None)
            code = getattr(response, 'status_code', None)
            detail = f'HTTP {code}' if code else type(exc).__name__
            self.result.emit(False, f'不可用 · {detail}')


class MapKeyTestWorker(QThread):
    """Connectivity/permission smoke test for browser-side map credentials."""
    result = Signal(str, bool, str)

    def __init__(self, provider, key, security_code=''):
        super().__init__()
        self.provider, self.key, self.security_code = provider, key, security_code

    def run(self):
        import requests
        urls = {
            'tianditu': (
                'https://t0.tianditu.gov.cn/vec_w/wmts?SERVICE=WMTS&REQUEST=GetTile'
                '&VERSION=1.0.0&LAYER=vec&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles'
                '&TILEMATRIX=1&TILEROW=0&TILECOL=0&tk={key}'
            ),
            'amap_js': 'https://webapi.amap.com/maps?v=2.0&key={key}',
            'baidu_browser': 'https://api.map.baidu.com/api?v=3.0&ak={key}',
            'tencent_js': 'https://map.qq.com/api/gljs?v=1&key={key}',
        }
        try:
            response = requests.get(
                urls[self.provider].format(key=self.key), timeout=12,
                headers={'User-Agent': 'POICollector/2.0 (map-key test)'},
            )
            response.raise_for_status()
            body = response.content[:4096].lower()
            if any(flag in body for flag in (b'invalid key', b'key error', b'ak error')):
                raise ValueError('服务返回KEY错误')
            if self.provider == 'tianditu' and not response.headers.get('content-type', '').lower().startswith('image/'):
                raise ValueError('天地图没有返回瓦片图片，请检查地图服务权限')
            note = '瓦片有效' if self.provider == 'tianditu' else '接口可达，最终权限将在地图中验证'
            self.result.emit(self.provider, True, note)
        except Exception as exc:
            response = getattr(exc, 'response', None)
            code = getattr(response, 'status_code', None)
            detail = f'HTTP {code}' if code else type(exc).__name__
            self.result.emit(self.provider, False, detail)


class KeyTestWorker(QThread):
    """测试单个 KEY 有效性（后台发一次最小请求）"""
    result = Signal(str, bool, str)  # (source_name, ok, message)

    def __init__(self, source_name, source):
        super().__init__()
        self.source_name = source_name
        self.source = source

    def run(self):
        from sources.base import QuotaExceeded, HttpRequestError, SourceUnavailable
        try:
            if self.source_name == 'tianditu':
                r = self.source.geocode('北京市人民政府', city='北京市')
            else:
                r = self.source.geocode('北京')
            if r:
                self.result.emit(self.source_name, True, f'有效（坐标 {r[0]},{r[1]}）')
            else:
                self.result.emit(self.source_name, False, '无效（无返回或权限异常）')
        except QuotaExceeded as e:
            self.result.emit(self.source_name, True, f'有效但配额已尽：{e}')
        except HttpRequestError as e:
            hint = '天地图 CloudWAF/网络出口拦截' if e.status_code == 418 else str(e)
            self.result.emit(self.source_name, False, f'[网络] {hint}；KEY 本身尚未判定')
        except SourceUnavailable as e:
            self.result.emit(self.source_name, False, f'[服务] {e}')
        except Exception as e:
            self.result.emit(self.source_name, False, f'异常：{e}')


class CollectWorker(QThread):
    """后台采集线程（区划模式 / POI 模式），信号槽更新 UI。"""
    progress = Signal(int, int, str)   # 完成数 / 总数 / 阶段文字
    quota = Signal(dict)               # 四源配额快照
    log = Signal(str)                  # 日志行（纯文本，level 由前缀区分）
    status = Signal(str, str)          # (状态文字, 灯色 idle/running/retry/error)
    finished_ok = Signal(dict)         # 完成结果统计

    def __init__(self, engine):
        super().__init__()
        self.engine = engine            # 采集引擎（含 run(progress_cb, ...) 方法）
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        try:
            result = self.engine.run(
                progress_cb=lambda done, total, msg: self.progress.emit(done, total, msg),
                quota_cb=lambda snap: self.quota.emit(snap),
                log_cb=lambda line: self.log.emit(line),
                status_cb=lambda text, light: self.status.emit(text, light),
                is_stopped=lambda: self._stopped,
            )
            if not self._stopped:
                self.finished_ok.emit(result)
        except Exception as e:
            self.log.emit(f'[错误] {e}')
            self.status.emit(f'异常：{e}', 'error')
