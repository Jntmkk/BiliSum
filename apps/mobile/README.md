# BiliSum Mobile

BiliSum 的移动端（iOS / Android），React Native + Expo 实现。纯 UI 表现层——解析、转写、总结、知识库存储等全部业务逻辑由 [BiliSum 服务](../service)完成，移动端只负责调用其 HTTP API。

## 功能范围

- **任务**：列表 + 状态（进行中/已完成/失败），进行中自动轮询进度，下拉刷新
- **新建**：粘贴 B 站 / YouTube 链接 → 解析 → 多 P 选集 → 提交总结任务
- **详情**：摘要（markdown）、章节时间轴、转写全文 三个页签
- **我的**：服务器地址设置

不在移动端实现：思维导图、图文笔记、知识库问答、本地视频上传、账号登录（B 站扫码登录请在桌面端 / Web 完成，cookie 由服务端维护）。

## 前置要求

1. 一台运行中的 BiliSum 服务（桌面端启动，或单独跑 `video-sum-service`），默认端口 `3838`
2. 手机和服务在同一局域网（或部署了公网可达的服务）
3. Node.js ≥ 20

## 快速开始

```bash
cd apps/mobile

# 安装依赖（锁文件为 pnpm-lock.yaml，推荐 pnpm）
pnpm install

npm run start      # 启动 Expo 开发服务器
```

然后用 **Expo Go** App（iOS/Android 应用商店下载）扫描终端里的二维码，即可在真机上运行。

## 连接服务

首次打开 App：

1. 切到「我的」Tab
2. 填写服务地址，例如 `http://192.168.1.10:3838`（填运行服务的机器的局域网 IP）
3. 保存后回到「任务」Tab 下拉刷新

> 若服务端开启了 access token（`VIDEO_SUM_ACCESS_TOKEN`），暂通过 API 请求头支持，后续在「我的」页补充 UI。

## 常用命令

| 命令 | 说明 |
|---|---|
| `npm run start` | 启动 Expo dev server |
| `npm run android` / `npm run ios` | 连接模拟器运行 |
| `npm run typecheck` | TypeScript 检查 |
| `npm run gen:api` | 从运行中的服务 `/openapi.json` 重新生成 API 类型 |

## API 类型生成

`src/api/types.ts` 由 [`scripts/gen-api-types.mjs`](scripts/gen-api-types.mjs) 从服务端 OpenAPI 规范生成。当前仓库中的类型是手写对齐的精简版，如需全量类型：

```bash
SERVER_URL=http://192.168.1.10:3838 npm run gen:api
```

服务端 schema 变更后重新执行即可。

## 技术栈

- Expo SDK 57 / React Native 0.86 / React 19
- [expo-router](https://docs.expo.dev/router/introduction/) 文件式路由
- [@react-native-async-storage/async-storage](https://github.com/react-native-async-storage/async-storage) 本地设置持久化
- [react-native-markdown-display](https://github.com/iamacup/react-native-markdown-display) 摘要渲染

## 已知限制

- 笔记中的 KaTeX 数学公式显示为原始 `$...$` 文本（RN 生态暂无成熟方案）
- 时间轴时间点不支持跳转播放
