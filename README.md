# locator · 文件定位（字面检索）

丢进去一堆资料（Word / Excel / PPT / PDF / RTF / 文本），之后每搜一个字符串，直接回：**哪个文件 · 哪个序号 · 那个序号的整段原文**。

- **纯字面匹配**：不分词、不近似、不同义词、不替你换词。搜不到就回搜不到。
- **给整段原文**：命中哪个序号，就把那个序号从头到尾照原排版贴出来（空行照留、不加行号前缀、序号顶格）。
- **标号取自文件本身**：`1.2.3` / `第3章` / `附录A.1` / `表3` / `[3]` / 工作表名 / 幻灯片号；识别不到就显示 `§(无标号)`，不重新编号。
- **查询前自动校对**：源文件改过，直接搜就是新内容，不用重新导入。

## 安装

它是 DSH（DeepSeek Harness）技能，装到技能目录即可用（`skill` 目录下每个 `<名字>/SKILL.md` 是一个技能）：

```powershell
git clone https://github.com/lmx494/dsh-search.git "$env:USERPROFILE\.dsh\skills\locator"
```

已有文件也可以直接跑 `pwsh -File install.ps1`。

不用 DSH 也能用——`tools\` 下两个脚本是独立的命令行程序。

> 本技能的 frontmatter 里带 `disable-model-invocation: true`：**模型不会自己调用它**，只有你明确开口（或手动 `/locator`）才启用，避免它在无关话题上乱搜。想让模型自己判断什么时候用，删掉 `SKILL.md` 里那一行即可。

## 用法

```powershell
$L="$env:USERPROFILE\.dsh\skills\locator"; $P="python"   # 或你的 python.exe 绝对路径

# 建库（文件 / 目录 / 通配符，可以给多个）
& $P "$L\tools\build_index.py" add "D:\资料" "D:\手册.docx"

# 搜索：字面命中 → 该序号整段原文
& $P "$L\tools\locate.py" "整机安装" --section
```

| 命令 | 作用 |
|---|---|
| `build_index.py status` | 已入库清单 |
| `locate.py --outline` | 全部序号目录 |
| `build_index.py add <路径> --force` | 强制重建该文件 |
| `locate.py "<词>" --section --all` | 长段不截断 |
| `locate.py "<词>" --no-sync` | 查询前不校对源文件 |
| `build_index.py remove <路径>` / `clear` | 移除某个 / 清空 |
| `tools/set_triggers.py` | 看 / 改自然语言口令，并同步进 AGENTS.md |

索引默认落在**当前目录**的 `.locator\`，用 `--dir` 换地方。

## 口令（自然语言触发词，可以随便改）

装了技能之后，你不用记命令行，直接用大白话触发。**现在的口令是这两句**：

| 你说 | 它做什么 |
|---|---|
| `添加文件到数据库 <文件或目录>`（也认 `添加到数据库`） | 导入到库 |
| `搜索<一串字符>`（例：`搜索四象限整流`） | 按字面查库，回「文件 · 序号 · 该序号整段原文」 |

口令存在技能根目录的 **`triggers.json`** 里，改口令是第一条命令的事：

```powershell
$L="$env:USERPROFILE\.dsh\skills\locator"; $P="python"

& $P "$L\tools\set_triggers.py" show                  # 看当前口令
& $P "$L\tools\set_triggers.py" add "喂资料" "入库"    # 改导入口令（可给多个）
& $P "$L\tools\set_triggers.py" search "找" "查一下"   # 改查询口令（可给多个）
```

改完它会自动把一段**契约块**写进 `AGENTS.md`（默认当前工作目录那份；`--scope global` 写 `$DSH_HOME\AGENTS.md`，所有工作区都认）。契约块用 `<!-- locator:begin -->` / `<!-- locator:end -->` 包着，**重复运行是幂等替换，不会叠加、也不会动你 AGENTS.md 里别的内容**；想自己手写这段契约，直接改两个标记之间的文字也行。

> 模型是靠 AGENTS.md 里那段契约认口令的。**改了 `triggers.json` 不同步，模型就不认新口令**——`add` / `search` 子命令默认会自动同步，只改配置加 `--no-sync`。

## 支持格式

| 类型 | 方式 | 状态 |
|---|---|---|
| txt / md / csv / 代码 | 直读，编码自动探测 | 可用 |
| docx / docm | python-docx（段落 + 表格按原序） | 可用 |
| xlsx / xlsm | openpyxl（带 `行N`、工作表名） | 可用 |
| pptx / pptm | python-pptx（带 `[幻灯片 N]`、表格） | 可用 |
| pdf | `tools/pdf_text.py`（纯标准库：Flate / ObjStm / ToUnicode） | 可用；扫描件、加密件报失败 |
| doc / xls / ppt / odt / ods / odp | 先经 LibreOffice Kit 转成新格式再抽取 | 需本机有 Kit |
| rtf | 内置解析（去控制字组、`\'hh` 按 `\ansicpg` 解码、认 `\uN`） | 可用 |
| 无扩展名附件 | 按文件头认出类型，老格式自动补扩展名再转 | 可用 |

依赖：Python 3.10+；`python-docx`、`openpyxl`、`python-pptx` 只有那三种格式才需要。老格式需要 LibreOffice Kit（DSH 自带；也可用环境变量 `DSH_LO_KIT_CLI` / `DSH_LO_KIT_NODE` 指定）。

## 验收

```powershell
python tests/acceptance.py      # 全过返回 0
python tools/tests/test_pdf_text.py   # PDF 解析器单测
```

真实文件用例放在 `tests/real_pdfs.txt` / `tests/real_legacy.txt`（每行一个路径，`#` 注释；文件不存在就跳过该段）。这两个文件在 `.gitignore` 里，仓库里只提供 `.example`。

## 边界

- 扫描件 / 加密 PDF 没有文字层 → 报失败，不做 OCR。
- 没有编号的 PDF / 文本，整篇算一个"序号"；单段默认只显示前 200 行（`--all` 看全）。
- 是否改过看的是「文件大小 + 修改时间（秒）」：同一秒内改完、大小又没变会漏掉 → `add <路径> --force` 强推。
- 源文件改名 / 移动 = 新路径，会多一条记录；源文件删了，库里已抽出的内容还在。
- 索引是**文字副本**（`.locator\raw\`），不是链接；原文件不参与查询。

## License

MIT，见 [LICENSE](LICENSE)。
