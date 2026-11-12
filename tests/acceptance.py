# -*- coding: utf-8 -*-
"""locator 验收脚本：跑一遍导入 → 查询 → PDF 抽取质量检查，全过才算合格。

用法: python tests/acceptance.py
退出码 0 = 全过；非 0 = 有 FAIL（逐条打印）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
TOOLS = SKILL / "tools"
PY = sys.executable
WS = HERE / "ws"
LOC = WS / ".locator"

REAL_PDFS_TXT = HERE / "real_pdfs.txt"
REAL_LEGACY_TXT = HERE / "real_legacy.txt"


def paths_from(f: Path) -> list[Path]:
    if not f.exists():
        return []
    return [Path(x.strip()) for x in f.read_text(encoding="utf-8").splitlines()
            if x.strip() and not x.startswith("#")]


def real_pdfs() -> list[Path]:
    """真实 PDF 验收用例：优先环境变量 LOCATOR_TEST_PDFS（; 分隔），其次 tests/real_pdfs.txt。"""
    import os
    env = os.environ.get("LOCATOR_TEST_PDFS", "").strip()
    if env:
        return [Path(x.strip()) for x in env.split(";") if x.strip()]
    return paths_from(REAL_PDFS_TXT)


results: list[tuple[bool, str]] = []


def check(ok: bool, msg: str) -> None:
    results.append((ok, msg))
    print(("PASS " if ok else "FAIL ") + msg)


KO_PROBE = {".doc": "的", ".xls": "1", ".ppt": "的"}


def ko_probe(kind: str) -> str:
    """老格式样本的查询词：用几乎必然出现的最短字符，只验链路通不通。"""
    return KO_PROBE.get("." + kind, "的")


def sh(args: list[str], cwd: Path | None = None):
    import os
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(cwd) if cwd else None, env=env)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 1. 样例
    sys.path.insert(0, str(HERE))
    import make_fixtures
    make_fixtures.make_docx(); make_fixtures.make_xlsx()
    make_fixtures.make_pptx(); make_fixtures.make_txt(); make_fixtures.make_rtf()
    (HERE / "data" / "crlf.txt").write_bytes(
        "1.1 甲\n乙丙丁内容\n1.2 戊\n己庚辛内容\n".replace("\n", "\r\n").encode("utf-8"))
    check(True, "生成 docx/xlsx/pptx/txt 样例")

    # 2. 导入
    if LOC.exists():
        shutil.rmtree(LOC)
    r = sh([PY, str(TOOLS / "build_index.py"), "add", str(HERE / "data"), "--dir", str(LOC)])
    check(r.returncode == 0, "build_index add 退出 0")
    check("手册A.docx" in r.stdout and "标号0个" not in r.stdout.split("手册A.docx")[1][:40],
          "docx 识别到标号")
    check("⚠标号0个" not in r.stdout.replace("培训讲义.pptx", "").replace("备件表.xlsx", ""),
          "无异常标号缺失（PPT/XLS 用结构标号）")

    # 3. 查询断言
    cases = [
        ("四象限整流", ["培训讲义.pptx", "手册A.docx", "§1.1"]),
        ("断电", ["手册A.docx", "§2.3.1", "第10行"]),
        ("KBPC3510", ["备件表.xlsx", "§备件表"]),
        ("E045", ["手册A.docx", "§附录A.1"]),
        ("归档", ["笔记.txt", "§[1]"]),
        ("己庚辛内容", ["crlf.txt", "第4行"]),
    ]
    for q, needles in cases:
        r = sh([PY, str(TOOLS / "locate.py"), q, "--dir", str(LOC)])
        missing = [n for n in needles if n not in r.stdout]
        check(not missing, f"查询「{q}」命中 {'/'.join(needles)}" + (f"（缺 {missing}）" if missing else ""))

    r = sh([PY, str(TOOLS / "locate.py"), "绝无此词zzq", "--dir", str(LOC)])
    check("〔未命中〕" in r.stdout, "无关词返回未命中")

    # 3b. 整段模式（口令「搜索…」走的路径）：字面命中 → 整段原文，不近似、不换词
    r = sh([PY, str(TOOLS / "locate.py"), "断电", "--section", "--dir", str(LOC)])
    check("§2.3.1" in r.stdout and "命中第10行" in r.stdout, "整段模式表头给出序号与命中行号")
    check("2.3.1 整机安装步骤" in r.stdout and "整机安装完成后测量绝缘电阻" in r.stdout,
          "整段模式给出整段原文（含命中行以外的行）")
    check(not re.search(r"^\s*\d+\| ", r.stdout, re.M), "整段原文照原排版，不加行号前缀")
    r = sh([PY, str(TOOLS / "locate.py"), "绝无此词zzq", "--section", "--dir", str(LOC)])
    check("〔未命中〕" in r.stdout and "近似" not in r.stdout, "整段模式无命中时不走近似、不换词")

    # 3c. RTF 解析：\'hh(GBK) 与 \uN 两种中文写法都要解出来，忽略组不能漏进正文
    r = sh([PY, str(TOOLS / "locate.py"), "台账需登记", "--section", "--dir", str(LOC)])
    check("笔记B.rtf" in r.stdout and "§3.1" in r.stdout, "RTF 的 \\'hh(GBK) 中文解出并带标号")
    r = sh([PY, str(TOOLS / "locate.py"), "案例", "--section", "--dir", str(LOC)])
    check("〔命中" in r.stdout, "RTF 的 \\uN 中文解出")
    r = sh([PY, str(TOOLS / "locate.py"), "generator", "--section", "--dir", str(LOC)])
    check("〔未命中〕" in r.stdout, "RTF 忽略组（generator/fonttbl）没漏进正文")
    r = sh([PY, str(TOOLS / "locate.py"), "台账", "--section", "--dir", str(LOC)])
    check("台账需登记" in r.stdout and not re.search(r"^\s*\d+\| ", r.stdout, re.M),
          "RTF 整段原文照原排版（空行保留、无行号前缀）")

    # 3d. 查询前自动同步：源文件改了，不重跑 add 也该搜到新内容
    import time as _time
    syncf = WS / "同步用例.txt"
    syncf.write_text("1.1 甲\n同步前的内容\n", encoding="utf-8")
    sh([PY, str(TOOLS / "build_index.py"), "add", str(syncf), "--dir", str(LOC)])
    _time.sleep(1.2)                                   # mtime 精确到秒，等一秒才认得出改动
    syncf.write_text("1.1 甲\n同步后的内容\n", encoding="utf-8")
    r = sh([PY, str(TOOLS / "locate.py"), "同步后的内容", "--section", "--dir", str(LOC)])
    check("〔已同步〕" in r.stdout and "同步后的内容" in r.stdout,
          "查询前自动同步：改过的文件直接搜得到")
    r = sh([PY, str(TOOLS / "locate.py"), "同步前的内容", "--section", "--dir", str(LOC)])
    check("〔未命中〕" in r.stdout, "自动同步后旧内容不再命中")
    r = sh([PY, str(TOOLS / "locate.py"), "同步后的内容", "--no-sync", "--dir", str(LOC)])
    check("〔命中" in r.stdout, "--no-sync 仍能正常查询")

    # 3e. 口令可塑性：口令写在 triggers.json，set_triggers.py 把它同步成 AGENTS.md 里的契约块
    tcfg = json.loads((SKILL / "triggers.json").read_text(encoding="utf-8"))
    check("添加文件到数据库" in tcfg.get("add", []) and "搜索" in tcfg.get("search", []),
          "triggers.json 里存着当前口令")
    tmp_agents = WS / "AGENTS-test.md"
    if tmp_agents.exists():
        tmp_agents.unlink()
    r = sh([PY, str(TOOLS / "set_triggers.py"), "sync", "--path", str(tmp_agents)])
    t1 = tmp_agents.read_text(encoding="utf-8") if tmp_agents.exists() else ""
    check("locator:begin" in t1 and "添加文件到数据库" in t1 and "build_index.py" in t1,
          "set_triggers sync 生成口令契约块")
    tmp_agents.write_text("前面本来就有的话\n\n" + t1, encoding="utf-8")
    ra = sh([PY, str(TOOLS / "set_triggers.py"), "sync", "--path", str(tmp_agents)])
    rb = sh([PY, str(TOOLS / "set_triggers.py"), "sync", "--path", str(tmp_agents)])
    t2 = tmp_agents.read_text(encoding="utf-8")
    check("前面本来就有的话" in t2 and t2.count("locator:begin") == 1 and t2.count("locator:end") == 1,
          "重复 sync 幂等：不叠加、不动别的内容")
    check(ra.returncode == 0 and rb.returncode == 0 and "bad escape" not in (ra.stderr + rb.stderr),
          "重复 sync 不因路径里的反斜杠报错（re 替换说）")

    # 3f. 换口令全流程（在技能副本上做，不动本仓库的 triggers.json）
    import shutil as _shutil
    copy = WS / "skillcopy"
    if copy.exists():
        _shutil.rmtree(copy, ignore_errors=True)
    (copy / "tools").mkdir(parents=True, exist_ok=True)
    _shutil.copy2(SKILL / "triggers.json", copy / "triggers.json")
    _shutil.copy2(TOOLS / "set_triggers.py", copy / "tools" / "set_triggers.py")
    agents2 = WS / "AGENTS-newuser.md"
    if agents2.exists():
        agents2.unlink()
    r1 = sh([PY, str(copy / "tools" / "set_triggers.py"), "add", "喂资料", "--path", str(agents2)])
    check(r1.returncode == 0 and "喂资料" in agents2.read_text(encoding="utf-8"),
          "换导入口令：AGENTS.md 里立刻是新词")
    r2 = sh([PY, str(copy / "tools" / "set_triggers.py"), "search", "找一下", "--path", str(agents2)])
    t3 = agents2.read_text(encoding="utf-8")
    check(r2.returncode == 0 and "找一下" in t3 and "喂资料" in t3 and t3.count("locator:begin") == 1,
          "再换查询口令：两个新词在同一块里、没叠加")

    r = sh([PY, str(TOOLS / "locate.py"), "--outline", "--dir", str(LOC)])
    check("§2.3.1" in r.stdout and "§幻灯片1" in r.stdout, "outline 列出文档与幻灯片标号")

    # 4. 真实 PDF 抽取质量
    outdir = HERE / "pdf"
    outdir.mkdir(exist_ok=True)
    pdfs = real_pdfs()
    check(True, f"真实 PDF 用例 {len(pdfs)} 个（缺 tests/real_pdfs.txt 时跳过）")
    for i, pdf in enumerate(pdfs, 1):
        if not pdf.exists():
            check(True, f"跳过缺失的真实 PDF：{pdf.name}")
            continue
        out = outdir / f"p{i}.txt"
        if out.exists():
            out.unlink()
        r = sh([PY, str(TOOLS / "pdf_text.py"), str(pdf), str(out)])
        if r.returncode != 0:
            check(False, f"PDF 提取 {pdf.name} 退出 {r.returncode}: {r.stderr.strip()[:80]}")
            continue
        text = out.read_text(encoding="utf-8", errors="replace")
        lines = [x for x in text.splitlines() if x.strip() and not x.startswith("[第")]
        single = sum(1 for x in lines if len(x.strip()) == 1)
        ratio = single / max(1, len(lines))
        cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
        check(len(lines) > 5, f"PDF {pdf.name} 有正文行（{len(lines)} 行）")
        check(ratio < 0.25, f"PDF {pdf.name} 未被拆成单字符行（单字符行占比 {ratio:.0%}）")
        check(cjk > 30, f"PDF {pdf.name} 含中文（{cjk} 个汉字）")

        # PDF 走完整链路：add → locate（此前只直接调 pdf_text.py，链路未验）
        loc2 = outdir / ".locator"
        if loc2.exists():
            shutil.rmtree(loc2)
        r = sh([PY, str(TOOLS / "build_index.py"), "add", str(pdf), "--dir", str(loc2)])
        check(r.returncode == 0 and pdf.name in r.stdout,
              f"PDF {pdf.name} 可导入索引")
        # 从抽取文本里挑一个足够长的中文词当查询词
        cand = max((re.findall(r"[\u4e00-\u9fff]{3,}", text) or [""]), key=len)
        if cand:
            r = sh([PY, str(TOOLS / "locate.py"), cand, "--dir", str(loc2)])
            check(pdf.name in r.stdout and "〔命中" in r.stdout,
                  f"PDF {pdf.name} 可被查询命中（词「{cand[:8]}」）")
            bad = [x for x in r.stdout.splitlines() if "§(无标号)" in x and "※标题行" in x]
            check(not bad, f"PDF {pdf.name} 无标号行未被误标为标题行")

    # 5. 老格式 .doc/.xls（经 LibreOffice Kit 转换；缺样本或未装 Kit 时跳过）
    legacy = paths_from(REAL_LEGACY_TXT)
    check(True, f"真实老格式用例 {len(legacy)} 个（缺 tests/real_legacy.txt 时跳过）")
    if legacy:
        loc3 = HERE / "legacy" / ".locator"
        if loc3.exists():
            shutil.rmtree(loc3, ignore_errors=True)
        for f in legacy:
            if not f.exists():
                check(True, f"跳过缺失的老格式样本：{f.name}")
                continue
            r = sh([PY, str(TOOLS / "build_index.py"), "add", str(f), "--dir", str(loc3)])
            ok = r.returncode == 0 and "lo-kit" in r.stdout
            check(ok, f"老格式 {f.name} 经 lo-kit 导入" + ("" if ok else f"（{r.stdout.strip()[:90]}）"))
            if not ok:
                continue
            key = f.suffix.lower().lstrip(".")
            r2 = sh([PY, str(TOOLS / "locate.py"), ko_probe(key), "--section", "--dir", str(loc3)])
            check("〔命中" in r2.stdout or "〔未命中" in r2.stdout,
                  f"老格式 {f.name} 导入后可查询（{key}）")

    # 6. 汇总
    bad = [m for ok, m in results if not ok]
    print(f"\n〔验收〕{len(results) - len(bad)}/{len(results)} 通过")
    for m in bad:
        print("  ✗ " + m)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
