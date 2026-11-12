# -*- coding: utf-8 -*-
"""locator · 索引器

把导入的文件抽取成纯文本，识别每行所属「标号」，建立倒排索引。
用法:
    python build_index.py add <文件或目录或通配符...> [--dir .locator] [--force]
    python build_index.py status [--dir .locator]
    python build_index.py remove <路径...> | clear
输出: 人类可读单行摘要（稳定、可直接转达）。
"""
from __future__ import annotations

import argparse
import glob as globmod
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
DEFAULT_DIRNAME = ".locator"

TEXT_EXTS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".log", ".json", ".jsonl",
    ".yaml", ".yml", ".ini", ".cfg", ".xml", ".html", ".htm", ".rst", ".tex",
    ".srt", ".vtt", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h",
    ".cpp", ".hpp", ".cs", ".go", ".rs", ".php", ".rb", ".sql", ".sh", ".ps1",
}
COM_EXTS = {".doc", ".docm", ".rtf", ".odt", ".xls", ".ppt", ".pdf"}

# —— 标号识别：按顺序命中，取第一个 ——
LABEL_RES = [
    ("marker", re.compile(r"^\[(?P<k>工作表|幻灯片|页|Sheet|Slide|Page)\s*(?P<n>[0-9]{0,4})\]\s*(?P<tail>.*)$")),
    ("md", re.compile(r"^#{1,6}\s+(?P<s>.+)$")),
    ("cn", re.compile(r"^(?P<s>第\s*[0-9一二三四五六七八九十百千万零〇]{1,6}\s*[章节節篇部编回条条款项](?:\s*[0-9一二三四五六七八九十]{1,6})?)")),
    ("appendix", re.compile(r"^(?P<s>附[录件表图]\s*[A-Za-z]?\s*[0-9]{0,3}(?:\.[0-9]{1,3})*)")),
    ("caption", re.compile(r"^(?P<s>[表图]\s*[0-9]{1,3}(?:[.\-][0-9]{1,3})*)")),
    ("sign", re.compile(r"^(?P<s>§\s*[0-9]{1,3}(?:\.[0-9]{1,3})*)")),
    ("br", re.compile(r"^(?P<s>[\[【（(]\s*[0-9]{1,3}(?:\.[0-9]{1,3}){0,6}\s*[\]】）)])")),
    ("dec", re.compile(r"^(?P<s>[0-9]{1,3}(?:\.[0-9]{1,3}){1,6})(?![0-9.])")),
    ("letter", re.compile(r"^(?P<s>[A-Za-z]\s*[.、)）]\s*[0-9]{1,3}(?:\.[0-9]{1,3})*)")),
    ("num", re.compile(r"^(?P<s>[0-9]{1,4})\s*[、.．)）]\s*")),
    ("cnnum", re.compile(r"^(?P<s>[一二三四五六七八九十]{1,3})\s*[、.．)）]\s*")),
]
INNER_NUM = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,6}|第\s*[0-9一二三四五六七八九十]{1,6}\s*[章节節篇部编回]")
FW = str.maketrans("０１２３４５６７８９．", "0123456789.")
NUM_TOKEN = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3})+")
LAT = re.compile(r"[A-Za-z0-9_]{1,}")
CJK = re.compile(r"[\u3400-\u9fff]+")


# ---------------------------------------------------------------- 基础工具
def norm(text: str) -> str:
    """统一换行，避免 Windows 下 \\r\\r\\n 把行号撑成两倍。"""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def dec(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "utf-16", "latin-1"):
        try:
            return norm(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return norm(raw.decode("utf-8", "replace"))


def find_pwsh() -> str | None:
    for name in ("pwsh", "powershell"):
        p = shutil.which(name)
        if p:
            return p
    for p in (
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    ):
        if Path(p).exists():
            return p
    return None


# —— LibreOffice Kit（dsoffice）：把 .doc/.xls/.ppt/.odt/.ods/.odp 转成新格式再抽取 ——
KIT_MAP = {".doc": ".docx", ".odt": ".docx",
           ".xls": ".xlsx", ".ods": ".xlsx",
           ".ppt": ".pptx", ".odp": ".pptx"}
_kit: tuple[str, str] | None | bool = False


def find_node() -> str | None:
    home = Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))
    cands = [os.environ.get("DSH_LO_KIT_NODE"), shutil.which("node")]
    try:
        cands += [str(p) for p in sorted(home.glob("dsh-runtimes/*/dependencies/node/bin/node.exe"))]
    except Exception:
        pass
    for c in cands:
        if c and Path(c).exists():
            return str(c)
    return None


def find_lo_kit() -> tuple[str, str] | None:
    """返回 (node.exe, cli.js)；找不到返回 None。可用 DSH_LO_KIT_CLI / DSH_LO_KIT_NODE 指定。"""
    global _kit
    if _kit is not False:
        return _kit                                    # type: ignore[return-value]
    _kit = None
    node = find_node()
    if not node:
        return None
    tail = Path("resources/app.asar.unpacked/dsh/node_modules/@deepseek-ai/libreoffice-kit/lib/cli.js")
    cli = os.environ.get("DSH_LO_KIT_CLI")
    if cli and Path(cli).exists():
        _kit = (node, str(cli))
        return _kit
    roots: list[Path] = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramData", "LOCALAPPDATA"):
        v = os.environ.get(env)
        if v:
            roots.append(Path(v))
            if env == "LOCALAPPDATA":
                roots.append(Path(v) / "Programs")
    roots += [Path(x + ":\\") for x in "CDEFGH"]
    cands: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        cands += [root / name / tail for name in ("DeepSeek Harness", "DeepSeekHarness", "dsh")]
        if root.parent == root:                        # 盘符根：再扫一层目录名
            try:
                cands += [sub / tail for sub in root.iterdir() if sub.is_dir()]
            except Exception:
                pass
    for c in cands:
        if c.exists():
            _kit = (node, str(c))
            return _kit
    return None


def via_lo_kit(p: Path, out: Path, suffix: str) -> Path:
    kit = find_lo_kit()
    if not kit:
        raise RuntimeError("没找到 LibreOffice Kit（dsoffice）")
    node, cli = kit
    tmp = out.parent / (out.name + suffix)             # 与 out 同目录，随 out 一起清理
    if tmp.exists():
        tmp.unlink()
    code, so, se = run([node, cli, "convert", "--input", str(p), "--output", str(tmp)], timeout=300)
    if code != 0 or not tmp.exists():
        raise RuntimeError(f"lo-kit 转换失败({code}): {(se or so).strip()[:160]}")
    return tmp


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return 124, "", f"命令超时（{timeout}s）：{Path(cmd[-1]).name}"
    return p.returncode, p.stdout or "", p.stderr or ""


def load_custom_labels(d: Path) -> list[tuple[str, re.Pattern]]:
    """读 <索引目录>/labels.json：自定义标号正则数组，优先级高于内置规则。"""
    f = d / "labels.json"
    if not f.exists():
        return []
    try:
        items = json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for i, it in enumerate(items if isinstance(items, list) else []):
        rx = it.get("re") if isinstance(it, dict) else it
        try:
            out.append((f"custom{i}", re.compile(rx)))
        except re.error:
            continue
    return out


def detect_label(line: str, extra: list | None = None):
    """返回 (标号, 标题) 或 None。"""
    s = line.strip().translate(FW)      # 全角数字/句点归一，便于统一比对标号
    if not s or len(s) > 120:
        return None
    for kind, rx in list(extra or []) + LABEL_RES:
        m = rx.match(s)
        if not m:
            continue
        gd = m.groupdict()
        if kind == "marker":
            k, n, tail = m.group("k"), m.group("n"), m.group("tail").strip()
            lab = f"{k}{n}" if n else (tail or k)
            return lab, (tail[:60] if (n and tail) else "")
        if "s" in gd and gd["s"]:
            lab = gd["s"].strip()
        else:
            lab = m.group(0).strip()
        if not lab:
            continue
        rest = s[m.end():].strip(" \t·—:：-|")
        if kind == "md":
            inner = INNER_NUM.search(lab)
            return (inner.group(0) if inner else lab), (lab if inner else rest)
        if kind in ("num", "cnnum") and len(lab) > 12:
            return None
        if not rest and lab.endswith(("、", ".", "．", ")", "）")):
            return None
        return lab, (rest if len(rest) <= 60 else rest[:60])
    return None


def tokenize(text: str) -> set[str]:
    t = text.lower()
    out: set[str] = set(NUM_TOKEN.findall(t))
    for m in LAT.finditer(t):
        w = m.group()
        if len(w) >= 2:
            out.add(w)
    for m in CJK.finditer(t):
        run_ = m.group()
        if len(run_) == 1:
            out.add(run_)
            continue
        for i in range(len(run_) - 1):
            out.add(run_[i:i + 2])
        if len(run_) <= 8:
            out.add(run_)
    return out


# ---------------------------------------------------------------- 抽取
def from_docx(p: Path) -> str:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(p))
    lines = []
    for child in d.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            lines.append(Paragraph(child, d).text.replace("\n", " ").rstrip())
        elif tag == "tbl":
            for row in Table(child, d).rows:
                cells = [c.text.replace("\n", " ").strip() for c in row.cells]
                lines.append(" | ".join(cells).rstrip(" |"))
    return "\n".join(lines)


def from_xlsx(p: Path) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(str(p), read_only=True, data_only=True)
    lines = []
    try:
        for ws in wb.worksheets:
            lines.append(f"[工作表] {ws.title}")
            for i, row in enumerate(ws.iter_rows(values_only=True), 1):
                vals = ["" if v is None else str(v).replace("\n", " ").strip() for v in row]
                while vals and vals[-1] == "":
                    vals.pop()
                if not any(vals):
                    continue
                lines.append(f"行{i}\t" + " | ".join(vals))
    finally:
        wb.close()
    return "\n".join(lines)


def from_pptx(p: Path) -> str:
    from pptx import Presentation

    prs = Presentation(str(p))
    lines = []
    for n, slide in enumerate(prs.slides, 1):
        lines.append(f"[幻灯片 {n}]")
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(r.text for r in para.runs).strip()
                    if t:
                        lines.append(t)
            if getattr(shape, "has_table", False) and shape.has_table:
                for i, row in enumerate(shape.table.rows, 1):
                    cells = [c.text.replace("\n", " ").strip() for c in row.cells]
                    lines.append(f"表格行{i}\t" + " | ".join(cells))
    return "\n".join(lines)


RTF_SKIP_DESTS = {
    "fonttbl", "colortbl", "stylesheet", "info", "pict", "generator", "listtable",
    "listoverridetable", "rsidtbl", "themedata", "datastore", "latentstyles", "xmlnstbl",
    "header", "headerl", "headerr", "footer", "footerl", "footerr", "fldinst", "filetbl",
    "mmathpr", "wgrffmtfilter", "panose", "falt", "objdata", "shp", "shpinst", "nonshppict",
}


def from_rtf(p: Path) -> str:
    """RTF 直接解析（转换引擎没有 rtf 滤镜）：去控制字、按 \\ansicpg 解码 \\'hh、认 \\uN。"""
    raw = p.read_bytes()
    n = len(raw)
    out: list[str] = []
    pending = bytearray()
    cp = "cp936"
    uc = 1
    skip = 0

    def flush() -> None:
        if pending:
            try:
                out.append(pending.decode(cp, "replace"))
            except LookupError:
                out.append(pending.decode("latin-1", "replace"))
            pending.clear()

    i = 0
    while i < n:
        c = raw[i]
        if c == 0x7B:                                   # {
            if skip:
                skip += 1
                i += 1
                continue
            j = i + 1
            while j < n and raw[j] in (0x20, 0x09, 0x0A, 0x0D):
                j += 1
            star = False
            k = j
            if k < n and raw[k] == 0x5C:
                k += 1
                if k < n and raw[k] == 0x2A:             # \*
                    star = True
                    k += 1
                    while k < n and raw[k] in (0x20, 0x09, 0x0A, 0x0D):
                        k += 1
                m = k
                while m < n and (65 <= raw[m] <= 90 or 97 <= raw[m] <= 122):
                    m += 1
                dest = raw[k:m].decode("ascii", "replace").lower()
                if star or dest in RTF_SKIP_DESTS:       # 非正文目标：整组丢掉
                    skip = 1
                    i += 1
                    continue
            i += 1
            continue
        if c == 0x7D:                                   # }
            if skip:
                skip -= 1
            i += 1
            continue
        if skip:
            i += 1
            continue
        if c == 0x5C:                                   # 反斜杠
            nxt = raw[i + 1] if i + 1 < n else None
            if nxt in (0x5C, 0x7B, 0x7D):               # \\ \{ \}
                flush()
                out.append(chr(nxt))
                i += 2
                continue
            if nxt == 0x27:                             # \'hh 十六进制字节
                try:
                    pending.append(int(raw[i + 2:i + 4].decode("ascii"), 16))
                except Exception:
                    pass
                i += 4
                continue
            if nxt == 0x7E:                             # \~ 不换行空格
                flush()
                out.append("\u00a0")
                i += 2
                continue
            j = i + 1
            if j < n and raw[j] == 0x2A:
                j += 1
            k = j
            while k < n and (65 <= raw[k] <= 90 or 97 <= raw[k] <= 122):
                k += 1
            word = raw[j:k].decode("ascii", "replace").lower()
            m = k
            if m < n and raw[m] == 0x2D:
                m += 1
            while m < n and 48 <= raw[m] <= 57:
                m += 1
            param = raw[k:m].decode("ascii", "replace")
            if m < n and raw[m] == 0x20:
                m += 1
            if word == "ansicpg" and param:
                flush()
                cp = "cp" + param
            elif word == "uc" and param:
                flush()
                uc = int(param or 1)
            elif word == "u" and param:
                flush()
                try:
                    v = int(param)
                    out.append(chr(v + 65536 if v < 0 else v))
                except Exception:
                    pass
                for _ in range(max(1, uc)):             # 跳过 \\uN 的替代字符
                    if raw[m:m + 2] == b"\\'":
                        m += 4
                    elif m < n and raw[m] == 0x3F:
                        m += 1
                    else:
                        break
            elif word in ("par", "line", "pard", "sect", "row"):
                flush()
                out.append("\n")
            elif word == "cell":
                flush()
                out.append("\t")
            elif word == "tab":
                flush()
                out.append("\t")
            i = m
            continue
        if c in (0x0A, 0x0D):                           # RTF 源里的裸换行不算内容
            i += 1
            continue
        flush()
        out.append(chr(c))
        i += 1
    flush()
    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return norm(text).strip("\n")


def via_com(p: Path, out: Path) -> str:
    ps = find_pwsh()
    if not ps:
        raise RuntimeError("找不到 pwsh/powershell，无法调用 Office COM")
    script = HERE / "office_to_text.ps1"
    if not script.exists():
        raise RuntimeError(f"缺少 {script}")
    cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
           "-File", str(script), "-Path", str(p), "-Out", str(out)]
    code, _, err = run(cmd)
    if code != 0:
        raise RuntimeError(f"office_to_text 退出 {code}: {err.strip()[:200]}")
    return dec(out)


def via_pdf_text(p: Path, out: Path) -> str:
    script = HERE / "pdf_text.py"
    if not script.exists():
        raise RuntimeError(f"缺少 {script}")
    code, _, err = run([sys.executable, str(script), str(p), str(out)])
    if code != 0:
        raise RuntimeError(f"pdf_text 退出 {code}: {err.strip()[:200]}")
    return dec(out)


def sniff(p: Path) -> str:
    """按文件头认出真实类型（附件常没有扩展名）。"""
    try:
        head = p.open("rb").read(8)
    except Exception:
        return ""
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head[:4] == b"\xd0\xcf\x11\xe0":
        return ".ole"                      # doc/xls/ppt 老格式（需 Office 转换）
    if head[:4] == b"PK\x03\x04":
        import zipfile
        try:
            with zipfile.ZipFile(p) as z:
                names = z.namelist()
            for pre, ext in (("word/", ".docx"), ("xl/", ".xlsx"), ("ppt/", ".pptx")):
                if any(n.startswith(pre) for n in names):
                    return ext
        except Exception:
            pass
        return ".docx"
    return ""


def extract(p: Path, out: Path) -> tuple[str, str]:
    """返回 (文本, 方法)。"""
    ext = p.suffix.lower()
    if ext not in TEXT_EXTS | COM_EXTS | {".docx", ".xlsx", ".xlsm", ".pptx"}:
        ext = sniff(p) or ext
    if ext in TEXT_EXTS:
        return dec(p), "text"
    if ext in (".docx", ".docm"):
        return from_docx(p), "python-docx"
    if ext in (".xlsx", ".xlsm"):
        return from_xlsx(p), "openpyxl"
    if ext in (".pptx", ".pptm"):
        return from_pptx(p), "python-pptx"
    if ext == ".rtf":
        return from_rtf(p), "rtf"
    if ext == ".pdf":
        errs = []
        try:
            return via_pdf_text(p, out), "pdf_text"
        except Exception as e1:
            errs.append(str(e1))
        try:
            return via_com(p, out), "word-com"
        except Exception as e2:
            errs.append(str(e2))
        raise RuntimeError("PDF 提取失败（内置解析与 Word COM 均失败）：" + " / ".join(errs)[:300] +
                           "｜若是扫描件/加密件，请先用 OCR 或另存为带文字层的 PDF")
    if ext in KIT_MAP or ext == ".ole":
        errs: list[str] = []
        pairs = [(ext, KIT_MAP[ext])] if ext in KIT_MAP else \
                [(".doc", ".docx"), (".xls", ".xlsx"), (".ppt", ".pptx")]
        for src_ext, tgt in pairs:                     # .ole 无扩展名旧格式：补扩展名挨个试
            try:
                src = p
                if src_ext != ext:                     # lo-kit 靠扩展名认格式，得先补上
                    src = out.parent / (out.name + ".in" + src_ext)
                    shutil.copyfile(p, src)
                conv = via_lo_kit(src, out, tgt)
                if tgt == ".docx":
                    return from_docx(conv), "lo-kit→docx"
                if tgt == ".xlsx":
                    return from_xlsx(conv), "lo-kit→xlsx"
                return from_pptx(conv), "lo-kit→pptx"
            except Exception as e:
                errs.append(f"{src_ext}: {str(e)[:90]}")
        try:                                           # 兜底：老办法 Office COM
            return via_com(p, out), "office-com"
        except Exception as e:
            errs.append(str(e)[:100])
        raise RuntimeError("抽不出来（LibreOffice Kit 与 Office COM 都失败）：" + " / ".join(errs)[:240] +
                           "｜可先在 Office/WPS 里另存为 docx/xlsx/pptx 再导入")
    if ext in COM_EXTS:
        try:
            return via_com(p, out), "office-com"
        except Exception as e:
            raise RuntimeError(
                f"需要本机 Office COM，但在受限进程里不可用（{str(e)[:120]}）"
                "｜请先在 Office 里另存为 docx/xlsx/pptx 或 PDF 再导入")
    try:
        return dec(p), "text?"
    except Exception:
        return via_com(p, out), "office-com"


# ---------------------------------------------------------------- 索引
def load_meta(d: Path) -> dict:
    f = d / "meta.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"version": 1, "sources": [], "updated": None}


def save_meta(d: Path, meta: dict) -> None:
    meta["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


SEP = "\x1f"


def load_records(d: Path) -> list[dict]:
    tsv = d / "index.tsv"
    if tsv.exists():
        recs = []
        with tsv.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                parts = line.split(SEP)
                if len(parts) < 5:
                    continue
                recs.append({"f": parts[0], "p": parts[1], "l": int(parts[2]),
                             "s": parts[3], "t": parts[4]})
        return recs
    f = d / "index.jsonl"          # 兼容旧索引
    if not f.exists():
        return []
    recs = []
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            recs.append(json.loads(line))
    return recs


def write_records(d: Path, recs: list[dict]) -> None:
    """紧凑 TSV（\\x1f 分隔），加载比 JSONL 快数倍。"""
    with (d / "index.tsv").open("w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            t = r["t"].replace(SEP, " ").replace("\n", " ").replace("\r", " ")
            fh.write(SEP.join((r["f"], r["p"], str(r["l"]), r["s"], t)) + "\n")
    old = d / "index.jsonl"
    if old.exists():
        old.unlink()


def build_tokens(d: Path, recs: list[dict]) -> int:
    inv: dict[str, list[int]] = {}
    for i, r in enumerate(recs):
        for t in tokenize(r["t"]):
            inv.setdefault(t, []).append(i)
    (d / "tokens.json").write_text(json.dumps(inv, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return len(inv)


def slug(p: Path) -> str:
    h = hashlib.md5(str(p).encode("utf-8")).hexdigest()[:6]
    name = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", p.name)[:60]
    return f"{name}.{h}"


def expand(paths: list[str], cwd: Path) -> list[Path]:
    out: list[Path] = []
    for item in paths:
        c = Path(item)
        if not c.is_absolute():
            c = cwd / c
        if c.is_dir():
            for sub in sorted(c.rglob("*")):
                if sub.is_file() and sub.suffix.lower() not in {".tmp", ".bak"}:
                    out.append(sub.resolve())
        else:
            hits = [Path(g).resolve() for g in globmod.glob(str(c), recursive=True)]
            out.extend(hits or [c.resolve()])
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def index_one(d: Path, recs: list[dict], meta: dict, p: Path, force: bool,
              extra_labels: list) -> tuple[list[dict], str]:
    """抽取一个文件、重建它的记录。返回 (新的 recs, 一行摘要)。"""
    (d / "raw").mkdir(parents=True, exist_ok=True)
    key = str(p)
    old = next((s for s in meta["sources"] if s["path"] == key), None)
    st = p.stat() if p.exists() else None
    if old and st and not force and old.get("size") == st.st_size and old.get("mtime") == int(st.st_mtime):
        return recs, f"跳过(已索引) {p.name}"
    if not p.exists():
        return recs, f"失败 {p} : 文件不存在"
    tmp = d / "raw" / (slug(p) + ".tmp.txt")
    try:
        text, method = extract(p, tmp)
    except Exception as e:
        for junk in (d / "raw").glob(slug(p) + ".tmp*"):
            junk.unlink()
        return recs, f"失败 {p.name} : {str(e)[:160]}"
    raw = d / "raw" / (slug(p) + ".txt")
    text = norm(text)
    raw.write_text(text, encoding="utf-8", newline="\n")   # 不翻译换行，行号才准
    for junk in (d / "raw").glob(slug(p) + ".tmp*"):       # 转换中间产物一并清掉
        junk.unlink()
    recs = [r for r in recs if r["p"] != key]              # 先剔除该文件的旧记录
    cur_label, n_labels = "", 0
    for ln, raw_line in enumerate(text.splitlines(), 1):
        hit = detect_label(raw_line, extra_labels)
        if hit:
            lab = hit[0]
            if lab and lab != cur_label:
                cur_label = lab
                n_labels += 1
        recs.append({"f": p.name, "p": key, "l": ln, "s": cur_label, "t": raw_line})
    src = {
        "path": key, "file": p.name, "ext": p.suffix.lower(), "method": method,
        "chars": len(text), "lines": len(text.splitlines()), "labels": n_labels,
        "size": st.st_size if st else 0, "mtime": int(st.st_mtime) if st else 0,
        "raw": raw.name, "added": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    pos = next((i for i, s in enumerate(meta["sources"]) if s["path"] == key), None)
    if pos is None:
        meta["sources"].append(src)                        # 新文件排到末尾
    else:
        meta["sources"][pos] = src                         # 重建就原地更新，顺序不乱
    warn = "" if n_labels else " ⚠标号0个"
    return recs, f"已导入 {p.name} : {src['lines']}行/{src['chars']}字 · 标号{n_labels}个 · 方式{method}{warn}"


def sync_index(d: Path) -> tuple[list[dict], list[str]]:
    """查询前自我校对：已登记的文件按 大小+mtime 比一遍，变了的重建。返回 (recs, 变化摘要)。"""
    meta = load_meta(d)
    if not meta.get("sources"):
        return [], []
    recs = load_records(d)
    extra = load_custom_labels(d)
    changed: list[str] = []
    for s in list(meta["sources"]):
        p = Path(s["path"])
        try:
            st = p.stat()
        except Exception:
            continue                                        # 源文件不在/读不到：留着旧内容，不动
        if s.get("size") == st.st_size and s.get("mtime") == int(st.st_mtime):
            continue
        recs, line = index_one(d, recs, meta, p, False, extra)
        if line.startswith("已导入"):
            changed.append(line)
    if changed:
        write_records(d, recs)
        build_tokens(d, recs)
        save_meta(d, meta)
    return recs, changed


def cmd_add(args) -> int:
    d = Path(args.dir).resolve()
    (d / "raw").mkdir(parents=True, exist_ok=True)
    meta = load_meta(d)
    recs = load_records(d)
    targets = expand(args.paths, Path.cwd())
    if not targets:
        print("〔导入 0 个〕没有匹配到文件")
        return 1
    lines_out = []
    extra_labels = load_custom_labels(d)
    for p in targets:
        recs, line = index_one(d, recs, meta, p, args.force, extra_labels)
        lines_out.append(line)
    write_records(d, recs)
    n_tok = build_tokens(d, recs)
    save_meta(d, meta)
    print("\n".join(lines_out))
    print(f"〔索引〕文件{len(meta['sources'])}个 · 行{len(recs)} · 词条{n_tok} · 目录 {d}")
    return 0


def cmd_status(args) -> int:
    d = Path(args.dir).resolve()
    meta = load_meta(d)
    if not meta["sources"]:
        print(f"〔状态〕索引为空（目录 {d}）")
        return 0
    print(f"〔状态〕{len(meta['sources'])} 个文件 · 更新 {meta.get('updated')}")
    for s in meta["sources"]:
        print(f"- {s['file']} · {s['lines']}行 · 标号{s['labels']}个 · {s['method']}")
    return 0


def cmd_remove(args) -> int:
    d = Path(args.dir).resolve()
    meta = load_meta(d)
    drop = {str(Path(x).resolve()) for x in args.paths}
    recs = [r for r in load_records(d) if r["p"] not in drop]
    meta["sources"] = [s for s in meta["sources"] if s["path"] not in drop]
    write_records(d, recs)
    build_tokens(d, recs)
    save_meta(d, meta)
    print(f"〔移除〕{len(drop)} 个 · 剩余文件{len(meta['sources'])} · 行{len(recs)}")
    return 0


def cmd_clear(args) -> int:
    d = Path(args.dir).resolve()
    if d.exists():
        shutil.rmtree(d)
    print(f"〔清空〕已删除 {d}")
    return 0


def main() -> int:
    argv = sys.argv[1:]
    # --dir 允许出现在任意位置（argparse 子命令不允许全局选项后置）
    idx_dir = DEFAULT_DIRNAME
    for i, a in enumerate(list(argv)):
        if a == "--dir" and i + 1 < len(argv):
            idx_dir = argv[i + 1]
            del argv[i:i + 2]
            break
        if a.startswith("--dir="):
            idx_dir = a.split("=", 1)[1]
            del argv[i]
            break
    ap = argparse.ArgumentParser(prog="build_index.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("paths", nargs="+")
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_add)
    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)
    r = sub.add_parser("remove")
    r.add_argument("paths", nargs="+")
    r.set_defaults(func=cmd_remove)
    c = sub.add_parser("clear")
    c.set_defaults(func=cmd_clear)
    args = ap.parse_args(argv)
    args.dir = idx_dir
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
