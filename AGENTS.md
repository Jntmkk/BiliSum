# BiliSum 项目指南（面向 AI Agent / 贡献者）

## CI 与发布规则

### 提交信息约定（Conventional Commits）

普通提交不会触发发版。只有带标记的提交会：

| 标记 | 效果 |
|---|---|
| `feat*:` / `fix*:` / `perf*:` / `refactor*:` | 触发自动发版检测（feat→minor，其余→patch） |
| `feat!:` / `fix!:` 或 footer `BREAKING CHANGE:` | major 版本 |
| 普通 `feat:` / `fix:` / `ci:` / `docs:` / `chore:` | 不发版 |
| 提交信息含 `[skip ci]` | 跳过 CI（Release 版本 bump 提交自带） |

检测逻辑见 `scripts/detect_bump.py`（`should_release_commit`）。

### 自动化发布链路

```
push 带 * 标记的提交到 master
  → CI 运行
  → Prepare Release 自动开 "Release vX.Y.Z" PR
  → 基线提交 CI 绿 → auto-merge-release-pr.yml 自动 squash 合并
  → create-release-tag.yml 自动打 tag vX.Y.Z
  → release.yml 构建 Windows/mac 安装包并创建 GitHub Release
  → Release 发布事件触发 publish-docker-image.yml 推送 Docker 镜像
```

如需手动发版：Actions → "Prepare Release" → Run workflow → 填 `patch` / `minor` / `major` 或显式版本号（如 `1.22.0`）。

### Docker 镜像发布（`publish-docker-image.yml`）

镜像仓库：`bbmike253/bilisum`（Docker Hub）。

| 触发方式 | 推送的 tag |
|---|---|
| push 到 master | `edge` |
| GitHub Release 发布（自动） | `vX.Y.Z`、`X.Y.Z`，稳定版另加 `latest`；预发布不动 `latest` |
| 手动 Run workflow 填 release_tag | 同上 |

### Workflow 一览

| Workflow | 作用 |
|---|---|
| `ci.yml` | 测试 + 类型检查 + Docker 镜像构建验证（不推送） |
| `prepare-release.yml` | 检测可发版提交，开 Release PR |
| `auto-merge-release-pr.yml` | Release PR 基线 CI 绿后自动合并 |
| `create-release-tag.yml` | Release PR 合并后打 tag |
| `release.yml` | 构建安装包、创建 GitHub Release |
| `publish-docker-image.yml` | 构建并推送 Docker 镜像 |
| `release-pr-updater.yml` | 更新 Release PR 的发布说明 |
| `publish-npx-package.yml` | 发布 npx 包（需 `NPM_TOKEN`，手动） |
| `label-sync.yml` | 同步 issue labels |

### 必需的仓库 Secrets

- `PAT_TOKEN`：带 repo 写权限的 PAT，用于打 tag、开/合并 PR（`GITHUB_TOKEN` 推送不会触发后续 workflow）
- `DOCKERHUB_TOKEN`：Docker Hub Access Token；用户名默认 `bbmike253`，可用仓库变量 `DOCKERHUB_USERNAME` 覆盖

## 开发环境

- 后端：`.venv/bin/python -m video_sum_service`（默认 `127.0.0.1:3838`，editable 安装，改代码重启即生效）
- 桌面端：`cd apps/desktop && npm run dev`（vite 热更新 + Electron）
- 后端单测：`pytest tests/unit`；桌面端：`npm test` / `npm run typecheck`（apps/desktop 下）
- Web 静态资源构建产物（`apps/web/static/assets/index-*`）随提交入库，桌面端 `npm run build:renderer` 会重建
