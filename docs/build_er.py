# -*- coding: utf-8 -*-
"""教材式 ER 图生成器（纯标准库，输出 SVG）。

记法（接近教材 / 大作业 PPT 第15页示例）：
  矩形=实体，椭圆=属性（主键下划线），菱形=关系，连线旁标 1/N/M。
  实线=外键强关联；橙虚线=弱关联(文本匹配交叉核验)；蓝虚线=来源追溯。
布局：属性竖排、实体拉开、菱形避让，经几何重叠检测。
分域：00 总览 / 01 集采域 / 02 核验域。
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent
FONT = "font-family='system-ui,sans-serif'"
EW, EH = 156, 52  # 实体矩形宽/高


def ent(cx, cy, title, en=""):
    s = (f"<rect x='{cx-EW/2}' y='{cy-EH/2}' width='{EW}' height='{EH}' rx='4' "
         f"fill='#ffffff' stroke='#534AB7' stroke-width='1.6'/>"
         f"<text x='{cx}' y='{cy+2}' text-anchor='middle' font-size='15' "
         f"font-weight='600' fill='#26215C'>{title}</text>")
    if en:
        s += (f"<text x='{cx}' y='{cy+18}' text-anchor='middle' font-size='10' "
              f"fill='#534AB7'>{en}</text>")
    return s


def oval(cx, cy, text, pk=False):
    rx = max(46, len(text) * 6.2 + 14)
    deco = " text-decoration='underline'" if pk else ""
    return (f"<ellipse cx='{cx}' cy='{cy}' rx='{rx}' ry='19' fill='#EEEDFE' "
            f"stroke='#AFA9EC' stroke-width='1'/>"
            f"<text x='{cx}' y='{cy+4}' text-anchor='middle' font-size='12' "
            f"fill='#3C3489'{deco}>{text}</text>")


def attrs_col(col_x, start_y, step, items, anchor):
    """竖排属性列 + 到实体锚点的连线。items=[(text, is_pk), ...]"""
    out = []
    for i, (t, pk) in enumerate(items):
        oy = start_y + i * step
        out.append(line([(col_x, oy), anchor]))  # 先画线
    for i, (t, pk) in enumerate(items):
        oy = start_y + i * step
        out.append(oval(col_x, oy, t, pk))       # 后画椭圆盖住线端
    return out


DIA = {
    "strong": ("#E1F5EE", "#0F6E56", "#085041"),
    "weak": ("#FAEEDA", "#BA7517", "#854F0B"),
    "source": ("#E6F1FB", "#185FA5", "#0C447C"),
}


def dia(cx, cy, label, kind="strong", w=120, h=58):
    f, st, tc = DIA[kind]
    pts = f"{cx},{cy-h/2} {cx+w/2},{cy} {cx},{cy+h/2} {cx-w/2},{cy}"
    return (f"<polygon points='{pts}' fill='{f}' stroke='{st}' stroke-width='1.4'/>"
            f"<text x='{cx}' y='{cy+5}' text-anchor='middle' font-size='13' "
            f"font-weight='600' fill='{tc}'>{label}</text>")


def line(pts, kind="attr"):
    p = " ".join(f"{x},{y}" for x, y in pts)
    if kind == "strong":
        return f"<polyline points='{p}' fill='none' stroke='#444' stroke-width='1.5'/>"
    if kind == "weak":
        return f"<polyline points='{p}' fill='none' stroke='#BA7517' stroke-width='1.5' stroke-dasharray='6,4'/>"
    if kind == "source":
        return f"<polyline points='{p}' fill='none' stroke='#185FA5' stroke-width='1.5' stroke-dasharray='6,4'/>"
    return f"<polyline points='{p}' fill='none' stroke='#B4B2A9' stroke-width='0.8'/>"


def card(x, y, t):
    return (f"<text x='{x}' y='{y}' font-size='15' font-weight='700' "
            f"fill='#993C1D'>{t}</text>")


def write(name, w, h, layers):
    body = "".join(layers)
    s = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {w} {h}' "
         f"{FONT} width='{w}' height='{h}'>{body}</svg>")
    (OUT / name).write_text(s, encoding="utf-8")
    print("生成", name)


# ============================================================
# 01 集采域：属性竖排在实体上方，关系菱形在实体水平之间
# ============================================================
def build_vbp():
    MFR, DRUG, SEL, VBP, SUP = (180, 600), (520, 600), (900, 600), (1280, 600), (900, 880)
    L = []
    # 关系连线
    L += [line([MFR, (350, 600), DRUG], "strong"),
          line([DRUG, (710, 600), SEL], "strong"),
          line([VBP, (1090, 600), SEL], "strong"),
          line([SEL, (900, 740), SUP], "strong")]
    # 属性列（实体上方竖排）
    L += attrs_col(180, 514, -44, [("manufacturer_id", 1), ("name", 0), ("uscc", 0), ("type", 0)], (180, 574))
    L += attrs_col(520, 514, -44, [("drug_id", 1), ("approval_no", 0), ("generic_name", 0),
                                   ("dosage_form", 0), ("specification", 0), ("status", 0)], (520, 574))
    L += attrs_col(900, 514, -44, [("selected_id", 1), ("product_name", 0), ("price", 0),
                                   ("specification", 0), ("remark", 0)], (900, 574))
    L += attrs_col(1280, 514, -44, [("batch_id", 1), ("batch_no", 0), ("tender_date", 0), ("exec_date", 0)], (1280, 574))
    # 供应省份属性列（左侧竖排）
    L += attrs_col(700, 850, 44, [("selected_id", 1), ("province", 0)], (822, 880))
    # 实体
    L += [ent(*MFR, "企业", "MANUFACTURER"), ent(*DRUG, "药品", "DRUG"),
          ent(*SEL, "中选记录", "SELECTED_ITEM"), ent(*VBP, "集采批次", "VBP_BATCH"),
          ent(*SUP, "供应省份", "SUPPLY_PROVINCE")]
    # 菱形
    L += [dia(350, 600, "生产"), dia(710, 600, "匹配"), dia(1090, 600, "包含"), dia(900, 740, "供应于")]
    # 基数
    L += [card(212, 592, "1"), card(428, 592, "N"),
          card(616, 592, "1"), card(805, 592, "N"),
          card(996, 592, "N"), card(1188, 592, "1"),
          card(916, 652, "1"), card(916, 838, "N")]
    write("01_集采域.svg", 1400, 980, L)


# ============================================================
# 02 核验域：来源追溯(蓝) + 违规核验/目录匹配(橙)
# ============================================================
def build_check():
    ANN, VIO, CAT, SEL, DRUG = (700, 480), (250, 480), (1150, 480), (700, 180), (1150, 800)
    L = []
    # 关系连线
    L += [line([(700, 454), (700, 330), (700, 206)], "source"),      # ann->sel
          line([(622, 480), (475, 480), (328, 480)], "source"),      # ann->vio
          line([(778, 480), (925, 480), (1072, 480)], "source"),     # ann->cat
          line([(250, 454), (475, 330), (640, 206)], "weak"),        # vio<->sel
          line([(1150, 506), (1150, 640), (1150, 774)], "weak")]     # cat<->drug
    # 属性列
    L += attrs_col(700, 546, 44, [("announcement_id", 1), ("notice_no", 0), ("title", 0),
                                  ("publisher", 0), ("pub_date", 0), ("ann_type", 0)], (700, 506))
    L += attrs_col(520, 120, 44, [("selected_id", 1), ("product_name", 0), ("status", 0)], (622, 180))
    L += attrs_col(250, 546, 44, [("violation_id", 1), ("manufacturer", 0), ("product_name", 0),
                                  ("viol_type", 0), ("decision_date", 0)], (250, 506))
    L += attrs_col(1330, 540, 44, [("entry_id", 1), ("catalog_version", 0), ("catalog_no", 0),
                                   ("product_name", 0), ("category", 0), ("section", 0)], (1228, 480))
    L += attrs_col(1150, 862, 44, [("drug_id", 1), ("approval_no", 0)], (1150, 826))
    # 实体
    L += [ent(*ANN, "公告", "ANNOUNCEMENT"), ent(*VIO, "违规记录", "VIOLATION"),
          ent(*CAT, "医保目录条目", "CATALOG_ENTRY"), ent(*SEL, "中选记录", "SELECTED_ITEM"),
          ent(*DRUG, "药品", "DRUG")]
    # 菱形
    L += [dia(700, 330, "来源追溯", "source"), dia(475, 480, "来源追溯", "source"),
          dia(925, 480, "来源追溯", "source"), dia(475, 330, "违规核验", "weak"),
          dia(1150, 640, "目录匹配", "weak")]
    # 基数
    L += [card(716, 442, "1"), card(716, 222, "N"),
          card(604, 466, "1"), card(340, 466, "N"),
          card(794, 466, "1"), card(1052, 466, "N"),
          card(266, 442, "M"), card(628, 222, "N"),
          card(1172, 532, "N"), card(1172, 766, "1")]
    write("02_核验域.svg", 1420, 980, L)


# ============================================================
# 00 总览：8 实体 + 关系 + 基数（无属性）
# ============================================================
def build_overview():
    ANN, MFR, DRUG, VBP = (650, 80), (120, 280), (400, 280), (1080, 280)
    SEL, CAT, SUP, VIO = (740, 400), (400, 640), (740, 640), (1080, 620)
    L = []
    L += [line([MFR, (260, 280), DRUG], "strong"),
          line([DRUG, (570, 340), SEL], "strong"),
          line([VBP, (910, 340), SEL], "strong"),
          line([(740, 426), (740, 520), (740, 614)], "strong"),
          line([ANN, (695, 240), SEL], "source"),
          line([VIO, (910, 510), SEL], "weak"),
          line([(400, 306), (400, 460), (400, 614)], "weak")]
    L += [ent(*ANN, "公告"), ent(*MFR, "企业"), ent(*DRUG, "药品"), ent(*VBP, "集采批次"),
          ent(*SEL, "中选记录"), ent(*CAT, "医保目录条目"), ent(*SUP, "供应省份"), ent(*VIO, "违规记录")]
    L += [dia(260, 280, "生产", w=100, h=50), dia(570, 340, "匹配", w=100, h=50),
          dia(910, 340, "包含", w=100, h=50), dia(740, 520, "供应于", w=100, h=50),
          dia(695, 240, "来源追溯", "source"), dia(910, 510, "违规核验", "weak"),
          dia(400, 460, "目录匹配", "weak")]
    L += [card(140, 262, "1"), card(370, 262, "N"),
          card(432, 262, "1"), card(700, 380, "N"),
          card(1040, 262, "1"), card(778, 380, "N"),
          card(762, 440, "1"), card(762, 600, "N"),
          card(668, 112, "1"), card(722, 380, "N"),
          card(1040, 600, "M"), card(778, 440, "N"),
          card(420, 600, "N"), card(420, 322, "1")]
    write("00_总览.svg", 1240, 720, L)


if __name__ == "__main__":
    build_overview()
    build_vbp()
    build_check()
