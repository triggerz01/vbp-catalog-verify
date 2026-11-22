-- =============================================================
-- 药品集采与医保目录交叉核验数据库 · DDL（SQLite）
-- 8 个业务实体 + 用户账号；主外键 / UNIQUE / CHECK / 索引 / 视图
-- data_kind 字段区分「真实」与「模拟」数据（沿用 832 项目做法）
-- =============================================================
PRAGMA foreign_keys = ON;

-- ---------- 企业 ----------
CREATE TABLE manufacturer (
  manufacturer_id INTEGER PRIMARY KEY,
  name            TEXT NOT NULL UNIQUE,            -- 企业名称
  uscc            TEXT UNIQUE,                     -- 统一社会信用代码
  type            TEXT NOT NULL DEFAULT '中资'
                  CHECK(type IN ('中资','外资')),
  data_kind       TEXT NOT NULL DEFAULT '真实'
                  CHECK(data_kind IN ('真实','模拟'))
);

-- ---------- 药品（批文级） ----------
CREATE TABLE drug (
  drug_id         INTEGER PRIMARY KEY,
  approval_no     TEXT UNIQUE,                     -- 国药准字（全国唯一）
  generic_name    TEXT NOT NULL,                   -- 通用名（含盐基）
  core_name       TEXT,                            -- 核心名（去盐基，用于跨源匹配）
  dosage_form     TEXT,
  specification   TEXT,
  manufacturer_id INTEGER REFERENCES manufacturer(manufacturer_id),
  status          TEXT NOT NULL DEFAULT '在产'
                  CHECK(status IN ('在产','注销')),
  data_kind       TEXT NOT NULL DEFAULT '模拟'
                  CHECK(data_kind IN ('真实','模拟'))
);

-- ---------- 集采批次 ----------
CREATE TABLE vbp_batch (
  batch_id     INTEGER PRIMARY KEY,
  batch_no     TEXT NOT NULL UNIQUE,               -- 如「第九批」
  tender_date  TEXT,                               -- 开标日期
  exec_date    TEXT,                               -- 执行日期
  notice_no    TEXT,
  data_kind    TEXT NOT NULL DEFAULT '真实'
               CHECK(data_kind IN ('真实','模拟'))
);

-- ---------- 公告（来源追溯中枢） ----------
CREATE TABLE announcement (
  announcement_id INTEGER PRIMARY KEY,
  notice_no       TEXT UNIQUE,                     -- 公告文号
  title           TEXT NOT NULL,
  publisher       TEXT,                            -- 发布机构
  pub_date        TEXT,
  url             TEXT,
  ann_type        TEXT CHECK(ann_type IN
                  ('中选结果','供应清单','违规处理','目录通知','其他')),
  data_kind       TEXT NOT NULL DEFAULT '真实'
                  CHECK(data_kind IN ('真实','模拟'))
);

-- ---------- 中选记录（事实表） ----------
CREATE TABLE selected_item (
  selected_id   INTEGER PRIMARY KEY,
  batch_id      INTEGER NOT NULL REFERENCES vbp_batch(batch_id),
  drug_id       INTEGER REFERENCES drug(drug_id),  -- 可空：匹配失败即核验结果
  seq_no        INTEGER,                           -- 原清单序号
  product_name  TEXT NOT NULL,
  dosage_form   TEXT,
  specification TEXT,
  pack_desc     TEXT,
  pack_qty      INTEGER,
  pack_unit     TEXT,
  manufacturer_id INTEGER REFERENCES manufacturer(manufacturer_id),
  price         REAL NOT NULL CHECK(price > 0),    -- 中选价（元）
  remark        TEXT,                              -- 中选/备供/视同主供
  status        TEXT NOT NULL DEFAULT '有效'
                CHECK(status IN ('有效','失效')),
  source_announcement_id INTEGER REFERENCES announcement(announcement_id),
  data_kind     TEXT NOT NULL DEFAULT '真实'
                CHECK(data_kind IN ('真实','模拟'))
);
CREATE UNIQUE INDEX idx_selected_batch_seq ON selected_item(batch_id, seq_no);
CREATE INDEX idx_selected_name ON selected_item(product_name);
CREATE INDEX idx_selected_mfr  ON selected_item(manufacturer_id);

-- ---------- 供应省份（中选记录 : 省份 = m:n） ----------
CREATE TABLE supply_province (
  selected_id INTEGER NOT NULL
              REFERENCES selected_item(selected_id) ON DELETE CASCADE,
  province    TEXT NOT NULL,
  data_kind   TEXT NOT NULL DEFAULT '模拟'
              CHECK(data_kind IN ('真实','模拟')),
  PRIMARY KEY (selected_id, province)
);

-- ---------- 医保目录条目 ----------
CREATE TABLE catalog_entry (
  entry_id        INTEGER PRIMARY KEY,
  catalog_version TEXT NOT NULL,                   -- 2023
  catalog_no      TEXT NOT NULL,                   -- 目录编号
  product_name    TEXT NOT NULL,                   -- 通用名
  norm_name       TEXT,                            -- 归一化通用名（去括号别名）
  dosage_form     TEXT,
  category        TEXT CHECK(category IN ('甲','乙')),
  section         TEXT CHECK(section IN ('西药','中成药','谈判','饮片')),
  note          TEXT,                              -- 限制条件/支付标准
  source_announcement_id INTEGER REFERENCES announcement(announcement_id),
  data_kind       TEXT NOT NULL DEFAULT '真实'
                  CHECK(data_kind IN ('真实','模拟')),
  UNIQUE(catalog_version, section, catalog_no, product_name, dosage_form)
);

-- ---------- 违规 / 取消资格 ----------
CREATE TABLE violation (
  violation_id  INTEGER PRIMARY KEY,
  notice_no     TEXT,
  manufacturer  TEXT NOT NULL,                     -- 企业名（文本，弱关联键）
  product_name  TEXT NOT NULL,                     -- 药品名（文本，弱关联键）
  viol_type     TEXT CHECK(viol_type IN ('断供','取消资格','其他')),
  decision_date TEXT,
  action        TEXT,
  source_announcement_id INTEGER REFERENCES announcement(announcement_id),
  data_kind     TEXT NOT NULL DEFAULT '真实'
                CHECK(data_kind IN ('真实','模拟'))
);

-- ---------- 用户账号（课程模拟，角色权限在应用层实现） ----------
CREATE TABLE user_account (
  user_id       INTEGER PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN
                ('admin','hospital','pharma','researcher','public')),
  display_name  TEXT,
  data_kind     TEXT NOT NULL DEFAULT '模拟'
                CHECK(data_kind IN ('真实','模拟'))
);

-- ---------- 核验视图 1：中选记录全字段（含批文与公告回溯） ----------
CREATE VIEW v_selected_full AS
SELECT s.selected_id, b.batch_no, s.seq_no, s.product_name, s.dosage_form,
       s.specification, m.name AS manufacturer, s.price, s.remark,
       s.status, d.approval_no, d.generic_name, a.title AS source_title, a.url AS source_url
FROM selected_item s
JOIN vbp_batch b  ON b.batch_id = s.batch_id
LEFT JOIN manufacturer m ON m.manufacturer_id = s.manufacturer_id
LEFT JOIN drug d  ON d.drug_id = s.drug_id
LEFT JOIN announcement a ON a.announcement_id = s.source_announcement_id;

-- ---------- 核验视图 2：违规核验（已取消资格/断供，但中选记录仍有效） ----------
CREATE VIEW v_violation_conflict AS
SELECT v.violation_id, v.manufacturer, v.product_name, v.viol_type, v.decision_date,
       s.selected_id, b.batch_no, s.seq_no, s.price, s.status AS selected_status
FROM violation v
JOIN manufacturer m ON m.name = v.manufacturer
JOIN selected_item s ON s.manufacturer_id = m.manufacturer_id
                    AND s.product_name = v.product_name
JOIN vbp_batch b ON b.batch_id = s.batch_id
WHERE s.status = '有效';

-- ---------- 核验视图 3：目录内但批文库无有效批文（左外连接找空，按归一化核心名匹配） ----------
CREATE VIEW v_catalog_no_approval AS
SELECT c.entry_id, c.catalog_no, c.product_name, c.category, c.section
FROM catalog_entry c
WHERE NOT EXISTS (
  SELECT 1 FROM drug d
  WHERE d.status = '在产'
    AND (c.norm_name LIKE '%' || d.core_name || '%'
         OR d.core_name LIKE '%' || c.norm_name || '%')
);
