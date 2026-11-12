# -*- coding: utf-8 -*-
"""pdf_text.py 自测脚本（纯标准库，可独立运行）。

运行: python tools\\tests\\test_pdf_text.py
现场生成 5 个 PDF 样例 + 1 个非 PDF 文件，验证提取结果与退出码。
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
import zlib

sys.dont_write_bytecode = True   # 不在 tools/ 下留 __pycache__
try:                             # 输出编码兜底：重定向时用 UTF-8，控制台装不下的字符用 ? 代替
    if sys.stdout.isatty():
        sys.stdout.reconfigure(errors='replace'); sys.stderr.reconfigure(errors='replace')
    else:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(os.path.dirname(HERE), 'pdf_text.py')
ENV = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')

# 真实 PDF 验收用例：p1 逐字形绘制+坏 xref、p2 用 ObjStm 对象流、p3 回归基准
# 路径来源：环境变量 LOCATOR_TEST_PDFS（; 分隔）→ tests/real_pdfs.txt → 都没有就跳过整段
ROOT = os.path.dirname(os.path.dirname(HERE))


def _load_real_pdfs():
    env = os.environ.get('LOCATOR_TEST_PDFS', '').strip()
    if env:
        items = [x.strip() for x in env.split(';') if x.strip()]
    else:
        f = os.path.join(ROOT, 'tests', 'real_pdfs.txt')
        if not os.path.exists(f):
            return []
        with open(f, encoding='utf-8') as fh:
            items = [x.strip() for x in fh if x.strip() and not x.startswith('#')]
    return [('p%d' % (i + 1), x) for i, x in enumerate(items)]


REAL_PDFS = _load_real_pdfs()
PAGE_MARK = re.compile(r'^\[第 \d+ 页\]$')

RESULTS = []


def check(name, cond, extra=''):
    RESULTS.append((name, bool(cond)))
    print('%s  %s%s' % ('PASS' if cond else 'FAIL', name,
                        ('   <- %s' % extra) if (extra and not cond) else ''))


def load_tool():
    spec = importlib.util.spec_from_file_location('pdf_text_under_test', TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------- PDF 构造工具
def stream_obj(dic, data, flate=False, crlf=False):
    """dic 形如 b'<<'；返回 完整流对象体（含 dict / Length / stream...endstream）。"""
    if flate:
        data = zlib.compress(data)
        dic = dic + b' /Filter /FlateDecode'
    eol = b'\r\n' if crlf else b'\n'
    return dic + b' /Length %d >>' % len(data) + eol + b'stream' + eol + data + eol + b'endstream'


def build_pdf(objs, broken_xref=False, extra_trailer=b''):
    """objs: {编号: 对象体 bytes}。broken_xref=True 时刻意写坏 xref 表。"""
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b'%d 0 obj\n' % num + objs[num] + b'\nendobj\n'
    xref_off = len(out)
    size = max(objs) + 1
    if broken_xref:
        out += b'xref\n' + b'this line is garbage\n' + b'0 0\n'
        start = 0
    else:
        out += b'xref\n0 %d\n0000000000 65535 f \n' % size
        for i in range(1, size):
            out += b'%010d 00000 n \n' % offsets.get(i, 0)
        start = xref_off
    out += b'trailer\n<< /Size %d /Root 1 0 R' % size + extra_trailer + b' >>\n'
    out += b'startxref\n%d\n%%%%EOF\n' % start
    return bytes(out)


def simple_font_res(font_num=5):
    return (b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
            b'/Resources << /Font << /F1 %d 0 R >> >> ' % font_num)


# ------------------------------------------------------------------- 样例 (a)
def sample_a():
    """未压缩内容流 + WinAnsi 单字节 + 数字标号 + TJ/T*/' 操作符 + 八进制转义。"""
    content = (rb'BT /F1 14 Tf 72 740 Td (Invoice 1.2.3 Caf\351) Tj ET'
               b'\nBT /F1 12 Tf 72 700 Td [(Hello) -300 (World)] TJ ET'
               b"\nBT /F1 12 Tf 14 TL 72 660 Td (Line One) Tj T* (Line Two) ' ET")
    objs = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        2: b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        3: simple_font_res() + b'/Contents 4 0 R >>',
        4: stream_obj(b'<<', content),
        5: b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
    }
    return build_pdf(objs, broken_xref=True)   # 顺便验证不依赖 xref


# ------------------------------------------------------------------- 样例 (b)
def sample_b():
    """FlateDecode 压缩流，两页；第一页 stream 后用 CRLF，第二页用 LF。"""
    p1 = b'BT /F1 12 Tf 72 720 Td (Compressed Page One) Tj ET'
    p2 = b'BT /F1 12 Tf 72 720 Td (Second 7.8.9) Tj ET'
    objs = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        2: b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
        3: simple_font_res(7) + b'/Contents 5 0 R >>',
        4: simple_font_res(7) + b'/Contents 6 0 R >>',
        5: stream_obj(b'<<', p1, flate=True, crlf=True),
        6: stream_obj(b'<<', p2, flate=True),
        7: b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
    }
    return build_pdf(objs)


# ------------------------------------------------------------------- 样例 (c)
def sample_c():
    """Identity-H 双字节 + ToUnicode CMap（bfchar / bfrange 数组 / bfrange 单目标）。"""
    cmap = (b'/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n'
            b'/CMapName /Test-H def\n/CMapType 2 def\n'
            b'1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n'
            b'2 beginbfchar\n<0001> <4E2D>\n<0002> <6587>\nendbfchar\n'
            b'1 beginbfrange\n<0003> <0004> [<56FD> <5B57>]\nendbfrange\n'
            b'1 beginbfrange\n<0005> <0006> <4E00>\nendbfrange\n'
            b'endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n')
    content = (b'BT /F1 24 Tf 72 700 Td <0001000200030004> Tj ET'
               b'\nBT /F1 16 Tf 72 660 Td <00050006> Tj ET')
    objs = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        2: b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        3: (b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
            b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>'),
        4: stream_obj(b'<<', content),
        5: (b'<< /Type /Font /Subtype /Type0 /BaseFont /TestCJK /Encoding /Identity-H '
            b'/DescendantFonts [6 0 R] /ToUnicode 7 0 R >>'),
        6: (b'<< /Type /Font /Subtype /CIDFontType0 /BaseFont /TestCJK '
            b'/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> >>'),
        7: stream_obj(b'<<', cmap, flate=True),
    }
    return build_pdf(objs)


# ------------------------------------------------------------------- 样例 (d)(e)
def sample_encrypted():
    objs = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        2: b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        3: simple_font_res() + b'/Contents 4 0 R >>',
        4: stream_obj(b'<<', b'BT /F1 12 Tf 10 10 Td (secret) Tj ET'),
        5: b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
        9: b'<< /Filter /Standard /V 2 /R 3 /O (x) /U (y) /P -1 >>',
    }
    return build_pdf(objs, extra_trailer=b' /Encrypt 9 0 R')


def sample_no_text():
    """页面没有 /Contents —— 等价于扫描件/空页。"""
    objs = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        2: b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        3: b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>',
    }
    return build_pdf(objs)


# ---------------------------------------------------------------------- 主流程
def run_cli(*args):
    p = subprocess.run([sys.executable, TOOL] + list(args), capture_output=True,
                       encoding='utf-8', errors='replace', env=ENV)
    return p.returncode, p.stdout, p.stderr


def run_real(tag, path, tmp):
    """跑一个真实 PDF，返回 (rc, 秒, 全文, 行列表, 汉字数, stderr)。"""
    out = os.path.join(tmp, tag + '.txt')
    t0 = time.time()
    p = subprocess.run([sys.executable, TOOL, path, out], capture_output=True,
                       encoding='utf-8', errors='replace', env=ENV)
    dt = time.time() - t0
    body = open(out, encoding='utf-8').read() if os.path.exists(out) else ''
    lines = [x for x in body.splitlines() if x.strip()]
    return p.returncode, dt, body, lines, len(re.findall(r'[\u4e00-\u9fff]', body)), p.stderr


def check_real_pdfs(tmp):
    """真实文件验收：行重建、ObjStm、中文正确性、性能。"""
    stats = {}
    for tag, path in REAL_PDFS:
        if not os.path.exists(path):
            check('%s. 跳过缺失的真实 PDF' % tag, True, path)
            continue
        rc, dt, body, lines, han, err = run_real(tag, path, tmp)
        plain = [x for x in lines if not PAGE_MARK.match(x)]
        stats[tag] = (rc, dt, body, plain, han)
        check('%s. exit 0' % tag, rc == 0, err.strip()[:150])
        check('%s. 3 秒内完成' % tag, dt < 3.0, '%.2fs' % dt)
        check('%s. 无乱码替换符' % tag, '\ufffd' not in body)
        if not plain:
            continue
        text = ''.join(plain)
        if tag == 'p1':
            short = sum(1 for x in plain if len(x) <= 2)
            check('p1. 不再是每字符一行', len(plain) > 20 and short / len(plain) < 0.3,
                  '%d 行长 ≤2 字符 / 共 %d 行' % (short, len(plain)))
            check('p1. 中文标题正确', '中国矿业大学实验室安全准入管理系统' in text)
            check('p1. 页内空格重建', 'Instructions' in text and 'Version 3.0' in text)
            check('p1. 汉字数 ≥ 800', han >= 800, str(han))
        elif tag == 'p2':
            check('p2. ObjStm 对象流已解析出正文', han >= 5000, '汉字 %d' % han)
            check('p2. 中文正文正确', '完赛篇' in text)
        elif tag == 'p3':
            check('p3. 回归基准 汉字 >= 103', han >= 103, '汉字 %d' % han)
            check('p3. 回归基准 总字符 >= 250', len(body.rstrip('\n')) >= 250,
                  '%d 字符' % len(body.rstrip('\n')))
            check('p3. 关键字段正确', '参会者：刘明轩' in text and '签到码：424527' in text)
    return stats


def make_tmpdir():
    """样例写在测试目录下的临时子目录里（沙箱/权限受限时不依赖系统 %TEMP%）。"""
    tmp = os.path.join(HERE, '_samples_tmp_%d' % os.getpid())
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    return tmp


def main():
    keep = '--keep' in sys.argv
    mod = load_tool()
    tmp = make_tmpdir()
    print('样例目录: %s' % tmp)
    print('解释器  : %s' % sys.executable)
    print('-' * 72)
    try:
        failed = run_checks(mod, tmp)
    finally:
        if keep:
            print('样例文件保留在: %s' % tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print('-' * 72)
    print('共 %d 项断言，通过 %d，失败 %d' % (len(RESULTS), len(RESULTS) - len(failed), len(failed)))
    for n in failed:
        print('  FAILED: %s' % n)
    return 1 if failed else 0


def run_checks(mod, tmp):
    def dump(name, data):
        path = os.path.join(tmp, name)
        with open(path, 'wb') as f:
            f.write(data)
        return path

    # --- (a) 未压缩 / WinAnsi / 坏 xref
    a = dump('a.pdf', sample_a())
    ta = mod.extract_pdf_text(a)
    print('[a] 提取结果:\n%s\n' % ta)
    check('a. 数字标号 1.2.3', 'Invoice 1.2.3' in ta)
    check('a. 八进制转义 \\351 -> é', 'Caf\u00e9' in ta)
    check('a. TJ 大负间距补空格', 'Hello World' in ta)
    check("a. T*/' 换行", 'Line One' in ta and 'Line Two' in ta)
    check('a. 页标记', '[第 1 页]' in ta)
    check('a. 坏 xref 不影响', ta.startswith('[第 1 页]'))

    # --- (b) FlateDecode / 两页 / CRLF
    b = dump('b.pdf', sample_b())
    tb = mod.extract_pdf_text(b)
    print('[b] 提取结果:\n%s\n' % tb)
    check('b. FlateDecode 第一页', 'Compressed Page One' in tb)
    check('b. FlateDecode 第二页(CRLF 起始流)', 'Second 7.8.9' in tb)
    check('b. 两页标记顺序', tb.index('[第 1 页]') < tb.index('Compressed Page One')
          < tb.index('[第 2 页]') < tb.index('Second 7.8.9'))

    # --- (c) Identity-H + ToUnicode 中文
    c = dump('c.pdf', sample_c())
    tc = mod.extract_pdf_text(c)
    print('[c] 提取结果:\n%s\n' % tc)
    check('c. bfchar 中文 中文', '中文' in tc)
    check('c. bfrange 数组 国字', '国字' in tc)
    check('c. bfrange 单目标 一丁', '一丁' in tc)
    check('c. 无乱码替换符', '\ufffd' not in tc and '?' not in tc)
    check('c. 页标记', '[第 1 页]' in tc)

    # --- (d) 加密
    d = dump('d.pdf', sample_encrypted())
    rc, out, err = run_cli(d, os.path.join(tmp, 'd.txt'))
    print('[d] 加密样例 rc=%d stderr=%r' % (rc, err.strip()))
    check('d. 加密 exit 非 0', rc != 0)
    check('d. 加密 stderr 含 ENCRYPTED', 'ENCRYPTED' in err)
    check('d. 加密不产生输出文件', not os.path.exists(os.path.join(tmp, 'd.txt')))

    # --- (e) 无文本
    e = dump('e.pdf', sample_no_text())
    rc, out, err = run_cli(e, os.path.join(tmp, 'e.txt'))
    print('[e] 空页样例 rc=%d stderr=%r' % (rc, err.strip()))
    check('e. NO_TEXT exit 非 0', rc != 0)
    check('e. stderr 含 NO_TEXT', 'NO_TEXT' in err)
    check('e. 不产生空输出文件', not os.path.exists(os.path.join(tmp, 'e.txt')))

    # --- CLI 正常路径
    out_txt = os.path.join(tmp, 'a.txt')
    rc, out, err = run_cli(a, out_txt)
    body = ''
    if os.path.exists(out_txt):
        with open(out_txt, encoding='utf-8') as f:
            body = f.read()
    check('CLI a. exit 0', rc == 0, 'rc=%d stderr=%s' % (rc, err.strip()))
    check('CLI a. UTF-8 输出含关键串', 'Invoice 1.2.3' in body and 'Caf\u00e9' in body)
    check('CLI a. 输出含页标记', '[第 1 页]' in body)
    cli_c = os.path.join(tmp, 'c.txt')
    rc, out, err = run_cli(c, cli_c)
    body_c = ''
    if os.path.exists(cli_c):
        with open(cli_c, encoding='utf-8') as f:
            body_c = f.read()
    check('CLI c. 中文落盘正确', rc == 0 and '中文国字' in body_c and '一丁' in body_c)

    # --- 非 PDF 健壮性
    junk = os.path.join(tmp, 'not_a_pdf.txt')
    with open(junk, 'w', encoding='utf-8') as f:
        f.write('这只是一个普通的文本文件，不是 PDF。\nhello world\n')
    rc, out, err = run_cli(junk, os.path.join(tmp, 'junk.txt'))
    print('[junk] rc=%d stderr=%r' % (rc, err.strip()))
    check('junk. exit 非 0', rc != 0)
    check('junk. 无未捕获异常栈', 'Traceback' not in err and 'Traceback' not in out)
    check('junk. stderr 只有一行', len([x for x in err.strip().splitlines() if x.strip()]) == 1,
          repr(err))
    check('junk. 不产生输出文件', not os.path.exists(os.path.join(tmp, 'junk.txt')))

    # --- 参数缺失
    rc, out, err = run_cli()
    check('usage. 缺参数 exit 非 0 且无栈', rc != 0 and 'Traceback' not in err)

    # --- 真实 PDF 验收用例
    stats = check_real_pdfs(tmp)
    print('-' * 72)
    print('真实 PDF 统计（行数不含页标记；汉字含页标记里的「页」）:')
    for tag, path in REAL_PDFS:
        if tag in stats:
            rc, dt, body, plain, han = stats[tag]
            print('  %s  rc=%d  %.2fs  行=%d  汉字=%d  总字符=%d  %s'
                  % (tag, rc, dt, len(plain), han, len(body.rstrip('\n')),
                     os.path.basename(path)))
    for tag in ('p1', 'p2'):
        if tag in stats:
            print('--- %s 前 20 行 ---' % tag)
            for k, x in enumerate(stats[tag][3][:20], 1):
                print('%3d| %s' % (k, x))

    return [n for n, ok in RESULTS if not ok]


if __name__ == '__main__':
    sys.exit(main())
