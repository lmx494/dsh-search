#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯标准库 PDF 文本提取器（不依赖 xref 或第三方库）。

命令行 python pdf_text.py <输入.pdf> <输出.txt>；可导入 extract_pdf_text(path) -> str。
退出码 2 NOT_A_PDF / 3 ENCRYPTED / 4 NO_TEXT / 1 其它；不支持非 FlateDecode 过滤器、
/Differences 自定义编码、无 ToUnicode 的 CID 字体（按 UTF-16BE 猜测）、扫描件（纯图片）。
"""
import bisect, re, sys, zlib

WS = b"\x00\t\n\x0c\r "
DELIM = b"()<>[]{}/%"
AO, AC = 'ao', 'ac'
# 预定义 CMap 名 -> Python 编码：Type0 无 ToUnicode 时按此解码（比 UTF-16BE 猜准确）
PREDEF = {'GBK-EUC-H': 'gb18030', 'GBK-EUC-V': 'gb18030', 'GB-EUC-H': 'gb18030',
          'GBKp-EUC-H': 'gb18030', 'GBK2K-H': 'gb18030', 'B5pc-H': 'big5', 'ETen-B5-H': 'big5',
          'ETenms-B5-H': 'big5', 'KSC-EUC-H': 'euc-kr', '90ms-RKSJ-H': 'shift_jis',
          '90pv-RKSJ-H': 'shift_jis', 'EUC-H': 'euc-jp', 'UniGB-UCS2-H': 'utf-16-be',
          'UniCNS-UCS2-H': 'utf-16-be', 'UniJIS-UCS2-H': 'utf-16-be', 'UniKS-UCS2-H': 'utf-16-be'}

class PdfError(Exception):
    """提取失败，携带进程退出码。"""
    def __init__(self, msg, code=1):
        Exception.__init__(self, msg)
        self.code = code
def warn(ws, msg):
    """告警去重：同一原因只报一次。"""
    if msg not in ws: ws.append(msg)
def lex(d):
    """PDF 词法分析，产出 (kind, value)；kind ∈ str/num/name/op/ao/ac。"""
    n, i = len(d), 0

    def lit(j):
        """(...) 字面串：\\n \\r \\t \\b \\f \\( \\) \\\\ \\ddd 与括号嵌套。"""
        j += 1; depth, out = 1, bytearray()
        esc = {0x6e: 10, 0x72: 13, 0x74: 9, 0x62: 8, 0x66: 12}
        while j < n:
            c = d[j]; j += 1
            if c == 0x5c and j < n:                       # 反斜杠转义
                e = d[j]
                if e in esc: out.append(esc[e]); j += 1
                elif e in b'()\\': out.append(e); j += 1
                elif 0x30 <= e <= 0x37:                   # 最多 3 位八进制
                    v = 0
                    for _ in range(3):
                        if j < n and 0x30 <= d[j] <= 0x37: v = v * 8 + d[j] - 0x30; j += 1
                        else: break
                    out.append(v & 0xFF)
                elif e in b'\r\n':                        # 行续接
                    j += 1
                    if e == 13 and j < n and d[j] == 10: j += 1
                else: out.append(e); j += 1
            elif c == 0x28: depth += 1; out.append(c)
            elif c == 0x29:
                depth -= 1
                if not depth: break
                out.append(c)
            else: out.append(c)
        return bytes(out), j
    def reg(j):
        """从 j 读到下一个空白或分隔符。"""
        while j < n and d[j:j + 1] not in WS and d[j:j + 1] not in DELIM: j += 1
        return j
    while True:
        while i < n:                                      # 跳空白与 % 注释
            c = d[i:i + 1]
            if c in WS: i += 1
            elif c == b'%': k = d.find(b'\n', i); i = n if k < 0 else k + 1
            else: break
        if i >= n: return
        c = d[i:i + 1]
        if c == b'(':
            s, i = lit(i); yield ('str', s)
        elif c == b'<' and d[i + 1:i + 2] != b'<':        # <...> 十六进制串，奇数位补 0
            k = d.find(b'>', i + 1); k = n if k < 0 else k
            h = re.sub(rb'[^0-9A-Fa-f]', b'', d[i + 1:k])
            i = k + 1
            yield ('str', bytes.fromhex((h + b'0' if len(h) % 2 else h).decode('ascii')))
        elif c == b'<':
            i += 2; yield ('do', None)
        elif c == b'>':
            i += 2 if d[i + 1:i + 2] == b'>' else 1; yield ('dc', None)
        elif c in (b'[', b']'):
            i += 1; yield (AO if c == b'[' else AC, None)
        elif c == b'/':
            j = reg(i + 1); yield ('name', d[i + 1:j].decode('latin-1')); i = j
        else:
            j = reg(i)
            if j == i: i += 1; continue
            raw = d[i:j]; i = j
            try: yield ('num', float(raw))
            except ValueError: yield ('op', raw.decode('latin-1'))
def parse_tounicode(data):
    """CMap：beginbfchar/endbfchar + beginbfrange/endbfrange（含数组与单目标形式）。"""
    def units(h):                                         # hex 串 -> 16bit 码元列表
        if len(h) % 4: h = h.ljust((len(h) + 3) // 4 * 4, '0')
        return [int(h[k:k + 4], 16) for k in range(0, len(h), 4)]
    def ustr(us):                                         # 码元 -> Unicode（含代理对）
        return b''.join(u.to_bytes(2, 'big') for u in us).decode('utf-16-be', 'replace')
    txt, cmap = data.decode('latin-1'), {}
    for blk in re.findall(r'beginbfchar(.*?)endbfchar', txt, re.S):
        for s, t in re.findall(r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>', blk):
            cmap[int(s, 16)] = ustr(units(t))
    pat = r'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])'
    for blk in re.findall(r'beginbfrange(.*?)endbfrange', txt, re.S):
        for lo, hi, dst in re.findall(pat, blk):
            a, b = int(lo, 16), min(int(hi, 16), int(lo, 16) + 65535)
            if b < a: continue
            if dst[0] == '[':                             # <lo> <hi> [<d1> <d2> ...]
                for k, item in enumerate(re.findall(r'<([0-9A-Fa-f]*)>', dst)):
                    if a + k <= b: cmap[a + k] = ustr(units(item))
            else:                                         # <lo> <hi> <dst>：dst 末码元递增
                base = units(dst[1:-1])
                for code in (range(a, b + 1) if base else ()):
                    u = list(base); u[-1] = (u[-1] + code - a) & 0xFFFF
                    cmap[code] = ustr(u)
    return cmap

class FontDecoder:
    """优先 ToUnicode CMap；否则 Identity-H 双字节，或 WinAnsi / Latin-1 单字节。"""
    def __init__(self, cmap=None, two=False, winansi=False, codec=None):
        self.cmap, self.two, self.winansi, self.codec = cmap, two, winansi, codec
    def decode(self, bs):
        if self.cmap:
            if not self.two: return ''.join(self.cmap.get(b, '') for b in bs)
            out = [self.cmap.get((bs[k] << 8) | bs[k + 1], '') for k in range(0, len(bs) - 1, 2)]
            if len(bs) % 2: out.append(self.cmap.get(bs[-1], ''))
            return ''.join(out)
        if self.codec: return bs.decode(self.codec, 'replace')
        if self.two: return bs.decode('utf-16-be', 'replace')
        if self.winansi:                                  # cp1252 未定义位按 latin-1 兜底
            out = []
            for b in bs:
                try: out.append(bytes([b]).decode('cp1252'))
                except UnicodeDecodeError: out.append(chr(b))
            return ''.join(out)
        return bs.decode('latin-1')
def scan_objects(data, warnings):
    """正则枚举 `N 0 obj ... endobj`，完全不依赖 xref；num -> (片段, 偏移)。"""
    objs = {}
    for m in re.finditer(rb'(?<![0-9])(\d{1,10})\s+(\d{1,5})\s+obj\b', data):
        end = data.find(b'endobj', m.end())
        objs[int(m.group(1))] = (data[m.end():end if end >= 0 else len(data)], m.start())
    return objs
def obj_dict(seg, objs):
    """返回 (字典片段, 原始流或 None)；流起点跳 CRLF/LF，终点按 /Length 或 endstream。"""
    m = re.search(rb'(?<!end)stream(?=[\r\n])', seg)
    if not m: return seg, None
    d, i = seg[:m.start()], m.end()
    i += 2 if seg[i:i + 2] == b'\r\n' else (1 if seg[i:i + 1] in (b'\r', b'\n') else 0)
    rest = seg[i:]
    m2 = re.search(rb'/Length\s+(\d+)\s+0\s+R', d)
    if m2:                                                # 间接 /Length
        o = objs.get(int(m2.group(1))); m2 = re.search(rb'(\d+)', o[0]) if o else None
    else: m2 = re.search(rb'/Length\s+(\d+)', d)
    ln = int(m2.group(1)) if m2 else None
    if ln is not None and 0 <= ln <= len(rest) and re.match(rb'[ \t\r\n]{0,4}endstream', rest[ln:ln + 24]):
        return d, rest[:ln]
    j = rest.find(b'endstream')                           # 长度不可信 -> 退回 endstream
    return d, re.sub(rb'[\r\n]+$', b'', rest[:j] if j >= 0 else rest)
def _filters(d):
    m = re.search(rb'/Filter\s*(\[[^\]]*\]|/[A-Za-z0-9]+)', d)
    return [x.decode('latin-1') for x in re.findall(rb'/([A-Za-z0-9]+)', m.group(1))] if m else []
def _inflate(data):
    try: return zlib.decompress(data)
    except zlib.error: pass
    for wbits in (-15, 47):                               # 裸 deflate / gzip
        try:
            o = zlib.decompressobj(wbits); return o.decompress(data) + o.flush()
        except zlib.error: continue
    try: return zlib.decompressobj().decompress(data)     # 截断流：返回已解出部分
    except zlib.error: return b''
def decode_stream(raw, filters, warnings, tag=''):
    """只支持无过滤与 FlateDecode，其它过滤器跳过并 warn。"""
    for f in filters:
        if f not in ('FlateDecode', 'Fl'):
            warn(warnings, '跳过%s：不支持的过滤器 /%s' % (tag, f)); return None
        raw = _inflate(raw)
    return raw
def load_objstm(objs, warnings):
    """展开 /Type /ObjStm：解压后按头部 `对象号 偏移` 对切出内嵌对象并并入对象表。"""
    for num in [k for k in objs]:
        seg, off = objs[num]
        d, raw = obj_dict(seg, objs)
        if not re.search(rb'/Type\s*/ObjStm', d): continue
        raw = decode_stream(raw, _filters(d), warnings, '(ObjStm %d)' % num)
        m, m2 = re.search(rb'/N\s+(\d+)', d), re.search(rb'/First\s+(\d+)', d)
        if not raw or not (m and m2):
            warn(warnings, '对象流 %d 解压或头部解析失败，已跳过' % num); continue
        first, cnt = int(m2.group(1)), int(m.group(1))
        nums = [int(x) for x in re.findall(rb'(\d+)', raw[:first])]   # 头部：对象号 偏移 交替
        pairs = list(zip(nums[0::2], nums[1::2]))[:cnt]
        for k, (onum, o) in enumerate(pairs):
            end = first + (pairs[k + 1][1] if k + 1 < len(pairs) else len(raw) - first)
            if onum not in objs and 0 <= o <= len(raw) - first:
                objs[onum] = (raw[first + o:end], off)                # 内嵌对象并入对象表
    return objs
def page_order(objs):
    """按 Catalog -> Pages -> Kids 遍历页树；失败则按对象出现顺序兜底。"""
    order, off = [], lambda k: objs[k][1]
    root = next((n for n in sorted(objs, key=off)
                 if re.search(rb'/Type\s*/Catalog', obj_dict(objs[n][0], objs)[0])), None)
    if root is not None:
        m = re.search(rb'/Pages\s+(\d+)\s+0\s+R', obj_dict(objs[root][0], objs)[0])
        if m: _walk(int(m.group(1)), objs, set(), order, 0)
    if not order:
        order = [n for n in sorted(objs, key=off)
                 if re.search(rb'/Type\s*/Page(?!s)', obj_dict(objs[n][0], objs)[0])]
    return order
def _walk(num, objs, seen, order, depth):
    if num in seen or depth > 64 or num not in objs: return   # seen 防环，depth 防异常深树
    seen.add(num)
    d = obj_dict(objs[num][0], objs)[0]
    if re.search(rb'/Kids', d) and not re.search(rb'/Type\s*/Page(?!s)', d):
        m = re.search(rb'/Kids\s*\[(.*?)\]', d, re.S)
        for k in (re.findall(rb'(\d+)\s+0\s+R', m.group(1)) if m else ()):
            _walk(int(k), objs, seen, order, depth + 1)
        return
    order.append(num)
def _balanced(buf, start):
    i, depth, n = start, 0, len(buf)              # 从 buf[start:start+2]=='<<' 起取配平字典
    while i < n:
        if buf[i:i + 2] == b'<<': depth += 1; i += 2
        elif buf[i:i + 2] == b'>>':
            depth -= 1; i += 2
            if not depth: return buf[start:i]
        else: i += 1
    return buf[start:]
def _resources(num, objs, depth=0):
    """沿 /Parent 继承 /Resources。"""
    if depth > 32 or num not in objs: return b''
    d = obj_dict(objs[num][0], objs)[0]
    m = re.search(rb'/Resources\s+(\d+)\s+0\s+R', d)
    if m and int(m.group(1)) in objs: return obj_dict(objs[int(m.group(1))][0], objs)[0]
    m = re.search(rb'/Resources\s*<<', d)
    if m: return _balanced(d, m.end() - 2)
    m = re.search(rb'/Parent\s+(\d+)\s+0\s+R', d)
    return _resources(int(m.group(1)), objs, depth + 1) if m else b''
def _make_font(num, objs, warnings):
    """字体对象 -> FontDecoder：ToUnicode 优先，其次 Type0 双字节 / WinAnsi / Latin-1。"""
    if num not in objs: return FontDecoder()
    d = obj_dict(objs[num][0], objs)[0]
    sm = re.search(rb'/Subtype\s*/([A-Za-z0-9]+)', d)
    sub = sm.group(1).decode('latin-1') if sm else ''
    cmap, m = None, re.search(rb'/ToUnicode\s+(\d+)\s+0\s+R', d)
    if m and int(m.group(1)) in objs:
        sd, raw = obj_dict(objs[int(m.group(1))][0], objs)
        raw = decode_stream(raw, _filters(sd), warnings, '(ToUnicode)') if raw is not None else None
        cmap = parse_tounicode(raw) if raw else None
    m = re.search(rb'/Encoding\s*/?([A-Za-z0-9+-]+)', d) or re.search(rb'/Encoding\s+(\d+)\s+0\s+R', d)
    if m and m.group(1).isdigit():                        # 间接 /Encoding
        o = objs.get(int(m.group(1)))
        m = re.search(rb'/([A-Za-z0-9+-]+)', obj_dict(o[0], objs)[0]) if o else None
    enc = m.group(1).decode('latin-1') if m else ''
    codec = PREDEF.get(enc) if (sub == 'Type0' and cmap is None) else None
    if cmap is None and sub == 'Type0':
        warn(warnings, '字体 %d 是 Type0 但无可用 ToUnicode，按 %s 猜测'
             % (num, '预定义 CMap' if codec else 'UTF-16BE'))
    return FontDecoder(cmap, sub == 'Type0', enc == 'WinAnsiEncoding', codec)
def _fonts(res, objs, warnings):
    """页面资源字典 -> {资源名: FontDecoder}。"""
    m = re.search(rb'/Font\s+(\d+)\s+0\s+R', res)
    if m and int(m.group(1)) in objs:
        body = obj_dict(objs[int(m.group(1))][0], objs)[0]
    else:
        m = re.search(rb'/Font\s*<<', res); body = _balanced(res, m.end() - 2) if m else b''
    return {name.decode('latin-1'): _make_font(int(num), objs, warnings)
            for name, num in re.findall(rb'/([^\s/\[\]<>()]+)\s+(\d+)\s+0\s+R', body)}
def _contents(d, objs, warnings):
    """页面 /Contents（单个或数组）-> 解码后的流字节列表。"""
    m = re.search(rb'/Contents\s*\[(.*?)\]', d, re.S)
    if m:
        nums = [int(x) for x in re.findall(rb'(\d+)\s+0\s+R', m.group(1))]
    else:
        m = re.search(rb'/Contents\s+(\d+)\s+0\s+R', d); nums = [int(m.group(1))] if m else []
    out = []
    for k in nums:
        if k not in objs:
            warn(warnings, '内容流对象 %d 不存在，已跳过' % k); continue
        sd, raw = obj_dict(objs[k][0], objs)
        if raw is None: continue
        raw = decode_stream(raw, _filters(sd), warnings, '(内容流 %d)' % k)
        if raw: out.append(raw)
    return out
def parse_content(data, fonts, warnings):
    """还原行：按基线 y 分桶（容差 0.3×字号），桶内按 x 排序拼接，片段间距超 0.3×字号补空格，
    TJ 数组里 ≤ -100 的负调整量也当空格；行按基线自上而下输出。逐字形绘制（每字形一个 BT/Tm/TJ）
    且绘制顺序与视觉顺序无关的 PDF 很常见，故不能按 y 变化即时换行。"""
    rows, keys, a, stack = {}, [], [], []
    st = {'x': 0.0, 'y': 0.0, 'pen': 0.0, 'fs': 12.0, 'lead': 0.0, 'font': None, 'key': None}

    def bucket(y, tol):                                     # 找到/新建与 y 同基线的行桶
        k = bisect.bisect_left(keys, y)
        for j in (k - 1, k):
            if 0 <= j < len(keys) and abs(keys[j] - y) <= tol: return keys[j]
        keys.insert(k, y); rows[y] = []
        return y

    def show(bs):
        f = st['font'] or FontDecoder()
        try: s = f.decode(bs)
        except Exception: s = bs.decode('latin-1', 'replace')   # 单串异常不打断整页
        if not s: return
        w = (len(bs) // 2 if f.two else len(bs)) * st['fs'] * (1.0 if f.two else 0.5)
        k = bucket(st['y'], max(0.3 * st['fs'], 0.5))       # 宽度只用于判断片段间空档
        rows[k].append((st['pen'], w, st['fs'], s))
        st['pen'] += w; st['key'] = k

    def move(nx, ny):
        st['x'], st['y'], st['pen'] = nx, ny, nx

    def space():                                            # TJ 大负间距补空格
        k = st['key']
        if k is not None and rows[k] and not rows[k][-1][3].endswith(' '):
            f = rows[k][-1]; rows[k][-1] = (f[0], f[1], f[2], f[3] + ' ')

    for kind, v in lex(data):
        if kind == AO:
            a.append([]); stack.append(a); a = a[-1]; continue
        if kind == AC:
            if stack: a = stack.pop()
            continue
        if kind in ('str', 'num', 'name'):
            a.append(v); continue
        if kind in ('do', 'dc'): continue                   # 内联字典不入栈，忽略即可
        try:
            if v == 'BT': st['x'] = st['y'] = st['pen'] = 0.0
            elif v == 'Tf' and len(a) >= 2 and isinstance(a[-1], float):
                st['font'] = (fonts.get(a[-2]) if isinstance(a[-2], str) else None) or FontDecoder()
                st['fs'] = a[-1] or 12.0
            elif v == 'TL' and a and isinstance(a[-1], float): st['lead'] = a[-1]
            elif v in ('Td', 'TD') and len(a) >= 2 and isinstance(a[-1], float):
                if v == 'TD': st['lead'] = -a[-1]
                move(st['x'] + a[-2], st['y'] + a[-1])
            elif v == 'Tm' and len(a) >= 6: move(a[-2], a[-1])
            elif v == 'T*': st['y'] -= st['lead']; st['pen'] = st['x']   # 下一行
            elif v == 'Tj' and a and isinstance(a[-1], bytes): show(a[-1])
            elif v == 'TJ' and a and isinstance(a[-1], list):
                for el in a[-1]:
                    if isinstance(el, bytes): show(el)
                    elif isinstance(el, float) and el <= -100: space()
            elif v in ("'", '"'):                           # ' = T* + Tj，\" 再加字距参数
                st['y'] -= st['lead']; st['pen'] = st['x']
                if a and isinstance(a[-1], bytes): show(a[-1])
        except Exception as e:
            warn(warnings, '操作符 %s 处理失败: %s' % (v, e))
        del a[:]
    out = []
    for y in sorted(rows, reverse=True):
        row = sorted(rows[y])                               # 桶内按 x 排序（绘制顺序常≠视觉顺序）
        if not row: continue
        parts = [row[0][3]]
        for (px, pw, pf, _), (nx, _nw, _nf, nt) in zip(row, row[1:]):
            if nx - (px + pw) > 0.3 * pf: parts.append(' ')  # 片段间明显空档 -> 空格
            parts.append(nt)
        s = re.sub(r'[ \t]+', ' ', ''.join(parts)).strip()
        if s: out.append(s)
    return '\n'.join(out)
def extract_bytes(data):
    """核心入口：返回整篇文本；失败抛 PdfError。"""
    if not data.lstrip()[:5].startswith(b'%PDF-'): raise PdfError('NOT_A_PDF: 缺少 %PDF- 文件头', 2)
    if re.search(rb'/Encrypt\s', data): raise PdfError('ENCRYPTED: 文档已加密，本工具不支持解密', 3)
    warnings = []
    objs = load_objstm(scan_objects(data, warnings), warnings)
    if not objs: raise PdfError('NOT_A_PDF: 未找到任何 `N 0 obj` 对象', 2)
    pages, chunks, got = page_order(objs), [], False
    for i, pnum in enumerate(pages, 1):
        d = obj_dict(objs[pnum][0], objs)[0]
        fonts = _fonts(_resources(pnum, objs), objs, warnings)
        txt = '\n'.join(t for t in (parse_content(c, fonts, warnings)
                                    for c in _contents(d, objs, warnings)) if t)
        chunks.append('[第 %d 页]' % i)                    # 页标记，N 从 1 开始
        if txt: got = True; chunks.append(txt)
    for w in warnings: sys.stderr.write('warn: %s\n' % w)  # 警告不影响成功退出
    if not got: raise PdfError('NO_TEXT: 未提取到任何文本（可能是扫描件/纯图片 PDF）', 4)
    return '\n'.join(chunks)
def extract_pdf_text(path):
    """读取 PDF 文件，返回整篇文本（行以 \\n 分隔）。"""
    with open(path, 'rb') as f: return extract_bytes(f.read())
def main(argv):
    if len(argv) != 3:
        sys.stderr.write('USAGE: python pdf_text.py <输入.pdf> <输出.txt>\n'); return 2
    try:
        text = extract_pdf_text(argv[1])
    except PdfError as e:
        sys.stderr.write('%s\n' % e); return e.code
    except OSError as e:
        sys.stderr.write('ERROR: 无法读取输入文件: %s\n' % e); return 1
    except Exception as e:                                  # 兜底：绝不向调用方抛栈
        sys.stderr.write('ERROR: %s: %s\n' % (type(e).__name__, e)); return 1
    try:
        with open(argv[2], 'w', encoding='utf-8', newline='\n') as f:
            f.write(text.rstrip('\n') + '\n')
    except OSError as e:
        sys.stderr.write('ERROR: 无法写入输出文件: %s\n' % e); return 1
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv))
