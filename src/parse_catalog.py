# -*- coding: utf-8 -*-
"""医保目录 2023 西药条目解析 + 集采品种 ↔ 目录条目匹配（主数据管理/名称规范化）。

- 集采 product_name -> 通用名（去"注射用"与剂型后缀）-> 核心名（去盐基前缀）
- 目录条目 -> 归一化（去 ★、括号别名）
- 匹配：核心名 与 目录通用名 精确/互相包含；未匹配品种本身即核验结果
输出：catalog_subset.csv（真实目录条目子集）、drug_match.csv（品种匹配台账）
"""
import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUPPLY = ROOT / "data" / "processed" / "supply_batch9.csv"
CATALOG_TXT = ROOT / "data" / "raw" / "catalog_2023.txt"
OUT_SUB = ROOT / "data" / "processed" / "catalog_subset.csv"
OUT_MATCH = ROOT / "data" / "processed" / "drug_match.csv"

SUFFIXES = ["雾化吸入溶液", "肠溶干混悬剂", "乳状注射液", "肠溶缓释片", "口服混悬剂",
            "干混悬剂", "口服溶液", "分散片", "咀嚼片", "口崩片", "肠溶片", "缓释片",
            "滴眼液", "注射液", "注射剂", "颗粒", "胶囊", "片"]
SALTS = ["盐酸", "硫酸", "磷酸", "醋酸", "枸橼酸", "酒石酸", "琥珀酸", "马来酸", "甲磺酸"]


def generic_of(product_name: str) -> str:
    n = product_name.strip()
    n = re.sub(r"[（(][ⅠⅡⅢⅣ0-9]*[)）]$", "", n)  # 先去尾部（Ⅱ）等
    if n.startswith("注射用"):
        n = n[3:]
    for s in SUFFIXES:
        if n.endswith(s):
            n = n[: -len(s)]
            break
    return n


def core_of(generic: str) -> str:
    n = re.sub(r"[（(].*?[)）]", "", generic)  # 去（Ⅱ）等
    for s in SALTS:
        # 仅当剥掉盐基后剩余 >=2 字才视为盐基前缀；
        # 否则"硫酸镁"会被误剥成单字"镁"（硫酸镁本身即通用名）。
        if n.startswith(s) and len(n) - len(s) >= 2:
            n = n[len(s):]
            break
    return n


def parse_catalog():
    t = CATALOG_TXT.read_text(encoding="utf-8")
    t = re.sub(r"<!-- Page \d+ -->", " ", t)
    t = re.sub(r"\s+", " ", t)
    pat = re.compile(
        r"(★\(\d+\)|\d{1,4})\s+(\S+?)\s+"
        r"([一-鿿]{2,8}?(?:剂型|剂|片|丸|散|膏|液|霜|雾|油|栓))"
        r"\s*(限[^甲乙]{0,90}?)?\s*(甲|乙)(?=\s|$)"
    )
    rows = []
    for no, name, form, note, cat in pat.findall(t):
        norm = re.sub(r"[（(].*?[)）]", "", name)  # 去括号别名
        rows.append(dict(catalog_no=no, product_name=name, norm_name=norm,
                         dosage_form=form, category=cat, note=(note or "").strip(),
                         section="西药", catalog_version="2023"))
    rows.extend(SUPPLEMENT)
    return rows


# 人工核对补录（依据目录 2023 原文）：自动正则覆盖不到的格式变体——
# 限制条件过长 / 药名自带剂型 / 类别单元格空缺。均为真实条目。
SUPPLEMENT = [
    dict(catalog_no="914", product_name="来那度胺", norm_name="来那度胺",
         dosage_form="口服常释剂型", category="乙", section="西药", catalog_version="2023",
         note="限：1.与地塞米松合用治疗不适合移植的多发性骨髓瘤；2.与地塞米松合用治疗曾接受至少一种疗法者；3.与利妥昔单抗合用治疗既往接受过治疗的滤泡性淋巴瘤(1-3a级)"),
    dict(catalog_no="333", product_name="伊伐布雷定", norm_name="伊伐布雷定",
         dosage_form="口服常释剂型", category="乙", section="西药", catalog_version="2023",
         note="类别依官方目录补全（PDF 该单元格空缺）"),
    dict(catalog_no="1116", product_name="托莫西汀", norm_name="托莫西汀",
         dosage_form="口服常释剂型", category="乙", section="西药", catalog_version="2023",
         note="类别依官方目录补全（PDF 该单元格空缺）"),
    dict(catalog_no="699", product_name="注射用磷酸特地唑胺", norm_name="注射用磷酸特地唑胺",
         dosage_form="注射剂", category="乙", section="西药", catalog_version="2023",
         note="限急性细菌性皮肤及皮肤软组织感染"),
    dict(catalog_no="678", product_name="西他沙星片", norm_name="西他沙星片",
         dosage_form="口服常释剂型", category="乙", section="西药", catalog_version="2023",
         note="限二线用药"),
]


def main():
    catalog = parse_catalog()
    supply = list(csv.DictReader(SUPPLY.open(encoding="utf-8-sig")))
    # 集采品种（通用名去重）
    kinds = {}
    for r in supply:
        g = generic_of(r["product_name"])
        kinds.setdefault(g, core_of(g))
    print(f"集采品种数={len(kinds)}  目录西药条目={len(catalog)}")

    matched_entries, match_rows = {}, []
    for generic, core in sorted(kinds.items()):
        hits = [c for c in catalog
                if core and (c["norm_name"] == core
                             or core in c["norm_name"] or c["norm_name"] in core)]
        # 防止"XX钠"误配过宽：要求核心名长度>=2
        for h in hits:
            matched_entries[(h["catalog_no"], h["product_name"], h["dosage_form"])] = h
        match_rows.append(dict(generic_name=generic, core_name=core,
                               match_count=len(hits),
                               catalog_nos=";".join(h["catalog_no"] for h in hits),
                               matched="是" if hits else "否"))
    with OUT_SUB.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["catalog_version", "catalog_no", "product_name", "norm_name",
                                          "dosage_form", "category", "section", "note"])
        w.writeheader()
        for h in matched_entries.values():
            w.writerow({k: h[k] for k in w.fieldnames})
    with OUT_MATCH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["generic_name", "core_name", "match_count",
                                          "catalog_nos", "matched"])
        w.writeheader()
        w.writerows(match_rows)

    print(f"匹配到目录条目={len(matched_entries)}")
    print("\n== 未匹配品种（集采有、目录无 = 核验点） ==")
    for r in match_rows:
        if r["matched"] == "否":
            print(" ", r["generic_name"], "/", r["core_name"])
    print("\n== 匹配抽样 ==")
    for r in match_rows:
        if r["core_name"] in ("吡拉西坦", "帕罗西汀", "阿立哌唑", "阿托品", "雷贝拉唑钠", "伊伐布雷定"):
            print(" ", r)
    print(f"\n-> {OUT_SUB}\n-> {OUT_MATCH}")


if __name__ == "__main__":
    main()
