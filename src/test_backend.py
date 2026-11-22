# -*- coding: utf-8 -*-
"""端到端测试：在库副本上运行，不改动样本库。运行：python test_backend.py"""
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="medtest_"))
shutil.copy(ROOT / "med_stat.sqlite", TMP / "test.sqlite")
os.environ["DB_PATH"] = str(TMP / "test.sqlite")

import app as appmod

app = appmod.app
app.config["TESTING"] = True

passed, failed = 0, 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}")


def login(c, u="admin", p="meddemo"):
    return c.post("/login", data={"username": u, "password": p}, follow_redirects=True)


def count_conflict():
    cx = sqlite3.connect(os.environ["DB_PATH"])
    n = cx.execute("SELECT COUNT(*) FROM v_violation_conflict").fetchone()[0]
    cx.close()
    return n


def main():
    c = app.test_client()
    print("== 公共页面（未登录） ==")
    for path in ["/", "/selected", "/catalog", "/manufacturers", "/violations", "/announcements"]:
        check(f"GET {path} =200", c.get(path).status_code == 200)
    check("GET /login =200", c.get("/login").status_code == 200)
    check("未登录 /verify 跳登录(302)", c.get("/verify").status_code == 302)
    check("未登录 /stats 跳登录(302)", c.get("/stats").status_code == 302)

    print("== 公共首页（无角色全集/无演示口令） ==")
    r = c.get("/")
    check("首页无角色卡片全集", "按角色使用".encode() not in r.data)
    check("首页无各角色工作台标题", "医院采购工作台".encode() not in r.data and "数据管理工作台".encode() not in r.data)
    check("首页无演示口令", "meddemo".encode() not in r.data)
    check("首页含核心查询", "查询中选与价格".encode() in r.data)

    print("== 检索与详情（公开） ==")
    check("检索吡拉西坦含结果", "吡拉西坦注射液".encode() in c.get("/selected?q=吡拉西坦").data)
    r = c.get("/selected/16")
    check("中选16详情=200", r.status_code == 200)
    check("中选16含珠海和凡", "珠海和凡".encode() in r.data)
    check("中选16命中违规弱关联", "违规记录".encode() in r.data)
    check("中选16含目录匹配吡拉西坦", "1132".encode() in r.data)

    print("== 角色工作台：五种身份内容不同 ==")
    check("未登录 /workspace 跳登录(302)", c.get("/workspace").status_code == 302)
    r = login(c, "hospital01")
    check("医院登录默认进工作台", "医院采购工作台".encode() in r.data)
    check("医院台含违规风险", "违规风险".encode() in r.data)
    check("医院台无数据管理术语", "数据管理工作台".encode() not in r.data and "标记失效".encode() not in r.data)
    c.get("/logout")
    r = login(c, "pharma01")
    check("药企台", "药企合规工作台".encode() in r.data)
    check("药企台用选择企业(非我司)", "选择企业".encode() in r.data and "我司".encode() not in r.data)
    check("药企台含竞争价格", "竞争价格".encode() in r.data)
    c.get("/logout")
    r = login(c, "researcher01")
    check("研究员台", "研究员工作台".encode() in r.data)
    check("研究员台含四类核验", "四类交叉核验".encode() in r.data)
    check("研究员台含核验口径", "核验口径".encode() in r.data)
    check("研究员台无管理操作", "标记失效".encode() not in r.data and "新增中选".encode() not in r.data)
    # 研究员可读核验中心
    r = c.get("/verify")
    check("研究员可读核验中心", r.status_code == 200)
    check("核验1珠海和凡", "珠海和凡".encode() in r.data)
    check("核验3西地那非/地夸磷索钠", "西地那非".encode() in r.data and "地夸磷索钠".encode() in r.data)
    c.get("/logout")

    print("== 越权与管理员 ==")
    login(c, "researcher01")
    check("普通角色访问 admin=403", c.get("/admin/selected/new").status_code == 403)
    check("普通角色写操作=403", c.post("/admin/selected/16/invalidate").status_code == 403)
    c.get("/logout")
    r = login(c, "admin")
    check("管理员台", "数据管理工作台".encode() in r.data)
    check("管理员台含标记失效", "标记失效".encode() in r.data)
    check("管理员台含待处置冲突", "待处置冲突".encode() in r.data)

    print("== 管理员 CRUD ==")
    r = c.post("/admin/selected/new", data={
        "seq_no": 900, "product_name": "测试药品X", "dosage_form": "片剂",
        "specification": "10mg", "price": "9.9", "pack_qty": 1, "pack_unit": "盒",
        "manufacturer_id": 1, "remark": "中选药品", "provinces": ["北京", "山东"]}, follow_redirects=False)
    check("新增中选302", r.status_code == 302)
    sid = int(r.headers["Location"].rstrip("/").split("/")[-1])
    check("新增后可访问详情", c.get(f"/selected/{sid}").status_code == 200)
    r = c.post(f"/admin/selected/{sid}/edit", data={
        "product_name": "测试药品X改", "dosage_form": "片剂", "specification": "20mg",
        "price": "12.5", "remark": "中选药品", "status": "有效", "manufacturer_id": 1, "provinces": ["北京"]})
    check("编辑302", r.status_code == 302)
    check("编辑后名称生效", "测试药品X改".encode() in c.get(f"/selected/{sid}").data)
    r = c.post("/admin/selected/new", data={
        "seq_no": 901, "product_name": "非法价", "dosage_form": "片剂", "specification": "1mg",
        "price": "-5", "pack_qty": 1, "pack_unit": "盒", "manufacturer_id": 1, "remark": "中选药品"},
        follow_redirects=True)
    check("负价格被CHECK拒绝", "失败".encode() in r.data)
    before = count_conflict()
    c.post("/admin/selected/16/invalidate")
    c.post("/admin/selected/17/invalidate")
    after = count_conflict()
    check(f"核验闭环：标记失效后矛盾 {before}->{after}", after == before - 2)
    r = c.post(f"/admin/selected/{sid}/delete")
    check("删除302", r.status_code == 302)
    check("删除后404", c.get(f"/selected/{sid}").status_code == 404)

    print(f"\n结果：{passed}/{passed+failed} 通过")
    shutil.rmtree(TMP, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
