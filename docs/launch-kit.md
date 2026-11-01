# 项目发布素材

这里集中保存 GitHub 仓库设置、演示录制和社区发布时可直接复制的文案。

## GitHub About

### Description（推荐）

```text
XGent：以 Web 为主要入口的自托管私人 AI Agent，支持多模型、长期记忆、文件处理与真实 Shell，保留 Telegram 和 CLI 接入。
```

### English Description

```text
A self-hosted private AI agent centered on a Web workspace, with multi-model chat, memory, files and real shell tools, plus Telegram and CLI access.
```

### Topics

```text
ai-agent
web-ui
self-hosted
telegram-bot
llm
python
openai
claude
gemini
linux
server-management
devops
personal-assistant
```

### Website

暂时没有独立网站时，可以留空，或填写仓库 README/文档站地址。不要为了填满字段而使用无内容的页面。

## Social Preview 设计稿

建议尺寸：`1280 × 640`。

主标题：

```text
XGent · 私人 AI Web 工作界面
```

副标题：

```text
Self-hosted · Multi-model · Memory · Files · Real Shell Agent
```

画面建议：以 Web 对话、折叠执行块和浏览器终端为主，补充一张 Telegram 同步消息的小图。移动端缩略图中应仍能看清 XGent 主标题。

## 30 秒演示脚本

录屏前准备一台无敏感数据的演示服务器，并隐藏 Token、API Key、IP 和用户名。

1. **0～3 秒**：展示 Web 会话列表与对话界面。
2. **3～8 秒**：发送“检查磁盘和内存状态，找出最大的日志目录”。
3. **8～18 秒**：展示 Agent 执行状态和命令结果陆续返回。
4. **18～24 秒**：让 Agent 生成 `server-report.md`。
5. **24～28 秒**：在 Web 下载报告，展示同一会话的 Telegram 同步结果。
6. **28～30 秒**：结束画面显示“XGent · Your private AI workspace”和仓库名。

建议同时导出：

- README 使用的短 GIF：15～20 秒、尽量小于 10 MB；
- 社区发布的视频：30～45 秒、MP4；
- 3 张静态截图：Web 会话、Agent 执行、文件下载。

## 社区发布长文案

### 标题

```text
XGent：在网页里使用自己的私人 AI Agent，处理文件与服务器任务
```

### 正文

```text
最近做了一个自托管私人 AI Agent，名字叫 XGent。

Web 是主要工作界面，可以管理模型与对话、查看思考和执行过程、处理文件并使用浏览器终端。开启 Agent 后，可以在授权服务器上执行命令、查看日志和读写文件；Telegram 和 CLI 继续共用同一套模型、记忆与工具服务。

目前支持：
- OpenAI / Claude / Gemini / Vertex / OpenAI 兼容接口
- Web 对话、会话分组、文件、任务、用量统计与浏览器终端
- Tool call／正则围栏两种调用方式
- SQLite 全局记忆
- 文件、图片和贴纸上下文
- 一次性命令与长驻 Shell 会话
- 对话模型和媒体模型分别配置
- Skill 扩展
- 提供商配置导入导出

项目面向单用户私有部署，需要自己的 Linux 服务器和模型 API Key。Web 可独立部署；接入 Telegram 时再配置 Bot Token 与授权用户 ID。Agent 按运行账号权限执行，建议使用独立低权限用户。

如果你平时会维护 VPS、家庭服务器或者开发机，欢迎试用并告诉我最想让它完成什么任务。
```

## 社区发布短文案

```text
XGent 是以 Web 为主要入口的自托管私人 AI Agent：支持多模型、长期记忆、文件、媒体生成与真实 Shell；Telegram 和 CLI 保留原生接入与会话同步。适合 VPS、家庭服务器与开发机。
```

## 发布前清单

- [ ] GitHub About 填写 Description
- [ ] 添加 Topics
- [ ] 上传 Social Preview
- [ ] README 顶部放真实 GIF 或截图
- [ ] 创建 `v0.1.0` 标签和 Release
- [ ] 确认 GitHub Actions 全部通过
- [ ] 在一台干净 Linux 服务器验证安装
- [ ] 验证 `/update` 与回滚/备份路径
- [ ] 检查录屏中没有 Token、Key、IP 或个人信息
- [ ] 开启 Issues，并准备一个用于收集安装问题的 Issue

## 首批用户反馈问题

不要只问“好不好用”，优先问：

1. 你在哪一步差点放弃安装？
2. README 第一屏让你以为它是做什么的？
3. 你最想在 Web 工作界面里完成哪三件事？哪些任务更适合通过 Telegram 或 CLI 发起？
4. 哪个权限或安全问题最让你担心？
5. 如果明天不能再用，你最舍不得哪个能力？
