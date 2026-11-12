# -*- coding: utf-8 -*-
"""生成 locator 的测试样例（docx/xlsx/pptx/txt），PDF 由 make_pdf.ps1 从 docx 转出。"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)

DOC_LINES = [
    "第一章 总则",
    "1.1 适用范围",
    "本手册适用于四象限整流装置的现场安装与维护。",
    "1.2 术语",
    "整流桥 —— 将交流电变为直流电的部件。",
    "第二章 安装",
    "2.1 开箱检查",
    "开箱后核对装箱清单，缺件立即上报。",
    "2.3.1 整机安装步骤",
    "整机安装前请断电，并悬挂警示牌。",
    "整机安装完成后测量绝缘电阻，阻值不低于 2 MΩ。",
    "2.3.2 接线",
    "接线端子扭矩为 2.5 N·m，不得超扭矩紧固。",
    "附录A.1 故障码",
    "E045 表示直流母线过压，需检查整流桥。",
    "表3 备件清单",
    "表3 内列出了常用备件。",
]


def make_docx() -> Path:
    import docx

    d = docx.Document()
    for line in DOC_LINES:
        d.add_paragraph(line)
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "名称"
    t.cell(0, 1).text = "规格"
    t.cell(1, 0).text = "整流桥"
    t.cell(1, 1).text = "KBPC3510"
    p = DATA / "手册A.docx"
    d.save(str(p))
    return p


def make_xlsx() -> Path:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "备件表"
    ws.append(["序号", "名称", "规格"])
    ws.append([1, "整流桥", "KBPC3510"])
    ws.append([2, "散热器", "150x100"])
    ws2 = wb.create_sheet("扭矩表")
    ws2.append(["部位", "扭矩"])
    ws2.append(["主端子", "2.5 N·m"])
    p = DATA / "备件表.xlsx"
    wb.save(str(p))
    wb.close()
    return p


def make_pptx() -> Path:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[5])
    s1.shapes.title.text = "3 四象限整流原理"
    tb = s1.shapes.add_textbox(Inches(1), Inches(2), Inches(6), Inches(1))
    tb.text_frame.text = "四象限整流可实现能量双向流动。"
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "4 维护要点"
    p = DATA / "培训讲义.pptx"
    prs.save(str(p))
    return p


def make_txt() -> Path:
    p = DATA / "笔记.txt"
    p.write_text(
        "[1] 现场照片存档要求\n"
        "所有整流桥照片按日期归档。\n"
        "[2] 备件盘点\n"
        "每月盘点一次散热器库存。\n",
        encoding="utf-8",
    )
    return p


def make_rtf() -> Path:
    """RTF 样例：中文同时用 \\'hh(GBK) 与 \\uN 两种写法，验解码；含表头/控制组/忽略组。"""
    def esc(s: str) -> str:
        out = []
        for ch in s:
            if ord(ch) < 128:
                out.append("\\" + ch if ch in "\\{}" else ch)
            else:
                out.append("".join("\\'%02x" % b for b in ch.encode("gbk")))
        return "".join(out)

    body = [
        "3.1 备件台账",
        "台账需登记整流桥的入库日期与数量。",
        "",                                        # 源文件里的空行：输出不该照抄出来
        "4.1 归档",
        "所有整流桥照片按日期归档。",
    ]
    tail = "\\u26696?\\u20363?\\par\n"          # “案例”走 \uN 写法
    rtf = ("{\\rtf1\\ansi\\ansicpg936\\deff0"
           "{\\fonttbl{\\f0\\fnil\\fcharset134 " + esc("宋体") + ";}}"
           "{\\colortbl;\\red0\\green0\\blue0;}"
           "{\\*\\generator locator-test;}"       # 忽略组：内容不该出现
           "\\pard " + "\\par\n".join(esc(x) for x in body) + "\\par\n" + tail + "}")
    p = DATA / "笔记B.rtf"
    p.write_bytes(rtf.encode("ascii"))
    return p


if __name__ == "__main__":
    made = [make_docx(), make_xlsx(), make_pptx(), make_txt(), make_rtf()]
    for p in made:
        print(p)
