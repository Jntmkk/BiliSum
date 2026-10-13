# 底层数据库支持 MySQL 评估

> 分支：`feat/mysql-support-eval` · 评估日期：2026-10-13
> 状态：**已按路线 B 实施完成**（SQLite / MySQL 双支持，不含数据库间数据迁移）。

实施摘要：

- `packages/infra/src/video_sum_infra/db.py`：新增 `open_database(url)` 按 scheme
  装配 `SQLiteSession` / `MySQLSession`；`rewrite_sql` 在 execute 时把
  repository 中的 SQLite 方言 SQL（`?` 占位符、`ON CONFLICT`、`OR IGNORE`、
  `julianday`、`COLLATE NOCASE`、`IS ?`、DDL 的 TEXT 主键/默认值等）翻译为
  MySQL 方言，方言差异集中在单一可测试函数内。
- `TaskRepository`（原 `SqliteTaskRepository`，保留别名）改为接受
  `DatabaseSession`，SQLite 行为不变。
- 依赖：`video-sum-infra` 增加 PyMySQL（纯 Python，桌面打包友好）。
- 测试：`tests/unit/test_db_dialect.py`（重写器覆盖 + repository 全 SQL
  静态守卫）；`tests/unit/test_task_repository_mysql.py`（真实 MySQL 集成，
  由 `VIDEO_SUM_TEST_MYSQL_URL` 门控）；CI `validate` job 增加 MySQL 8.4
  service container 跑集成测试。
- 迁移工具：`scripts/migrate_sqlite_to_mysql.py` 把既有 `video_sum.db`
  的 17 张表迁到 MySQL（源库只读打开、外键安全序拷贝、逐表行数校验、
  非空表默认拒绝覆盖，`--force` 可幂等合并）。已于 2026-10-13 将测试服务器
  （16MB / 约 2,060 行，含 253KB 大结果字段）完整迁入阿里云 RDS 并抽查通过。
- 已知取舍：保持"单连接 + 锁"的串行语义（与 SQLite 一致），连接池为后续项；
  `knowledge_index` 等 JSON 列在 MySQL 上映射为 `LONGTEXT`，id 列映射为
  `VARCHAR(191)`。

以下为原始评估内容，保留备查。

## 1. 现状

- DB 入口极薄：`packages/infra/src/video_sum_infra/db.py`（35 行），仅提供
  `connect_sqlite()` + `sqlite_cursor()` 事务上下文。
- **全部 SQL 集中在单一类** `SqliteTaskRepository`
  （`apps/service/src/video_sum_service/repository.py`，约 3100 行，约 237 处
  `cursor.execute`）。路由、知识库服务、worker 等只通过 repository 对象访问数据，
  没有第二处直连 SQL —— 这是支持 MySQL 的最大利好。
- 连接模型：单连接 + `check_same_thread=False` + 进程内 `threading.Lock`
  （SQLite 单写者模型）。
- 类型约定：时间统一存 ISO 字符串（TEXT），布尔存 INTEGER 0/1，JSON 存 TEXT。
- 迁移方式：`initialize()` 里手写 `CREATE TABLE IF NOT EXISTS` + `_ensure_column()`
  （`PRAGMA table_info` + `ALTER TABLE ADD COLUMN`）的滚动式迁移，无版本表。
- `database_url` 已是 URL 字符串（settings/database），加 `mysql://` scheme
  自然衔接。

## 2. SQLite 专有语法清单（需逐处移植）

| 位置（repository.py） | SQLite 写法 | MySQL 8 等价 | 难度 |
|---|---|---|---|
| 约 6 处 | `INSERT OR IGNORE` | `INSERT IGNORE` | 低（注意严格模式下 silent-ignore 语义） |
| 约 5 处 | `ON CONFLICT(...) DO UPDATE SET x = excluded.x` | `ON DUPLICATE KEY UPDATE x = VALUES(x)` | 低（MySQL 8.0.20+ 推荐别名写法，VALUES() 仍可用） |
| 1 处（L537） | `UPDATE OR IGNORE` | `UPDATE IGNORE` | 低 |
| L443 `_ensure_column` | `PRAGMA table_info` | `information_schema.COLUMNS` 查询 | 中（随迁移方案一并解决） |
| L427 启动回填 | `julianday(a) - julianday(b)` 算秒数 | `TIMESTAMPDIFF(SECOND, b, a)` | 低（一次性 backfill） |
| L427 | 多参数标量 `MAX(0, expr)` | `GREATEST(0, expr)` | 低 |
| L2127 | `WHERE parent_id IS ?`（参数化 NULL 安全比较） | `WHERE parent_id <=> ?` | 低 |
| L2113 | `ORDER BY parent_id IS NOT NULL` | `ORDER BY (parent_id IS NOT NULL)` | 低 |
| L2492 等 | 复合主键 `ON CONFLICT(video_id, tag)` | 需唯一索引支撑 `ON DUPLICATE KEY UPDATE`（schema 中已声明 PK，OK） | 已覆盖 |
| `db.py` 全文 | `sqlite3` API：`Row` factory、`rowcount`、`check_same_thread` | PyMySQL：dict cursor、`rowcount`、无线程限制 | 低-中（`rowcount` 在 3 处 UPDATE 上使用，MySQL 行为兼容） |

未发现 `RETURNING`、`json_extract`、CTE、窗口函数等更难移植的特性。
LIKE 查询仅 `_canonical_family_pattern` 的 `?p=%` 前缀匹配，两端均为 ASCII
case-insensitive 行为接近，风险低。

**数据类型注意点**：`knowledge_index.embedding_json` 存向量 JSON（TEXT）。
SQLite TEXT 无上限；MySQL TEXT 上限 64KB，1024 维 float 向量 JSON 约 8–15KB
目前够用，但建议 MySQL schema 用 `LONGTEXT` 兜底。其余列（TEXT/REAL/INTEGER）
与 MySQL 映射直接。

## 3. 三种实施路线

### 路线 A：方言翻译层（最小改动）
保留现有 `SqliteTaskRepository`，新增一个 dialect shim：按 URL scheme 选择
连接驱动，对约 10 类 SQL 惯用法做字符串/参数翻译（占位符统一 `%s`、
`OR IGNORE`/`ON CONFLICT` 重写、`julianday`→`TIMESTAMPDIFF` 等），迁移逻辑
按方言分支。

- 工作量：约 3–5 天 + 测试。
- 优点：改动面最小，SQLite 行为完全不变。
- 缺点：3000 行手写 SQL 类的技术债原样保留；字符串级翻译脆弱；
  `_ensure_column` 滚动迁移在 MySQL 上继续蔓延。

### 路线 B：Repository 接口 + 双实现
定义 `TaskRepository` Protocol（现有公开方法签名即接口），SQLite 实现保持
不动，新增 `MySqlTaskRepository`（可大量复用 SQL 文本，仅覆盖方言差异点）。
`app.py` 按 `database_url` scheme 装配。

- 工作量：约 1.5–2 周（含测试）。
- 优点：类型边界清晰，SQLite 路径零回归风险，CI 可对两库跑同一套
  repository 单测。
- 缺点：两份 SQL 文本需要长期同步维护。

### 路线 C：迁移到 SQLAlchemy Core + Alembic（治本）
用 SQLAlchemy Core 重写 repository 的 237 处语句，Alembic 接管迁移
（替换 `initialize()`/`_ensure_column`）。

- 工作量：约 2–4 周。
- 优点：一处代码多方言；连接池天然解决第 4 节的并发问题；迁移体系正规化。
- 缺点：重写面最大；桌面端（PyInstaller 打包）引入 SQLAlchemy 依赖与
  打包验证成本。

## 4. 非 SQL 层面的影响

1. **并发模型必须改**：当前"单连接 + 全局 Lock"在 SQLite 下合理，但放到
   网络数据库上会把 MySQL 的并发优势全部锁掉。至少改为按请求的短连接或
   小型连接池（PyMySQL 可手工池化，SQLAlchemy 自带池）。
2. **驱动选择**：推荐 **PyMySQL**（纯 Python，无 C 编译，对 PyInstaller
   桌面打包友好）；追求性能可后续换 mysqlclient。
3. **测试**：`tests/unit/test_task_repository.py` 等现用 SQLite；建议
   repository 单测参数化跑 SQLite + MySQL（GitHub Actions 起 MySQL 8
   service container）。
4. **用户数据迁移**：已有 SQLite 用户的升级路径（导出/导入或一次性
   `ATTACH`/ETL 脚本）需要另行设计，不属于本次方言适配范围。
5. **配置面**：`database_url` 已存在，仅需文档补充 MySQL DSN 格式与
   新建库/字符集要求（`utf8mb4`）。

## 5. 建议

- **短期目标（快速可用 MySQL）→ 路线 B**：接口清晰、风险可控，两周内
  可交付，且为路线 C 留出接口层。
- **长期维护（如果确定多库是常态）→ 路线 C**：方言差异与迁移问题一次
  性根治。
- 不建议路线 A：翻译层在 3000 行 SQL 上的长期维护成本高于它省下的
  初期工作量。
- 无论哪条路线，第 4.1（连接池）都是必须项，不是可选项。
