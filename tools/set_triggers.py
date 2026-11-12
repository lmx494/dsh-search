# -*- coding: utf-8 -*-
"""locator · 口令设置器

口令 = 触发 locator 的自然语言前缀。它存在技能根目录的 triggers.json 里，
本脚本负责改它，并把「契约块」同步进 AGENTS.md（用 <!-- locator:begin/end --> 标记，
重复运行是幂等替换，不动 AGENTS.md 里别的内容）。

用法:
    python set_triggers.py show                                  # 看当前口令
    python set_triggers.py add "添加文件到数据库" "添加到数据库"    # 改导入口令（可多个）
    python set_triggers.py search "搜索" "找"                     # 改查询口令（可多个）
    python set_triggers.py sync [--scope workspace|global] [--path <AGENTS.md>] [--dry]

add / search 改完默认会把契约块同步到「当前目录的 AGENTS.md」；加 --no-sync 只改配置。
--scope global 写 $DSH_HOME/AGENTS.md（所有工作区都认）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
CFG = SKILL / "triggers.json"
BEGIN = "<!-- locator:begin"
END = "<!-- locator:end -->"
DEFAULT = {"add": ["添加文件到数据库", "添加到数据库"], "search": ["搜索"]}


def load() -> dict:
    raw = {}
    if CFG.exists():
        try:
            raw = json.loads(CFG.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
    cfg = {}
    for k in ("add", "search"):
        v = raw.get(k, DEFAULT[k])
        if isinstance(v, str):
            v = [v]
        v = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
        cfg[k] = v or list(DEFAULT[k])
    return cfg


def save(cfg: dict) -> None:
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def block(cfg: dict) -> str:
    py = sys.executable
    adds = " / ".join(f"`{x}`" for x in cfg["add"])
    search = " / ".join(f"`{x}`" for x in cfg["search"])
    return f"""{BEGIN} 由 tools/set_triggers.py 生成，改口令请跑那个脚本，不要手改这一段 -->
## locator 口令约定（只认这几句）

locator 设了 `disable-model-invocation: true`（不在技能目录，不许自动调用）。命中下面口令时**只跑一条命令，然后把命令输出原样贴回，不加一个字**——不读被索引的文件、不看 `raw\\`、不跑 `--outline`/`status`/验收、不解释、不建议、不总结。

```powershell
$L="{SKILL}"; $P="{py}"
& $P "$L\\tools\\build_index.py" add "<路径>"        # 口令：{adds} <路径/附件>
& $P "$L\\tools\\locate.py" "<原样字符串>" --section  # 口令：{search}<字符串>
```

- **导入 = 一条 `add`；查询 = 一条 `locate`。多一个工具调用就是违规。**
- `{cfg["search"][0]}` 后面那串字符原样传进 `--section`：不解释、不截断、不补词、不近似。
- 只有命令自己报错（`失败 …`）才回那一行错误。
- 例外：用户明说"上网搜 / 搜互联网 / 查资料"时不走本地库。
- 其余任何消息都不要用 locator，也不要提它。细则见 `{SKILL}\\SKILL.md`，只在报错或要改行为时才读。
- 想换口令：`{py} "{HERE}\\set_triggers.py" show`，手动强制启用：`/{SKILL.name}`。
{END}
"""


def target_path(scope: str, path: str | None) -> Path:
    if path:
        return Path(path)
    if scope == "global":
        return Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh")) / "AGENTS.md"
    return Path.cwd() / "AGENTS.md"


def sync(scope: str, path: str | None, dry: bool = False) -> str:
    p = target_path(scope, path)
    new = block(load())
    if p.exists():
        text = p.read_text(encoding="utf-8")
        pat = re.compile(r"<!-- locator:begin.*?<!-- locator:end -->\n?", re.S)
        if pat.search(text):
            # 用函数式替换：契约块里有 Windows 路径（\U \d 之类），当替换串会被 re 当成转义报错
            text = pat.sub(lambda _m: new, text)
        else:
            text = text.rstrip("\n") + "\n\n" + new
    else:
        text = new
    if dry:
        print(text)
        return str(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return str(p)


def main() -> int:
    ap = argparse.ArgumentParser(prog="set_triggers.py")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("show", help="看当前口令")
    s.set_defaults(f="show")

    for name, helptext in (("add", "改导入口令"), ("search", "改查询口令")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("words", nargs="+", help="一个或多个触发前缀")
        p.add_argument("--no-sync", action="store_true", help="只改配置，不动 AGENTS.md")
        p.add_argument("--scope", choices=["workspace", "global"], default="workspace")
        p.add_argument("--path", default=None)
        p.set_defaults(f=name)

    y = sub.add_parser("sync", help="只同步契约块到 AGENTS.md")
    y.add_argument("--scope", choices=["workspace", "global"], default="workspace")
    y.add_argument("--path", default=None)
    y.add_argument("--dry", action="store_true")
    y.set_defaults(f="sync")

    args = ap.parse_args()

    if args.f == "show":
        cfg = load()
        print("导入口令: " + " / ".join(cfg["add"]))
        print("查询口令: " + " / ".join(cfg["search"]))
        print(f"配置: {CFG}")
        print(f"技能: {SKILL}")
        return 0

    if args.f == "sync":
        where = sync(args.scope, args.path, args.dry)
        if not args.dry:
            print(f"已同步口令契约块 → {where}")
        return 0

    cfg = load()
    cfg[args.f] = list(args.words)
    save(cfg)
    label = "导入" if args.f == "add" else "查询"
    print(f"已改{label}口令: " + " / ".join(cfg[args.f]))
    if not args.no_sync:
        print(f"已同步 → {sync(args.scope, args.path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
