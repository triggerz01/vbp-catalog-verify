# -*- coding: utf-8 -*-
"""数据库连接与查询助手（沿用 832 项目 db.py 模式）。"""
import os
import sqlite3
from pathlib import Path
from flask import g

DB_PATH = Path(os.environ.get("DB_PATH", Path(__file__).resolve().parent.parent / "med_stat.sqlite"))


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


def query(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def query_one(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
