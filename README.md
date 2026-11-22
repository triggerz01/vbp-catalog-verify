# 药品集采与医保目录交叉核验数据库

《数据库系统概论》课程大作业 · 自选主题。把**国家联采办公告、国家医保药品目录、药品批文、违规名单**四个来源围绕同一批药品统一组织，让使用者核对价格、供应、资格与官方记录之间的一致性与矛盾。

实现方式：**选项 1 · 传统动态网站**（Flask + SQLite + Jinja 服务端渲染），SQL 全部手写并在服务端执行，不用 ORM 隐藏。

## 一、快速开始

```bash
# 1) 装依赖（仅 Flask）
python -m pip install flask

# 2) 重建数据库（解析文本快照 + 导入三源真实数据 + 模拟数据）
cd src
python parse_supply.py     # 供应清单文本 -> CSV（121 条）
python parse_catalog.py    # 医保目录解析 + 品种匹配（41 品种 / 76 条目）
python build_db.py         # 建表 + 导入 -> med_stat.sqlite

# 3) 启动
python app.py              # 默认 127.0.0.1:5000

# 4) 端到端测试（在库副本上跑，不动样本库）
python test_backend.py     # 期望：29/29 通过
```

> 数据快照已随仓库提供（`data/raw/*.txt`），无需联网即可复现建库。
> PDF→文本这一步如需重跑原始 PDF，可用 `pypdf` 或 WorkBuddy PDF 工具提取后覆盖 `data/raw/` 同名快照。

## 二、演示账号（口令统一 `meddemo`）

| 账号 | 角色 | 权限 |
|---|---|---|
| admin | 管理员 | 全部：检索 + 核验 + 增删改 + 标记失效 |
| hospital01 | 医院采购 | 只读：检索、核验、统计 |
| pharma01 | 药企合规 | 只读：检索、核验、统计 |
| researcher01 | 研究员 | 只读：检索、核验、统计 |
| （未登录） | 公众 | 只读公开页面 |

> SQLite 不支持 GRANT，"谁能写"由路由装饰器（`admin_required`）保证，"看什么"由 SQL 的 WHERE 控制。

## 三、数据来源与真实性（data_kind 区分）

| 数据 | 来源 | 性质 |
|---|---|---|
| 第九批集采中选/备供清单（121 条） | 联采办公告 PDF（天津医保局转载） | **真实** |
| 企业（99 家） | 同上清单提取 | **真实** |
| 医保目录条目（76 条，西药/星号条目） | 国家医保局 2023 版目录 PDF（187 页） | **真实** |
| 违规公告（珠海和凡取消资格、华北制药断供） | 联采办/省医保局公告 | **真实** |
| 公告（5 条，含来源 URL） | 联采办/国家医保局 | **真实** |
| 药品批准文号 approval_no | 模拟占位（待 NMPA/第三方批文库替换） | **模拟** |
| 供应省份 supply_province | 模拟抽样（真实应来自各省执行公告） | **模拟** |
| 用户账号 | 课程演示 | **模拟** |

真实核验点（无需编造）：
- **珠海和凡医药 · 吡拉西坦注射液**：第九批序号 16/17 仍"有效"，但 2024-11 已被取消中选资格 → 核验①检出矛盾。
- **西地那非、地夸磷索钠**：集采中选但 2023 版医保目录未收录 → 核验③检出。
- **卡泊芬净**：演示"目录内品种批文已注销"（drug.status 模拟置为注销）→ 核验②检出。

## 四、目录结构

```
med_stat.sqlite            数据库（9 表 + 3 视图）
src/
  schema.sql               DDL：主外键 / UNIQUE / CHECK / 索引 / 视图
  parse_supply.py          供应清单文本解析（跨行清洗 + 序号校验）
  parse_catalog.py         目录解析 + 品种匹配（通用名/核心名归一化）
  build_db.py              建库 + 导入 + 核验自检
  db.py                    连接与查询助手
  app.py                   全部路由 / 登录 / 角色装饰器 / 事务
  test_backend.py          端到端测试（29 项断言）
  templates/  static/      Jinja 模板与样式
docs/
  build_er.py              教材式 ER 图生成器（纯标准库）
  00_总览.svg 01_集采域.svg 02_核验域.svg
  ER图预览.html            三图预览（可打印 PDF）
  范式分析.md
data/
  raw/                     原始 PDF + 文本快照
  processed/               解析后的 CSV
```

## 五、功能拆解与实现位置

| 需求 | 功能 | 路由 / 函数 | 关键 SQL / 对象 |
|---|---|---|---|
| 检索与阅读 | 中选记录组合检索 | `GET /selected` `selected()` | 动态 WHERE + 省份 EXISTS 子查询 |
| 检索与阅读 | 中选详情（来源追溯+价格对比+目录匹配+违规命中） | `/selected/<id>` | v_selected_full + 多表 |
| 检索与阅读 | 医保目录检索 | `/catalog` | 药名 LIKE + 甲乙类 |
| 统计分析 | 企业中选数/均价 | `/manufacturers` `/stats` | LEFT JOIN + GROUP BY + HAVING |
| 统计分析 | 分布与排行 | `/stats` | GROUP BY remark/category/province |
| 交叉核验 | 违规 vs 中选 | `/verify` 板块① | v_violation_conflict（弱关联） |
| 交叉核验 | 目录 vs 批文 | `/verify` 板块② | v_catalog_no_approval（找空） |
| 交叉核验 | 集采 vs 目录 | `/verify` 板块③ | 核心名 NOT EXISTS |
| 交叉核验 | 同品种价格差 | `/verify` 板块④ | GROUP BY + MAX-MIN |
| 数据管理 | 中选记录增删改 | `/admin/selected/*` | 事务 + CHECK/UNIQUE 约束 |
| 业务流程 | 标记失效（核验闭环） | `/admin/selected/<id>/invalidate` | UPDATE status + 视图联动 |
| 用户与权限 | 登录 / 角色 | `/login` 装饰器 | pbkdf2 哈希 + admin_required |

## 六、已知边界（报告如实写）

1. **批文号为模拟**：NMPA 官方不可批量获取（逐条+验证码），当前 drug.approval_no 为占位；generic_name/core_name 为真实通用名。可替换为 GitHub `shi-yuan/nmpa-data` 子集。
2. **供应省份为模拟**：真实供应省份分散于各省医保局执行公告，当前抽样分配仅作演示，库内 `data_kind='模拟'` 标注。
3. **医保目录为子集**：只解析了本批集采品种涉及的西药条目（76 条），非全量 3088 条。
4. **权限在应用层**：SQLite 无 GRANT，行级可见性由应用层 WHERE 控制。
5. **名称匹配规则**：跨源匹配用"通用名去盐基/括号别名的核心名"互相包含，存在同名异物风险，已在 drug_match.csv 留台账供人工复核。
6. **安全**：课程演示，未加 CSRF、口令统一，勿直接部署公网。

## 七、AI 使用说明（大作业要求）

本项目由 WorkBuddy（AI 编程助手）辅助完成：ER 图设计、DDL、PDF 文本解析规则、Flask 路由与模板、测试用例均由 AI 生成初稿，再经人工核对真实数据来源与解析正确性（如盐基剥离误伤"硫酸镁"、目录星号条目同编号不同盐基等问题均为人工核对原文后修正）。
