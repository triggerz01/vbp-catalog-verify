# -*- coding: utf-8 -*-
"""第九批集采供应清单：文本快照 -> 结构化 CSV。

数据清洗要点（报告"数据清洗"加分点）：
1. PDF 长单元格跨行 -> 先合并全文，按"备注"结尾词切分记录，序号递增校验防错切；
2. 换行断字（"公 司"）-> 中文间伪空格清除；
3. 化学式下标（C₁₇H₁₉）-> 归一化为普通字符；
4. 剂型用领域词表定位，药名/规格/包装描述依次切分；
5. 每条带 confidence，低置信记录进入人工复核清单。
"""
import csv
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "supply_batch9.txt"
OUT = ROOT / "data" / "processed" / "supply_batch9.csv"

DOSAGE_FORMS = [
    "口服溶液剂", "口服混悬剂", "吸入制剂", "眼用制剂", "颗粒剂",
    "胶囊剂", "注射剂", "干混悬剂", "口服溶液", "注射液", "片剂",
]
PACK_MARKERS = [
    "药品包装", "口服固体", "口服液体", "内包装", "中硼硅", "中性硼硅",
    "低密度", "高密度", "铝塑", "双铝", "三层", "四层", "五层", "包装",
    "采用", "本品", "瓶装", "纸/", "纸铝", "聚酯", "聚酰胺", "聚氯乙烯",
    "聚丙烯", "聚三氟", "中性", "附带有",
]
SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")


def clean(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).translate(SUB)
    # 中文之间的空格是 PDF 换行造成的伪空格，循环清除
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"(?<=[一-鿿])[ ]+(?=[一-鿿])", "", s)
    return re.sub(r"\s+", " ", s).strip(" 。;")


def split_records(text: str):
    text = re.sub(r"<!-- Page \d+ -->", " ", text)
    text = text.replace("附件1", " ")
    text = text.replace("第九批国家组织药品集采中选药品供应清单", " ")
    text = re.sub(r"序\s*号\s*药品名称.*?备注", " ", text, flags=re.S)
    text = re.sub(r"\s+", " ", text)
    pat = re.compile(r"(\d{1,3})\s+(.+?)(视同主供的\s*中选药品|中选药品|备供药品)")
    records, problems = [], []
    for m in pat.finditer(text):
        seq, body, remark = int(m.group(1)), m.group(2).strip(), m.group(3)
        records.append((seq, body, re.sub(r"\s+", "", remark)))
    for i, (seq, _, _) in enumerate(records, start=1):
        if seq != i:
            problems.append(f"序号断裂：第{i}条匹配到序号{seq}")
    return records, problems


def split_manufacturers(mfr: str):
    """企业字段：先清断字，再在"公司/Ltd."边界恢复多企业分隔。"""
    s = clean(mfr)
    s = re.sub(r"(公司|Ltd\.)\s*", r"\1 ", s).strip()
    parts = s.split(" ")
    return s, parts[0]


def parse_body(seq: int, body: str, remark: str):
    m = re.match(
        r"^(?P<head>.*?)(?P<qty>\d+)\s+(?P<unit>盒|瓶|支|袋)\s+(?P<mfr>.*?)\s*(?P<price>\d+(?:\.\d+)?)$",
        body,
    )
    if not m:
        return dict(seq=seq, remark=remark, confidence="fail", raw=body)
    head, qty, unit = m.group("head"), m.group("qty"), m.group("unit")
    mfr_raw, mfr_main = split_manufacturers(m.group("mfr"))
    price = m.group("price")

    h = clean(head)
    # 剂型定位：遍历每次出现，要求其后续文本以"规格样式"开头
    # （数字/每/按/括号/%）——避免药名后缀或包装文字中的剂型词误判。
    form, pos, hit = "", -1, ""
    for w in DOSAGE_FORMS:  # 长词优先
        start = 0
        while True:
            p = h.find(w, start)
            if p < 0:
                break
            tail = h[p + len(w):].lstrip()
            if re.match(r"^[\d每按(（%]", tail):
                form, pos, hit = w, p, w
                break
            start = p + 1
        if pos >= 0:
            break
    if pos < 0:
        return dict(seq=seq, remark=remark, confidence="fail", raw=body)
    name = h[:pos].strip()
    rest = h[pos + len(hit):].strip()
    # 规格 vs 包装描述：最早出现的包装关键词为界
    cuts = [rest.find(k) for k in PACK_MARKERS if rest.find(k) > 0]
    if cuts:
        c = min(cuts)
        spec, pack = rest[:c].strip(), rest[c:].strip()
        conf = "high"
    else:
        spec, pack = rest.strip(), ""
        conf = "medium"
    # 原表规格列与包装列重复书写规格（如"15ml:3g 15ml:3g 规格:"）-> 去重
    dup = re.match(r"^(.*?)\s+\1\s*规格:?$", spec)
    if dup:
        spec = dup.group(1).strip()
    return dict(
        seq=seq, product_name=name, dosage_form=form, specification=spec,
        pack_desc=pack, pack_qty=qty, pack_unit=unit,
        manufacturer_raw=mfr_raw, manufacturer_main=mfr_main,
        price=price, remark=remark, confidence=conf,
    )


def main():
    text = SRC.read_text(encoding="utf-8")
    records, problems = split_records(text)
    rows = [parse_body(s, b, r) for s, b, r in records]
    fields = ["seq", "product_name", "dosage_form", "specification", "pack_desc",
              "pack_qty", "pack_unit", "manufacturer_raw", "manufacturer_main",
              "price", "remark", "confidence", "raw"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    ok = [r for r in rows if r.get("confidence") in ("high", "medium")]
    med = [r for r in rows if r.get("confidence") == "medium"]
    print(f"记录总数={len(rows)}  解析成功={len(ok)}(high={len(ok)-len(med)}, medium={len(med)})  失败={len(rows)-len(ok)}")
    print(f"序号校验：{'通过' if not problems else problems}")
    print(f"备注分布：{ {r['remark']: sum(1 for x in rows if x['remark']==r['remark']) for r in rows} }")
    print(f"企业数(主企业去重)={len({r.get('manufacturer_main') for r in ok})}")
    print("\n== 失败记录 ==")
    for r in rows:
        if r.get("confidence") == "fail":
            print(r["seq"], r["raw"][:90])
    print("\n== 抽样核对（含珠海和凡 16/17） ==")
    for r in rows:
        if r["seq"] in (1, 8, 12, 16, 17, 20, 21, 22, 23, 24, 49, 64, 70, 74, 94, 121):
            print({k: r.get(k, "") for k in ("seq", "product_name", "dosage_form", "specification",
                                             "pack_qty", "pack_unit", "manufacturer_main", "price", "remark", "confidence")})
    print(f"\nCSV -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
