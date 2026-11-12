# -*- coding: utf-8 -*-
"""locator · 查询器

输入一个词/一句话，输出「在哪个文件 · 哪个标号 · 第几行」。
用法:
    python locate.py "<词或句子>" [--dir .locator] [--limit 8] [--file 过滤] [--outline] [--json]
设计: 先全量字面命中（最准最全），无命中再走倒排词条近似（给出候选）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DIRNAME = ".locator"

NUM_TOKEN = re.compile(r"[0-9]{1,3}(?:\.[0-9]{1,3})+")
LAT = re.compile(r"[A-Za-z0-9_]{2,}")
CJK = re.compile(r"[\u3400-\u9fff]+")
NAT = re.compile(r"(\d+)")


def natkey(s: str):
    return [int(x) if x.isdigit() else x for x in NAT.split(s or "")]


SEP = "\x1f"


def load_meta(d: Path) -> dict:
    mf = d / "meta.json"
    if mf.exists():
        return json.loads(mf.read_text(encoding="utf-8"))
    return {"sources": []}


def load_records(d: Path) -> list[dict]:
    tsv = d / "index.tsv"
    if tsv.exists():
        recs = []
        with tsv.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n")
                if not line:
                    continue
                p = line.split(SEP)
                if len(p) < 5:
                    continue
                recs.append({"f": p[0], "p": p[1], "l": int(p[2]), "s": p[3], "t": p[4]})
        return recs
    recs = []
    rf = d / "index.jsonl"          # 兼容旧索引
    if rf.exists():
        for line in rf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                recs.append(json.loads(line))
    return recs


def load_inv(d: Path) -> dict:
    """倒排表只在字面没命中时才加载（大库能省几百毫秒）。"""
    tf = d / "tokens.json"
    if tf.exists():
        return json.loads(tf.read_text(encoding="utf-8"))
    return {}


def order_of(meta: dict) -> dict:
    return {s["path"]: i for i, s in enumerate(meta.get("sources", []))}


def query_tokens(q: str) -> list[str]:
    t = q.lower()
    out = list(dict.fromkeys(NUM_TOKEN.findall(t)))
    for m in LAT.finditer(t):
        out.append(m.group())
    for m in CJK.finditer(t):
        run = m.group()
        if len(run) <= 8:
            out.append(run)
        for i in range(len(run) - 1):
            out.append(run[i:i + 2])
    return list(dict.fromkeys(out))


def run_ids(recs: list[dict]) -> list[int]:
    """同一文件内「标号相同且连续」的行算一段。返回每行的段号。"""
    ids, cur, prev = [], -1, None
    for r in recs:
        key = (r["p"], r["s"])
        if key != prev:
            cur += 1
            prev = key
        ids.append(cur)
    return ids


def do_section(recs: list[dict], q: str, args) -> int:
    """纯字面命中 → 命中的那个「序号」整段原文照原排版给出（表头写序号与命中行号）。"""
    hits = [r for r in recs if q.lower() in r["t"].lower()]
    if not hits:
        if args.json:
            print(json.dumps({"query": q, "mode": "none", "sections": []}, ensure_ascii=False))
        else:
            print(f"〔未命中〕{q}")
            print("按字面没找到这个字符串；换你自己的关键词再试，我不会替你改词。")
        return 0

    ids = run_ids(recs)
    hitlines: dict[int, set[int]] = {}
    for i, r in enumerate(recs):
        if q.lower() in r["t"].lower():
            hitlines.setdefault(ids[i], set()).add(r["l"])
    order, seen = [], set()
    for i in range(len(recs)):
        k = ids[i]
        if k in hitlines and k not in seen:
            seen.add(k)
            order.append(k)

    truncated = len(order) > args.limit
    shown = order[: args.limit]
    if args.json:
        out = []
        for k in shown:
            lines = [r for i, r in enumerate(recs) if ids[i] == k]
            out.append({"file": lines[0]["f"], "label": lines[0]["s"],
                        "from": lines[0]["l"], "to": lines[-1]["l"],
                        "lines": [{"n": r["l"], "text": r["t"], "hit": r["l"] in hitlines[k]} for r in lines]})
        print(json.dumps({"query": q, "mode": "section", "total": len(order), "sections": out},
                         ensure_ascii=False, indent=1))
        return 0

    total_hits = sum(len(v) for v in hitlines.values())
    print(f"〔命中 {total_hits} 处 · {len(order)} 个序号〕{q}")
    last = None
    for k in shown:
        lines = [r for i, r in enumerate(recs) if ids[i] == k]
        f, lab = lines[0]["f"], lines[0]["s"]
        if f != last:
            print(f)
            last = f
        n = len(lines)
        cap = n if args.all else min(n, args.max_lines)
        hit_nums = "、".join(str(x) for x in sorted(hitlines[k]))
        head = f"§{lab}" if lab else "§(无标号)"
        # 序号顶格 + 命中行号写在表头；正文照原排版整段给出，不加行号前缀
        print(f"{head} · 第{lines[0]['l']}–{lines[-1]['l']}行 · 命中第{hit_nums}行")
        for r in lines[:cap]:
            print(r["t"])
        if cap < n:
            print(f"…（本段还有 {n - cap} 行未显示；加 --all 看整段）")
    if truncated:
        print(f"（共 {len(order)} 个序号，只显示前 {args.limit} 个；加 --limit 调大）")
    return 0


def snippet(text: str, q: str, width: int = 70) -> str:
    s = text.strip()
    if len(s) <= width:
        return s
    pos = s.lower().find(q.lower()) if q else -1
    if pos < 0:
        return s[:width] + "…"
    start = max(0, pos - width // 3)
    end = min(len(s), start + width)
    return ("…" if start else "") + s[start:end] + ("…" if end < len(s) else "")


def main() -> int:
    ap = argparse.ArgumentParser(prog="locate.py")
    ap.add_argument("query", nargs="?", default="")
    ap.add_argument("--dir", default=DEFAULT_DIRNAME)
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--file", default=None, help="只在这些文件名里找（子串匹配，逗号分隔）")
    ap.add_argument("--outline", action="store_true", help="列出全部标号目录")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--raw", action="store_true", help="输出未截断的整行原文")
    ap.add_argument("--section", action="store_true",
                    help="整段模式：纯字面命中后，把命中所在的整个标号段原文打出来（不近似、不换词）")
    ap.add_argument("--all", action="store_true", help="整段模式下不截断长段")
    ap.add_argument("--max-lines", type=int, default=200, help="整段模式单段最多显示多少行（默认 200）")
    ap.add_argument("--cwd", default=None)
    ap.add_argument("--no-sync", action="store_true", help="查询前不校对源文件（默认会校对）")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    d = Path(args.dir)
    if not d.is_absolute():
        d = (Path(args.cwd) if args.cwd else Path.cwd()) / d
    meta = load_meta(d)
    recs: list[dict] = []
    changed: list[str] = []
    if not args.no_sync:                       # 查询前自己看一眼：源文件改了就先重建
        try:
            sys.path.insert(0, str(HERE))
            import build_index as _bi
            recs, changed = _bi.sync_index(d)
        except Exception:
            recs, changed = [], []
    if not recs:
        recs = load_records(d)
    for c in changed:
        print("〔已同步〕" + (c[len("已导入 "):] if c.startswith("已导入 ") else c))
    if not recs:
        print(f"〔无索引〕{d} 里没有数据；先运行 build_index.py add <文件>")
        return 0
    filt = [x.strip().lower() for x in args.file.split(",")] if args.file else None
    if filt:
        recs = [r for r in recs if any(f in r["f"].lower() for f in filt)]
    ordmap = order_of(meta)

    if args.outline:
        seen, lines = set(), []
        for i, r in enumerate(recs):
            if r["s"] and (r["p"], r["s"]) not in seen:
                seen.add((r["p"], r["s"]))
                lines.append((ordmap.get(r["p"], 99), natkey(r["s"]), r["l"], r))
        lines.sort(key=lambda x: (x[0], x[1], x[2]))
        print(f"〔目录〕{len(lines)} 个标号")
        last = None
        for _, _, _, r in lines:
            if r["f"] != last:
                print(r["f"])
                last = r["f"]
            print(f"  §{r['s']} · 第{r['l']}行" + (f" — {r['t'].strip()[:50]}" if r["t"].strip() else ""))
        return 0

    q = args.query.strip()
    if not q:
        print("〔空查询〕给一个词或一句话")
        return 0

    if args.section:
        return do_section(recs, q, args)

    mode = "exact"
    hits = [r for r in recs if q.lower() in r["t"].lower()]
    if not hits:
        mode = "approx"
        inv = load_inv(d)
        toks = query_tokens(q)
        score: dict[int, float] = {}
        for t in toks:
            ids = inv.get(t)
            if not ids:
                continue
            w = 1.0 / (1.0 + len(ids) / 50.0)
            for i in ids:
                score[i] = score.get(i, 0.0) + w
        top = sorted(score.items(), key=lambda kv: -kv[1])[: args.limit]
        hits = [recs[i] for i, _ in top]

    if not hits:
        if args.json:
            print(json.dumps({"query": q, "mode": "none", "hits": []}, ensure_ascii=False))
        else:
            print(f"〔未命中〕{q}")
            print("库里没有这个词；可换更短的词、去掉限定词，或先导入对应文件。")
        return 0

    hits.sort(key=lambda r: (ordmap.get(r["p"], 99), natkey(r["s"]), r["l"]))
    if mode == "exact":
        hits = hits[: args.limit]
    else:
        hits.sort(key=lambda r: (ordmap.get(r["p"], 99), natkey(r["s"]), r["l"]))

    if args.json:
        print(json.dumps({"query": q, "mode": mode, "total": len(hits),
                          "hits": [{"file": r["f"], "label": r["s"], "line": r["l"], "text": r["t"]} for r in hits]},
                         ensure_ascii=False, indent=1))
        return 0

    tag = "命中" if mode == "exact" else "近似"
    print(f"〔{tag} {len(hits)}〕{q}")
    last = None
    for r in hits:
        if r["f"] != last:
            print(f"{r['f']}")
            last = r["f"]
        lab = f"§{r['s']}" if r["s"] else "§(无标号)"
        is_title = bool(r["s"]) and r["t"].strip().startswith(r["s"]) and len(r["t"].strip()) <= 60
        body = r["t"] if args.raw else snippet(r["t"], q)
        print(f"  {lab} · 第{r['l']}行{' ※标题行' if is_title else ''} — {body}")
    if mode == "approx":
        print("（字面没命中，以上是词条近似；换更短的关键词更准）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
