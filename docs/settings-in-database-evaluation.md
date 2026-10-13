# 配置入库（Settings-in-Database）评估

> 分支：`feat/mysql-support-eval` · 评估日期：2026-10-13
> 状态：**已实施完成**（v1：单行 JSON 存储 + 文件种子 + 实例本地字段强制 +
> 多实例 TTL 版本刷新）。

实施摘要：

- `apps/service/src/video_sum_service/settings_store.py`：`SettingsStore` 接口 +
  `FileSettingsStore`（原子写，原行为）+ `DbSettingsStore`（惰性连接、单行
  `settings` 表、SQL 侧 version 自增）；`create_settings_store` 按
  `database_url` scheme 选后端（MySQL→库，其余→文件）。
- `SettingsManager` store 化：文件种子自动导入 DB（配置随 SQLite→MySQL 迁移
  自动跟过来）；实例本地字段（data/cache/tasks 目录、database_url、host、port）
  在 DB 模式下强制取本机环境；`current` 每 5s 探 version，跨实例改动自动生效
  （纯内存刷新，不触发 worker 重建——重建仍由写入实例执行）。
- 连带修复一个真实 bug：`MySQLSession.execute`（辅助读连接）SELECT 后不
  commit，autocommit=off 下元数据锁长期持有，曾永久阻塞其他会话的
  `CREATE DATABASE`；已加 commit + connect_timeout=10。
- 测试：`tests/unit/test_settings_store.py`（内存 SQLite 覆盖双后端/种子/掩码/
  TTL）、`tests/unit/test_settings_mysql.py`（RDS 集成：往返/共享/密钥掩码），
  已挂入 CI MySQL job。
- 已上线验证：隧道测试环境（http://120.26.16.8:3000）配置迁入 RDS
  `video_sum.settings`，经公网 API 保存 → version 递增 → 新实例读到了共享配置。

以下为原始评估内容，保留备查。

## 1. 现状

- **模型**：`ServiceSettings`（pydantic，infra/config.py，约 120 个字段），环境变量前缀
  `VIDEO_SUM_`，支持 `.env`。
- **存储**：`{data_dir}/settings.json` 单文件，**文件值覆盖环境变量**
  （`{**base, **stored}` 合并，stored 胜出）；保存为临时文件 + rename 原子写。
- **读取面**：`settings_manager.current` 在约 15 个模块被实时读取（worker、LLM/ASR
  集成、知识库、路由等），全部进程内缓存，启动时加载一次。
- **写入面**：唯一入口 `PUT /settings` → `settings_manager.save()`（内存合并 +
  整体写回 + 密钥掩码保护： masked 值不覆盖已存密钥）。保存后有重副作用：
  重建 task worker、runtime channel bootstrap、环境探测缓存清理——**隐含单实例假设**。
- **版本机制**：`settings_schema_version` + 一次性迁移（retry 默认值等）。
- **不入库的周边**：`auth.json`（访问令牌）、bilibili cookies 文件、prompt presets
  文件——均为本机态，无共享需求。

## 2. 动机与收益

MySQL 部署的真实驱动力是多实例/共享存储；此时配置仍按实例放在各自文件里，
出现"数据在库里、配置在文件里"的分裂（本次测试环境即手动复制 settings.json
解决）。入库后：改一处配置全体实例生效，与 DB 双支持的目标一致。

## 3. 方案设计

### 存储形态（推荐：单行 JSON）

`settings` 表单行列：`settings_json LONGTEXT + version BIGINT + updated_at`。
保存 = 内存合并后整体 UPDATE（与现有 save() 语义完全同构），读取 = 单行 SELECT。
键值对逐行方案粒度更细但与现有"整体对象 + 部分更新 API"不匹配，徒增复杂度。

### 后端抽象

```
SettingsStore (接口: load() / save(json) / version())
├─ FileSettingsStore   # 现状，原样保留
└─ DbSettingsStore     # 经 open_database 的 DatabaseSession 读写
```

按 `database_url` scheme 选择：**SQLite → 文件（桌面/单机零变化）；MySQL → 库**。
与方言层同一装配风格。`SettingsManager` 只依赖 store 接口，save() 的合并/掩码/
迁移逻辑零改动。

### 优先级

`环境变量 > DB > 文件(仅作首次种子) > 内置默认`。种子规则：DB 无该实例的行时，
用本地 settings.json（若存在）初始化——覆盖"从 SQLite 迁到 MySQL 后配置跟过来"
的场景（本次测试环境的手工操作将自动化）。

### 多实例传播（核心难点）

进程内缓存意味着实例 A 保存后实例 B 仍用旧值，且 B 的 task worker 不会重建。
选项：

| 方案 | 说明 | 评价 |
|---|---|---|
| A. 启动时加载 + 文档声明"改配置需重启其他实例" | 零成本 | 对本应用规模（单用户、个位数实例）**可接受**，建议 v1 就用它 |
| B. version 列 + TTL 刷新（如 5s） | `current` 访问时若缓存超龄则 `SELECT version` 比对，变了才重载 | 增量成本约 1 天，可作为 v1.5；注意刷新只更新内存，不触发 worker 重建（由下一次任务调度自然生效） |
| C. MySQL 通知 | 无 LISTEN/NOTIFY，只能靠轮询/binlog，不值 | 不推荐 |

### 密钥安全

API 密钥随库共享后，安全边界从"本机文件权限"变为"数据库访问控制"：

- API 回显掩码（现有 `******` 机制）原样保留；
- 建议实例用最小权限账号（只授目标库权限，不开 super）；
- 阿里云 RDS 可开 TDE 静态加密，需要时一行配置；
- 字段级加密可作后续增强（主密钥仍回文件），v1 不做。

### 启动顺序

`settings_manager` 在 import 期构造，而 DB session 在 lifespan 里才打开。
DB store 需要**惰性连接**（首次 load/save 时才 `open_database`），或把
settings 初始化挪进 lifespan。推荐惰性 store，避免牵动 app 装配。

## 4. 工作量与风险

| 项 | 估时 |
|---|---|
| SettingsStore 抽象 + DbSettingsStore（含 DDL/方言重写兼容） | 2–3 天 |
| 装配与启动顺序（惰性连接、scheme 选择、种子导入） | 1–2 天 |
| 多实例 TTL 刷新（若做） | 1 天 |
| 测试（文件/DB 双后端单测 + MySQL 集成 + save 副作用回归） | 2–3 天 |
| 文档 | 0.5 天 |
| **合计** | **约 1.5–2 周** |

风险（均可控）：

1. **保存副作用的单实例假设**（worker 重建/runtime bootstrap）——只让写入实例执行，
   其余实例 TTL 刷新纯内存生效；需在 update_settings 里明确语义。
2. **存量行为回归**——settings 相关测试面大（多个 API 测试经 settings_manager.save），
   文件后端必须零变化。
3. **密钥入库的接受度**——单用户自用场景风险有限，文档需写明边界。

## 5. 结论与建议

- **若多实例是真实需求**（当前 MySQL 部署的方向）：值得做，按上表方案，
  v1 = 单行 JSON + 文件种子 + 环境变量最高优先 + "改动实例即时生效、其余实例重启生效"；
  TTL 刷新列为快速跟进。
- **若只是单机/桌面使用**：不建议做，文件方案的简单性是优势。
- 与 MySQL 方言支持本身解耦，可独立成分支开发；复用 `open_database` 与方言重写，
  无需新的 SQL 方言工作（单行读写 SQL 均为双方言通用）。

**建议**：把本评估与方言支持分支一并提交后，按真实使用反馈决定是否立项；
短期运维痛点（配置跟迁移）已有手动解法，不阻塞。
