# -*- coding: utf-8 -*-
"""建库：schema.sql + 三源真实数据 + 标注的模拟数据 -> med_stat.sqlite

数据来源与性质：
- selected_item / manufacturer / vbp_batch / catalog_entry / violation / announcement：真实（公开公告、PDF 解析）
- drug.approval_no：模拟占位（待 NMPA / 第三方批文库替换），generic_name 为真实通用名
- supply_province：模拟（真实应来自各省执行公告，抽样分配仅作演示）
- user_account：模拟演示账号（pbkdf2 哈希，标准库实现，无第三方依赖）
"""
import csv
import hashlib
import os
import re
import secrets
import sqlite3
from pathlib import Path

from parse_catalog import generic_of, core_of

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "med_stat.sqlite"
SCHEMA = ROOT / "src" / "schema.sql"
SUPPLY = ROOT / "data" / "processed" / "supply_batch9.csv"
CATALOG = ROOT / "data" / "processed" / "catalog_subset.csv"
MATCH = ROOT / "data" / "processed" / "drug_match.csv"

PROVINCES = ["北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
             "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
             "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "内蒙古",
             "广西", "西藏", "宁夏", "新疆"]


def hash_pw(pw: str) -> str:
    salt = secrets.token_hex(8)
    it = 60000
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), it).hex()
    return f"pbkdf2:sha256:{it}${salt}${h}"


def main():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    cur = con.cursor()

    # ---- 公告（真实） ----
    announcements = [
        ("第九批国家组织药品集采中选药品供应清单", "国家组织药品联合采购办公室", "2024-02",
         "https://ylbz.tj.gov.cn/YBJSY/gabsycs/tzgggh/202402/W020240227639820302438.pdf", "供应清单"),
        ("第九批国家组织药品集中带量采购中选结果执行提示", "国家组织药品联合采购办公室", "2024-03-22",
         "https://www.smpaa.cn/xxgk/gggs/2024/03/22/13368.shtml", "中选结果"),
        ("关于取消珠海和凡医药股份有限公司吡拉西坦注射液中选资格并将该企业列入违规名单的公告",
         "国家组织药品联合采购办公室（江苏省医保局转载）", "2024-11-29",
         "http://ybj.jiangsu.gov.cn/art/2024/11/29/art_91459_11432354.html", "违规处理"),
        ("联采办回应华北制药断供：违约必受惩戒", "国家组织药品联合采购办公室", "2021-08",
         "https://www.peopleapp.com/column/30038196486-500003218659", "违规处理"),
        ("国家医保局 人力资源社会保障部关于印发《国家基本医疗保险、工伤保险和生育保险药品目录（2023年）》的通知",
         "国家医保局 人力资源社会保障部", "2023-12-13",
         "https://www.nhsa.gov.cn/art/2023/12/13/art_104_11673.html", "目录通知"),
    ]
    ann_ids = {}
    for i, (title, pub, date, url, typ) in enumerate(announcements, start=1):
        cur.execute("INSERT INTO announcement(announcement_id,notice_no,title,publisher,pub_date,url,ann_type,data_kind)"
                    " VALUES(?,?,?,?,?,?,?,'真实')",
                    (i, f"ANN-{i:03d}", title, pub, date, url, typ))
        ann_ids[typ if typ not in ann_ids else f"{typ}-{i}"] = i
    ANN_SUPPLY, ANN_EXEC, ANN_ZH, ANN_HB, ANN_CATALOG = 1, 2, 3, 4, 5

    # ---- 集采批次（真实） ----
    cur.execute("INSERT INTO vbp_batch(batch_id,batch_no,tender_date,exec_date,notice_no,data_kind)"
                " VALUES(1,'第九批','2023-11-06','2024-03',NULL,'真实')")

    # ---- 中选记录 + 企业（真实） ----
    supply = list(csv.DictReader(SUPPLY.open(encoding="utf-8-sig")))
    mfr_id, mfr_map = {}, {}
    def get_mfr(name, foreign=False):
        if name not in mfr_map:
            mid = len(mfr_map) + 1
            mfr_map[name] = mid
            cur.execute("INSERT INTO manufacturer(manufacturer_id,name,uscc,type,data_kind)"
                        " VALUES(?,?,NULL,?,?)",
                        (mid, name, "外资" if foreign else "中资", "真实"))
        return mfr_map[name]

    # ---- 品种（通用名真实，批文号模拟） ----
    match = {r["generic_name"]: r for r in csv.DictReader(MATCH.open(encoding="utf-8-sig"))}
    drug_map = {}  # generic_name -> drug_id
    # 找每个品种第一条记录的企业与剂型
    first = {}
    for r in supply:
        g = generic_of(r["product_name"])
        if g not in first:
            first[g] = r

    # 先注册全部企业（含次企业）
    for r in supply:
        for j, name in enumerate(r["manufacturer_raw"].split(" ")):
            if not name:
                continue
            foreign = bool(re.search(r"Ltd|Cipla|Dr\.|Reddy", name))
            get_mfr(name, foreign)
    # 华北制药（真实，用于违规案例，不在第九批清单）
    hb_id = get_mfr("华北制药股份有限公司")

    for g in sorted(first):
        r = first[g]
        mid = mfr_map[r["manufacturer_main"]]
        did = len(drug_map) + 1
        drug_map[g] = did
        cur.execute("INSERT INTO drug(drug_id,approval_no,generic_name,core_name,dosage_form,specification,manufacturer_id,status,data_kind)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (did, f"国药准字H2023{did:04d}", g, core_of(g), r["dosage_form"], r["specification"],
                     mid, "在产", "模拟"))
    # 演示核验规则：某品种批文已注销（模拟状态），应被"目录内无有效批文"检出
    cur.execute("UPDATE drug SET status='注销' WHERE generic_name='醋酸卡泊芬净'")

    for r in supply:
        g = generic_of(r["product_name"])
        cur.execute(
            "INSERT INTO selected_item(batch_id,drug_id,seq_no,product_name,dosage_form,specification,"
            "pack_desc,pack_qty,pack_unit,manufacturer_id,price,remark,status,source_announcement_id,data_kind)"
            " VALUES(1,?,?,?,?,?,?,?,?,?,?,?,'有效',?,'真实')",
            (drug_map[g], int(r["seq"]), r["product_name"], r["dosage_form"], r["specification"],
             r["pack_desc"], int(r["pack_qty"]), r["pack_unit"], mfr_map[r["manufacturer_main"]],
             float(r["price"]), r["remark"], ANN_SUPPLY))

    # ---- 供应省份（模拟抽样，真实应来自各省执行公告） ----
    for r in supply:
        sid = int(r["seq"])
        n = 2 + (sid % 3)  # 2~4 省
        for k in range(n):
            prov = PROVINCES[(sid * 3 + k * 7) % len(PROVINCES)]
            cur.execute("INSERT OR IGNORE INTO supply_province(selected_id,province,data_kind) VALUES(?,?,'模拟')",
                        (sid, prov))

    # ---- 医保目录条目（真实子集） ----
    for i, r in enumerate(csv.DictReader(CATALOG.open(encoding="utf-8-sig")), start=1):
        cur.execute("INSERT INTO catalog_entry(entry_id,catalog_version,catalog_no,product_name,norm_name,dosage_form,"
                    "category,section,note,source_announcement_id,data_kind) VALUES(?,?,?,?,?,?,?,?,?,?,'真实')",
                    (i, r["catalog_version"], r["catalog_no"], r["product_name"], r["norm_name"], r["dosage_form"],
                     r["category"], r["section"], r["note"], ANN_CATALOG))

    # ---- 违规记录（真实公告） ----
    cur.execute("INSERT INTO violation(violation_id,notice_no,manufacturer,product_name,viol_type,decision_date,action,source_announcement_id,data_kind)"
                " VALUES(1,'ANN-003','珠海和凡医药股份有限公司','吡拉西坦注射液','取消资格','2024-11-29',"
                "'取消第九批集采中选资格，列入违规名单',?,'真实')", (ANN_ZH,))
    cur.execute("INSERT INTO violation(violation_id,notice_no,manufacturer,product_name,viol_type,decision_date,action,source_announcement_id,data_kind)"
                " VALUES(2,'ANN-004','华北制药股份有限公司','布洛芬缓释胶囊','断供','2021-08',"
                "'第三批集采布洛芬缓释胶囊在山东断供，列入违规名单并限制参与后续集采',?,'真实')", (ANN_HB,))

    # ---- 用户账号（模拟演示） ----
    users = [("admin", "管理员", "admin"), ("hospital01", "医院采购员", "hospital"),
             ("pharma01", "药企合规员", "pharma"), ("researcher01", "研究员", "researcher")]
    for i, (u, d, role) in enumerate(users, start=1):
        cur.execute("INSERT INTO user_account(user_id,username,password_hash,role,display_name,data_kind)"
                    " VALUES(?,?,?,?,?,'模拟')", (i, u, hash_pw("meddemo"), role, d))

    con.commit()

    # ---- 验证 ----
    print("== 表行数 ==")
    for t in ["manufacturer", "drug", "vbp_batch", "announcement", "selected_item",
              "supply_province", "catalog_entry", "violation", "user_account"]:
        print(f"  {t}: {cur.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    print("\n== 核验1：已取消资格/断供但中选记录仍有效（v_violation_conflict） ==")
    for row in cur.execute("SELECT manufacturer,product_name,viol_type,batch_no,seq_no,price,selected_status FROM v_violation_conflict"):
        print("  ", row)
    print("\n== 核验2：目录内但批文库无有效批文（v_catalog_no_approval） ==")
    for row in cur.execute("SELECT catalog_no,product_name,category FROM v_catalog_no_approval"):
        print("  ", row)
    print("\n== 统计抽样：第九批各企业平均中选价 TOP5 ==")
    for row in cur.execute("SELECT m.name, COUNT(*) n, ROUND(AVG(s.price),2) avg_p FROM selected_item s "
                           "JOIN manufacturer m ON m.manufacturer_id=s.manufacturer_id "
                           "GROUP BY m.name HAVING n>=3 ORDER BY avg_p DESC LIMIT 5"):
        print("  ", row)
    print(f"\n数据库 -> {DB}")
    con.close()


if __name__ == "__main__":
    main()
