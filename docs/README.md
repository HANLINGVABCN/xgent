# XGent 文档

[返回项目首页](../README.md)

项目首页负责安装和功能概览。这里按用途组织使用说明、行为约定、实现记录及历史资料。

## 使用与配置

| 文档 | 内容 |
| --- | --- |
| [操作参考](usage-reference.md) | 安装与维护命令、Telegram／CLI 菜单、TUI 操作、工具和提示词 |
| [模型输入与容量](model-inputs.md) | 提供商选择、媒体参考文件、原生输入范围和模型容量配置 |
| [上下文与对话导出](context-and-export.md) | 记忆深度、工具结果留存、压缩流程和导出文件结构 |
| [工具调用双模式](tool-call-mode.md) | Tool call 与正则围栏的配置、请求、历史和兼容规则 |
| [品牌与头像](web-branding.md) | 自定义名称、头像预览、保存与同步；预设顺序以当前外观页为准 |

## 对话、文件与消息

| 文档 | 内容 |
| --- | --- |
| [新对话延迟保存](new-conversation.md) | 空白页、首次发送、附件接收和失败重试 |
| [多对话与同步](multi-conversation.md) | 独立选择、上下文隔离、跨端投递与导出；历次迁移版本按记录时点描述 |
| [分支与子对话](child-conversations.md) | 父子归属、后台助手和结果回传 |
| [归档分组](archive-group.md) | 隐藏归档列表、归档内对话、父子恢复和原分组保存 |
| [消息队列](message-queue.md) | 同对话排队、安全接入、取消、取回和恢复 |
| [附件排队](attachment-queue.md) | 生成中带文件入队、草稿恢复和原件关联 |
| [附件版本与恢复](attachment-versions.md) | 原件、当前版本、历史版本和恢复校验 |
| [文件入口与传输](file-ingress.md) | 附件／仅路径上传、多文件、Telegram 限制和分块续传 |
| [页面渲染](rendered-pages.md) | SVG／HTML 实时预览、独立完成、源码视图和 Telegram Web App |
| [全局搜索](global-search.md) | 跨对话查找、筛选与来源定位 |
| [连续命令折叠](command-series.md) | 多轮命令的展示、展开、停止与统计 |
| [通知、撤回与输入同步](notification-and-input-sync.md) | 陌生访问提醒、准确撤回、服务器附件草稿和跨端恢复 |

## 安全、数据与运维

| 文档 | 内容 |
| --- | --- |
| [访问安全与登录设备](web-access-security.md) | IP 记录、失败等待、封禁解除、黑白名单和设备踢下线 |
| [两步验证与恢复](web-two-factor.md) | TOTP、恢复码、Telegram 免密入口和跨重启登录 |
| [数据管理与迁移](data-management.md) | 数据目录、备份范围、定时导出、分组恢复和回退 |
| [Telegram 备份](bot-backups.md) | Bot 原生导入导出、压缩格式及凭据保留 |
| [文件与任务来源](workbench-sources.md) | 来源定位、文件读取范围、任务筛选和管理接口 |

## 架构与实现记录

| 文档 | 内容 |
| --- | --- |
| [架构](architecture.md) | 入口、共享兼容层与各模块职责 |
| [可靠执行](reliable-execution.md) | 工具分派、执行结果和续接语义 |
| [前端重写](frontend-rebuild.md) | 对话／设置结构、功能基线与验证范围 |
| [设置响应与排版](web-settings-responsiveness.md) | 区域加载、配置同步、缓存和排版 |
| [聊天与附件可靠性](chat-attachment-reliability.md) | 缺件、长历史、阅读状态和原件预览 |
| [Web 与 Telegram 同步](web-telegram-sync.md) | 生成媒体投递、消息关联与撤回 |
| [Telegram 生成状态](telegram-generation-status.md) | 前台、后台、非流式进度与停止生命周期 |
| [Telegram 原生能力接入](telegram-native-upgrade.md) | 富文本、草稿和话题能力的接入记录 |

## 历史资料与设计草案

这些文件记录当时的版本、问题或计划，不作为当前安装步骤。旧路径、部署名称和迁移版本不能直接套用到新实例；当前入口与部署方式见[项目首页](../README.md)。

| 文档 | 类型 |
| --- | --- |
| [聊天控制更新](chat-controls-update.md) | 历史升级与验证记录 |
| [Web 工作界面发布记录](web-workbench-release.md) | 历史改版范围 |
| [2026-10-31 Bot 修复](bot-repair-20261031.md) | 当时的故障与修复记录 |
| [已知问题调查](known-issues.md) | 旧部署的排障笔记，部分结论尚未确认 |
| [Telegram 能力调研](telegram-capabilities-review.md) | 接口调研及当时的接线计划 |
| [群聊模式设计](group-chat-mode-design.md) | 设计草案，不表示已实现 |
| [v0.1.0 发布草稿](release-draft-v0.1.0.md) | 历史发布文案，不表示当前版本号 |
| [发布准备](launch-kit.md) | 仓库介绍、演示与发布资料 |
