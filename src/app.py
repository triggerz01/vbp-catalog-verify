# -*- coding: utf-8 -*-
"""药品集采与医保目录交叉核验系统 · Flask 后端
选项 1：传统动态网站（Flask + SQLite + Jinja），SQL 全部手写、服务端执行，不用 ORM。
角色权限在应用层 + SQL 层实现（SQLite 不支持 GRANT）。
"""
import hashlib
import os
from functools import wraps
from pathlib import Path

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)

from db import query, query_one, get_db, close_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "med-stat-demo-key")
app.teardown_appcontext(close_db)

ROLES = {"admin": "管理员", "hospital": "医院采购", "pharma": "药企合规",
         "researcher": "研究员", "public": "公众"}


# ---------- 登录与角色 ----------
def verify_pw(pw, stored):
    try:
        head, salt, h = stored.split("$")
        it = int(head.split(":")[2])
        return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), it).hex() == h
    except Exception:
        return False


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return query_one("SELECT * FROM user_account WHERE user_id=?", (uid,))


@app.context_processor
def inject_user():
    return {"me": current_user(), "ROLES": ROLES}


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        u = current_user()
        if not u or u["role"] != "admin":
            abort(403)
        return f(*a, **kw)
    return wrapper


# ---------- 登录 / 注销 ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = query_one("SELECT * FROM user_account WHERE username=?", (request.form["username"].strip(),))
        if u and verify_pw(request.form["password"], u["password_hash"]):
            session["uid"] = u["user_id"]
            flash(f"已登录：{u['display_name']}（{ROLES[u['role']]}）", "ok")
            return redirect(request.args.get("next") or url_for("workspace"))
        flash("账号或口令不正确", "err")
    accounts = query("SELECT username,display_name,role FROM user_account ORDER BY user_id")
    return render_template("login.html", accounts=accounts)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------- 工作台 ----------
@app.route("/")
def index():
    stats = {
        "selected": query_one("SELECT COUNT(*) c FROM selected_item")["c"],
        "mfr": query_one("SELECT COUNT(*) c FROM manufacturer")["c"],
        "catalog": query_one("SELECT COUNT(*) c FROM catalog_entry")["c"],
        "violation": query_one("SELECT COUNT(*) c FROM violation")["c"],
        "conflict": query_one("SELECT COUNT(*) c FROM v_violation_conflict")["c"],
        "no_approval": query_one("SELECT COUNT(*) c FROM v_catalog_no_approval")["c"],
    }
    conflicts = query("SELECT * FROM v_violation_conflict")
    return render_template("index.html", stats=stats, conflicts=conflicts)


# ---------- 角色工作台（登录后按服务端角色渲染） ----------
@app.route("/workspace")
@login_required
def workspace():
    u = current_user()
    role = u["role"]
    stats = {
        "selected": query_one("SELECT COUNT(*) c FROM selected_item")["c"],
        "mfr": query_one("SELECT COUNT(*) c FROM manufacturer")["c"],
        "catalog": query_one("SELECT COUNT(*) c FROM catalog_entry")["c"],
        "violation": query_one("SELECT COUNT(*) c FROM violation")["c"],
        "conflict": query_one("SELECT COUNT(*) c FROM v_violation_conflict")["c"],
        "no_approval": query_one("SELECT COUNT(*) c FROM v_catalog_no_approval")["c"],
        "announcement": query_one("SELECT COUNT(*) c FROM announcement")["c"],
    }
    conflicts = query("SELECT * FROM v_violation_conflict")
    not_in_catalog = query(
        "SELECT d.generic_name FROM drug d WHERE NOT EXISTS("
        " SELECT 1 FROM catalog_entry c WHERE c.norm_name LIKE '%'||d.core_name||'%'"
        " OR d.core_name LIKE '%'||c.norm_name||'%')")
    price_gap = query(
        "SELECT product_name, COUNT(*) n, ROUND(MIN(price),2) pmin, ROUND(MAX(price),2) pmax,"
        " ROUND(MAX(price)-MIN(price),2) gap FROM selected_item"
        " GROUP BY product_name HAVING n>1 AND gap>1 ORDER BY gap DESC LIMIT 10")
    ctx = {"u": u, "stats": stats, "conflicts": conflicts,
           "not_in_catalog": not_in_catalog, "price_gap": price_gap}

    if role == "hospital":
        ctx["prov_count"] = query_one("SELECT COUNT(DISTINCT province) c FROM supply_province")["c"]
        ctx["cat_ab"] = query("SELECT category,COUNT(*) n FROM catalog_entry GROUP BY category")
        return render_template("ws_hospital.html", **ctx)

    if role == "pharma":
        mid = request.args.get("mid", type=int)
        ctx["mfrs"] = query("SELECT manufacturer_id,name FROM manufacturer ORDER BY name")
        ctx["mid"] = mid
        if mid:
            ctx["sel_mfr"] = query_one("SELECT * FROM manufacturer WHERE manufacturer_id=?", (mid,))
            ctx["mfr_items"] = query("SELECT s.*,b.batch_no FROM selected_item s JOIN vbp_batch b ON b.batch_id=s.batch_id WHERE s.manufacturer_id=? ORDER BY s.seq_no", (mid,))
            ctx["mfr_viols"] = query("SELECT * FROM violation WHERE manufacturer=(SELECT name FROM manufacturer WHERE manufacturer_id=?)", (mid,))
            ctx["mfr_stat"] = query_one("SELECT COUNT(*) n,ROUND(AVG(price),2) avg_p FROM selected_item WHERE manufacturer_id=?", (mid,))
        ctx["no_approval_list"] = query("SELECT * FROM v_catalog_no_approval")
        return render_template("ws_pharma.html", **ctx)

    if role == "researcher":
        ctx["data_kind"] = query("SELECT data_kind,COUNT(*) n FROM selected_item GROUP BY data_kind")
        return render_template("ws_researcher.html", **ctx)

    if role == "admin":
        ctx["mock_stat"] = query("SELECT data_kind,COUNT(*) n FROM selected_item GROUP BY data_kind")
        return render_template("ws_admin.html", **ctx)

    return redirect(url_for("index"))


# ---------- 中选记录：组合检索 ----------
@app.route("/selected")
def selected():
    q = request.args.get("q", "").strip()
    mfr = request.args.get("mfr", "").strip()
    remark = request.args.get("remark", "").strip()
    prov = request.args.get("province", "").strip()
    pmin, pmax = request.args.get("pmin", ""), request.args.get("pmax", "")
    sql = ("SELECT s.*, m.name mfr_name, d.generic_name, d.approval_no, b.batch_no "
           "FROM selected_item s "
           "LEFT JOIN manufacturer m ON m.manufacturer_id=s.manufacturer_id "
           "LEFT JOIN drug d ON d.drug_id=s.drug_id "
           "JOIN vbp_batch b ON b.batch_id=s.batch_id WHERE 1=1 ")
    args = []
    if q:
        sql += " AND s.product_name LIKE ?"
        args.append(f"%{q}%")
    if mfr:
        sql += " AND m.name LIKE ?"
        args.append(f"%{mfr}%")
    if remark:
        sql += " AND s.remark=?"
        args.append(remark)
    if prov:
        sql += " AND EXISTS(SELECT 1 FROM supply_province sp WHERE sp.selected_id=s.selected_id AND sp.province=?)"
        args.append(prov)
    if pmin:
        sql += " AND s.price>=?"
        args.append(float(pmin))
    if pmax:
        sql += " AND s.price<=?"
        args.append(float(pmax))
    sql += " ORDER BY s.seq_no LIMIT 300"
    rows = query(sql, args)
    provinces = query("SELECT DISTINCT province FROM supply_province ORDER BY province")
    return render_template("selected.html", rows=rows, provinces=provinces)


@app.route("/selected/<int:sid>")
def selected_detail(sid):
    s = query_one("SELECT * FROM v_selected_full WHERE selected_id=?", (sid,))
    if not s:
        abort(404)
    provs = query("SELECT province,data_kind FROM supply_province WHERE selected_id=?", (sid,))
    # 同品种其它中选/备供记录（价格对比）
    peers = query("SELECT s.selected_id,s.seq_no,m.name mfr,s.price,s.remark FROM selected_item s "
                  "LEFT JOIN manufacturer m ON m.manufacturer_id=s.manufacturer_id "
                  "WHERE s.product_name=? AND s.selected_id<>? ORDER BY s.price", (s["product_name"], sid))
    # 关联违规（企业名+药品名弱关联）
    viols = query("SELECT v.* FROM violation v JOIN manufacturer m ON m.name=v.manufacturer "
                  "WHERE v.product_name=? AND m.manufacturer_id=(SELECT manufacturer_id FROM selected_item WHERE selected_id=?)",
                  (s["product_name"], sid))
    # 目录匹配（按核心名）
    cats = query("SELECT c.* FROM catalog_entry c WHERE c.norm_name IN "
                 "(SELECT core_name FROM drug WHERE drug_id=(SELECT drug_id FROM selected_item WHERE selected_id=?)) "
                 "OR EXISTS(SELECT 1 FROM drug d WHERE d.drug_id=(SELECT drug_id FROM selected_item WHERE selected_id=?) "
                 "AND (c.norm_name LIKE '%'||d.core_name||'%' OR d.core_name LIKE '%'||c.norm_name||'%'))",
                 (sid, sid))
    return render_template("selected_detail.html", s=s, provs=provs, peers=peers, viols=viols, cats=cats)


# ---------- 医保目录 ----------
@app.route("/catalog")
def catalog():
    q = request.args.get("q", "").strip()
    cat = request.args.get("category", "").strip()
    sql = "SELECT * FROM catalog_entry WHERE 1=1"
    args = []
    if q:
        sql += " AND product_name LIKE ?"
        args.append(f"%{q}%")
    if cat:
        sql += " AND category=?"
        args.append(cat)
    sql += " ORDER BY CAST(catalog_no AS INTEGER), entry_id LIMIT 300"
    rows = query(sql, args)
    return render_template("catalog.html", rows=rows)


# ---------- 企业 ----------
@app.route("/manufacturers")
def manufacturers():
    rows = query("SELECT m.*, COUNT(s.selected_id) n, ROUND(AVG(s.price),2) avg_p "
                 "FROM manufacturer m LEFT JOIN selected_item s ON s.manufacturer_id=m.manufacturer_id "
                 "GROUP BY m.manufacturer_id ORDER BY n DESC, m.name")
    return render_template("manufacturers.html", rows=rows)


@app.route("/manufacturers/<int:mid>")
def manufacturer_detail(mid):
    m = query_one("SELECT * FROM manufacturer WHERE manufacturer_id=?", (mid,))
    if not m:
        abort(404)
    items = query("SELECT s.*, b.batch_no FROM selected_item s JOIN vbp_batch b ON b.batch_id=s.batch_id "
                  "WHERE s.manufacturer_id=? ORDER BY s.seq_no", (mid,))
    viols = query("SELECT * FROM violation WHERE manufacturer=?", (m["name"],))
    return render_template("manufacturer_detail.html", m=m, items=items, viols=viols)


# ---------- 违规名单 ----------
@app.route("/violations")
def violations():
    rows = query("SELECT v.*, a.title src_title, a.url src_url FROM violation v "
                 "LEFT JOIN announcement a ON a.announcement_id=v.source_announcement_id")
    return render_template("violations.html", rows=rows)


# ---------- 核验中心 ----------
@app.route("/verify")
@login_required
def verify():
    conflict = query("SELECT * FROM v_violation_conflict")
    no_approval = query("SELECT * FROM v_catalog_no_approval")
    # 集采品种未入医保目录（按核心名找空）
    not_in_catalog = query(
        "SELECT d.drug_id, d.generic_name, d.core_name FROM drug d WHERE NOT EXISTS("
        " SELECT 1 FROM catalog_entry c WHERE c.norm_name LIKE '%'||d.core_name||'%'"
        " OR d.core_name LIKE '%'||c.norm_name||'%')")
    # 同品种跨企业中选价差异（价格核验）
    price_gap = query(
        "SELECT product_name, COUNT(*) n, ROUND(MIN(price),2) pmin, ROUND(MAX(price),2) pmax,"
        " ROUND(MAX(price)-MIN(price),2) gap FROM selected_item"
        " GROUP BY product_name HAVING n>1 AND gap>1 ORDER BY gap DESC LIMIT 20")
    return render_template("verify.html", conflict=conflict, no_approval=no_approval,
                           not_in_catalog=not_in_catalog, price_gap=price_gap)


# ---------- 统计分析 ----------
@app.route("/stats")
@login_required
def stats():
    by_remark = query("SELECT remark, COUNT(*) n, ROUND(AVG(price),2) avg_p FROM selected_item GROUP BY remark")
    by_mfr = query("SELECT m.name, COUNT(*) n, ROUND(AVG(s.price),2) avg_p, ROUND(MIN(s.price),2) mn, ROUND(MAX(s.price),2) mx "
                   "FROM selected_item s JOIN manufacturer m ON m.manufacturer_id=s.manufacturer_id "
                   "GROUP BY m.name HAVING n>=2 ORDER BY n DESC, avg_p DESC LIMIT 15")
    by_cat = query("SELECT category, COUNT(*) n FROM catalog_entry GROUP BY category")
    by_prov = query("SELECT province, COUNT(*) n FROM supply_province GROUP BY province ORDER BY n DESC LIMIT 15")
    top_price = query("SELECT s.product_name, m.name mfr, s.price, s.remark FROM selected_item s "
                      "LEFT JOIN manufacturer m ON m.manufacturer_id=s.manufacturer_id ORDER BY s.price DESC LIMIT 10")
    return render_template("stats.html", by_remark=by_remark, by_mfr=by_mfr, by_cat=by_cat,
                           by_prov=by_prov, top_price=top_price)


# ---------- 公告（来源追溯） ----------
@app.route("/announcements")
def announcements():
    rows = query("SELECT a.*, (SELECT COUNT(*) FROM selected_item s WHERE s.source_announcement_id=a.announcement_id) n_sel,"
                 " (SELECT COUNT(*) FROM catalog_entry c WHERE c.source_announcement_id=a.announcement_id) n_cat,"
                 " (SELECT COUNT(*) FROM violation v WHERE v.source_announcement_id=a.announcement_id) n_vio"
                 " FROM announcement a")
    return render_template("announcements.html", rows=rows)


# ---------- 数据管理（仅 admin）：中选记录 CRUD ----------
@app.route("/admin/selected/new", methods=["GET", "POST"])
@admin_required
def admin_selected_new():
    if request.method == "POST":
        f = request.form
        db = get_db()
        try:
            db.execute("BEGIN")
            cur = db.execute(
                "INSERT INTO selected_item(batch_id,drug_id,seq_no,product_name,dosage_form,specification,"
                "pack_qty,pack_unit,manufacturer_id,price,remark,status,source_announcement_id,data_kind)"
                " VALUES(1,NULL,?,?,?,?,?,?,?,?,?,'有效',1,'模拟')",
                (int(f["seq_no"]), f["product_name"], f["dosage_form"], f["specification"],
                 int(f["pack_qty"] or 0), f["pack_unit"], int(f["manufacturer_id"]),
                 float(f["price"]), f["remark"]))
            sid = cur.lastrowid
            for p in request.form.getlist("provinces"):
                db.execute("INSERT OR IGNORE INTO supply_province(selected_id,province,data_kind) VALUES(?,?,'模拟')", (sid, p))
            db.execute("COMMIT")
            flash("已新增中选记录", "ok")
            return redirect(url_for("selected_detail", sid=sid))
        except Exception as e:
            db.execute("ROLLBACK")
            flash(f"新增失败：{e}", "err")
    mfrs = query("SELECT manufacturer_id,name FROM manufacturer ORDER BY name")
    return render_template("admin_selected_form.html", mfrs=mfrs, s=None)


@app.route("/admin/selected/<int:sid>/edit", methods=["GET", "POST"])
@admin_required
def admin_selected_edit(sid):
    s = query_one("SELECT * FROM selected_item WHERE selected_id=?", (sid,))
    if not s:
        abort(404)
    if request.method == "POST":
        f = request.form
        db = get_db()
        try:
            db.execute("BEGIN")
            db.execute("UPDATE selected_item SET product_name=?,dosage_form=?,specification=?,price=?,"
                       "remark=?,status=?,manufacturer_id=? WHERE selected_id=?",
                       (f["product_name"], f["dosage_form"], f["specification"], float(f["price"]),
                        f["remark"], f["status"], int(f["manufacturer_id"]), sid))
            db.execute("DELETE FROM supply_province WHERE selected_id=?", (sid,))
            for p in request.form.getlist("provinces"):
                db.execute("INSERT OR IGNORE INTO supply_province(selected_id,province,data_kind) VALUES(?,?,'模拟')", (sid, p))
            db.execute("COMMIT")
            flash("已保存", "ok")
            return redirect(url_for("selected_detail", sid=sid))
        except Exception as e:
            db.execute("ROLLBACK")
            flash(f"保存失败：{e}", "err")
    mfrs = query("SELECT manufacturer_id,name FROM manufacturer ORDER BY name")
    provs = [r["province"] for r in query("SELECT province FROM supply_province WHERE selected_id=?", (sid,))]
    return render_template("admin_selected_form.html", mfrs=mfrs, s=s, provs=provs)


@app.route("/admin/selected/<int:sid>/delete", methods=["POST"])
@admin_required
def admin_selected_delete(sid):
    db = get_db()
    try:
        db.execute("BEGIN")
        db.execute("DELETE FROM supply_province WHERE selected_id=?", (sid,))
        db.execute("DELETE FROM selected_item WHERE selected_id=?", (sid,))
        db.execute("COMMIT")
        flash("已删除", "ok")
    except Exception as e:
        db.execute("ROLLBACK")
        flash(f"删除失败：{e}", "err")
    return redirect(url_for("selected"))


# ---------- 违规记录处理：将中选记录标记失效（核验闭环写操作） ----------
@app.route("/admin/selected/<int:sid>/invalidate", methods=["POST"])
@admin_required
def admin_selected_invalidate(sid):
    db = get_db()
    db.execute("UPDATE selected_item SET status='失效' WHERE selected_id=?", (sid,))
    db.commit()
    flash("已将该中选记录标记为「失效」，核验矛盾随之消除", "ok")
    return redirect(url_for("verify"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=bool(os.environ.get("APP_DEBUG")))
