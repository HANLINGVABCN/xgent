<p align="center"><img src="xgent_app/webui/assets/logo.svg" alt="XGent" width="88" height="88"></p>

# XGent

**部署在自己服务器上的私人 AI 助手，以 Web 为主要入口，支持 Telegram 和本地终端。**

在同一个项目里聊天、处理文件、生成媒体、运行命令和管理后台任务。三个客户端共用对话引擎、模型配置与数据库，各自选择当前对话；可以单独部署，也可以组合使用。

<p>
  <a href="https://github.com/HANLINGVABCN/xgent/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/HANLINGVABCN/xgent/actions/workflows/tests.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-yellow.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white">
</p>

[快速安装](#快速安装) · [开始使用](#开始使用) · [主要功能](#主要功能) · [安全与登录](#安全与登录) · [更新与备份](#更新与备份) · [完整文档](docs/README.md)

> [!IMPORTANT]
> Agent 工具和网页终端使用运行账号的真实系统权限，项目不提供执行沙箱。命令黑名单只能拦截匹配的片段。建议使用独立、低权限账号部署；网页登录防护和页面预览沙箱不会隔离 Agent 的服务器操作。

## 快速安装

建议在 Linux 或 WSL 中部署。需要 Python 3.11+、Git、curl 和可用的模型接口。安装脚本可在 Debian／Ubuntu 上补齐系统依赖；其他发行版需先自行安装 Python、pip 和 venv。

```bash
git clone https://github.com/HANLINGVABCN/xgent.git
cd xgent
chmod +x install.sh
./install.sh
```

按菜单完成环境安装、选择保活方式，再选择需要的组件。安装后可以重新运行脚本，添加、配置或移除组件。

| 组件 | 入口 | 需要配置 |
| --- | --- | --- |
| Web | 浏览器 | 访问密码；默认端口 `8790` |
| Telegram Bot | Telegram 私聊 | [BotFather](https://t.me/BotFather) 提供的 Bot Token、你的 Telegram 用户 ID |
| CLI | 服务器终端中的 `xgent` 命令 | 无需 Web 密码或 Telegram Token；模型可在终端菜单配置 |

三个组件可任意组合。没有 Bot Token 时，Web 仍能独立聊天、管理提供商和模型、使用工具、表单、备份及后台任务。

Telegram 普通聊天里收到图片、文件或音视频，会先保存并加入已有拼接；继续发送的文字和附件都加入同一批，点“发送”才交给 AI。正在回答时也能接收，手动提交后由原有队列等待；提交成功会删除拼接提示，保留原消息与文件，AI 正常接着回答。

Web 默认只监听 `127.0.0.1`。同机浏览器打开 [http://127.0.0.1:8790](http://127.0.0.1:8790)。从其他电脑访问，可使用 SSH 转发：

```bash
ssh -N -L 8790:127.0.0.1:8790 user@server
```

将 `user@server` 换成服务器账号与地址，然后在本机浏览器打开同一个地址。需要公网入口时，自行配置 HTTPS 反向代理，并在「设置 → Web 与安全」填写公开地址；Telegram Web App 按钮需要 HTTPS。

安装与维护命令见 [操作参考](docs/usage-reference.md#安装与维护)。

## 开始使用

1. 登录网页，进入 **设置 → 模型与技能 → 模型提供商**，添加接口地址、API Key 和模型。
2. 可以用当前表单的连接信息拉取候选模型；选入列表后保存配置。
3. 选择一个模型，点击 **用于对话**。需要生图或媒体编辑时，再选择 **用于媒体**；两者可以不同。
4. 回到对话，发送文字或附件。点击“新对话”只打开空白页，首次发送被保存后才创建记录和对话地址。
5. 需要执行服务器任务时，在 Agent 设置中开启工具，并检查账号权限、提示词与命令黑名单。

提供商卡片上的“当前对话”和“当前媒体”会显示已经生效的模型。只改变候选下拉框不会切换实际模型。

Telegram 发送 `/start` 打开菜单；CLI 运行 `xgent`，也可通过 `/providers`、`/models` 和 `/media_model` 完成配置。完整命令见 [操作参考](docs/usage-reference.md#对话与管理命令)。

## 主要功能

| 功能 | 当前支持 |
| --- | --- |
| 对话管理 | 分组、搜索、置顶、分支、子对话、归档恢复、导出、撤回及历史分页 |
| 文件与附件 | 图片和全文文本输入、仅路径上传、混合文件队列、分块传输、原件与版本恢复 |
| 模型与媒体 | OpenAI、OpenAI 兼容接口、Claude、Gemini、Vertex；对话与媒体模型独立选择 |
| Agent 工具 | 命令执行、交互终端、文件读写、代码分析、联网搜索、网页抓取、文件交付和表单 |
| 后台任务 | 延时、指定时间、cron、条件监控与子对话任务，结果回到来源对话 |
| 页面渲染 | 普通回复中的 SVG／HTML 实时预览，支持 CSS 动效、完成后的 JavaScript 交互及源码查看 |
| 上下文与记忆 | 记忆深度、工具结果留存、手工记忆、上下文压缩和完整对话导出 |
| 用量统计 | 按模型和日期查看 Token 用量、费用配置与调用明细 |
| 外观 | 六套独立主题及明暗模式、字号、品牌名称与头像库；主题和头像分别选择 |
| 安全与维护 | 登录设备管理、IP 访问记录及封禁、黑白名单、可选两步验证、更新与实例备份 |

### 对话与跨端同步

Web 界面只有 **对话** 和 **设置** 两个主要区域。任务、文件、模型、用量、安全、备份及归档集中在设置中。

不同对话可同时生成，同一对话的输入按顺序处理。生成中可以继续发送文字和附件，尚未接入的消息可取消或取回编辑。停止、异常和队列暂停只影响对应对话。

Web 标签页、Telegram 和每个 CLI 进程独立选择对话。网页浏览其他对话不会替 Bot 换上下文；侧栏的“设为 Bot 当前对话”是明确的切换操作。同步遵守来源对话与 Bot 选择，不会把其他对话自动加入模型上下文。

三端共用“流式／非流式”开关，在任一端修改后其他端跟随。流式时网页与 CLI 实时显示；Bot 使用后台流式，每约 3 秒分批刷新正文，完成后立即补齐，限流时按 Telegram 要求延后刷新。非流式等待模型完整返回。旧版独立的网页和 Bot 模式合并为同一开关，升级沿用原 `stream_mode`；正在运行的回合保持开始时的方式，下一个新回合使用新设置。

网页点击“新对话”时，列表先显示一条临时对话，可从它的菜单设为 Bot 当前。未发送消息不创建对话记录，刷新会移除临时行，发送首条消息后才保存。如果已设为 Bot 当前，网页或 Telegram 的首次发送会创建同一个正式对话；已明确设置的 Bot 选择不因网页刷新而撤销。

归档入口在 **设置 → 已归档**。归档对话可以继续聊天和建立子对话，名称固定、不能新建分支。父对话恢复时子对话一起恢复，保留原分组信息并自动进入父对话。

普通对话共享项目文件目录；分支有自己的文件快照与目录。它们都不是系统权限沙箱。

[多对话与同步](docs/multi-conversation.md) · [消息队列](docs/message-queue.md) · [附件排队](docs/attachment-queue.md) · [分支与子对话](docs/child-conversations.md) · [归档](docs/archive-group.md)

### 附件、服务器上传与媒体

| Web 文件入口 | 交给 AI 的内容 |
| --- | --- |
| 附件 | 图片作为图片输入，文本文件提供全文；其他类型按能力提供路径与文件信息 |
| 上传 | 只提供服务器路径，不声称模型已读取文件内容 |

两种入口都保存文件，可以混合发送，也可以在生成中入队。文件是否同步到 Telegram，取决于 Bot 配置、对话路由及平台大小限制；Telegram 投递失败不会撤销 Web 已接收的文件。

当前有效附件与普通文本历史深度分别处理。上传文件被修改后，下一次请求读取当前内容；工具读取的冻结副本保留当时版本。新普通上传保存独立原件及最近版本，可查看、下载和确认恢复。

媒体生成或编辑使用独立媒体模型，可显式提供服务器上的参考文件。接口和模型支持的输入范围不同，详见 [模型输入与容量](docs/model-inputs.md)。

[文件入口](docs/file-ingress.md) · [附件版本](docs/attachment-versions.md) · [缺件处理](docs/chat-attachment-reliability.md)

### 实时 SVG／HTML 页面

AI 可以在正常回复中输出 `xgent-svg` 或 `xgent-html` 代码块。网页随已写出的图形、HTML 和 CSS 逐步预览；每一块完成后独立启用完整交互，不等待后面的代码块或整条回复结束。

这是回复格式，不计作 Agent 操作，不增加执行轮次，也不会为渲染多调用一次模型。预览可展开，尖括号按钮切换源码，返回预览时保留页面内状态。

Telegram 将同一份源码折叠显示；超限时明确标注节选并附完整源码。有公开 HTTPS 网页入口时，Web App 按钮打开同一份页面。

页面使用隔离 iframe，只允许自包含资源；无法读取宿主对话、Cookie、网络或本地文件。生成中的脚本保持静止，完成后才运行。每条回复最多四块，每块不超过 256 KiB。

[页面格式与限制](docs/rendered-pages.md)

### 工具、表单与后台任务

新实例默认使用 **Tool call**，也可选择 **正则围栏**。两种方式调用同一套执行服务；正在运行或等待表单的回合保持开始时的模式，修改影响下一次请求。

工具可以执行命令、读写文件、分析代码、调用媒体模型和向用户提问。写文件只写盘；要交付原件，需使用文件发送工具。联网搜索需要配置 Tavily API Key。

网页把执行命令与对应输出放在同一个块内。顶部控制整个块，收起时命令和输出一起隐藏；展开后，内部命令正文与输出各自折叠，可以收起长命令直接阅读结果。输出只有点击后才从后台分页读取，重复命令也按独立执行记录对应。复制、完整下载、执行详情和运行中的停止按钮均保留，Telegram 与 CLI 继续沿用各自原有显示。

表单支持单选、多选、文本与私密字段。Web、Telegram 和 CLI 使用各自的输入界面，提交后恢复原回合。后台任务按创建时的对话保存，查看任务不会切换当前聊天。

[工具双模式](docs/tool-call-mode.md) · [工具名称参考](docs/usage-reference.md#工具与提示词) · [后台任务与子对话](docs/child-conversations.md)

### 上下文、压缩与导出

这些操作的作用不同：

| 操作 | 作用 |
| --- | --- |
| 记忆深度 | 调整普通模型可见消息窗口，不删除聊天历史 |
| 工具结果留存 | 保留实际回传的工具结果，关闭不删除已经留存的内容 |
| `/clear` | 开启新的模型上下文阶段，保留可见历史、附件记录和任务 |
| `/compress` | 先备份，再用成功保存的摘要替换有效上下文；失败或停止保留原上下文 |
| `/export` | 导出当前对话完整记录、压缩链和上下文阶段；不代替实例备份 |
| 归档 | 移入隐藏归档分组，保留对话；恢复后继续使用 |

压缩摘要不能保证语义绝对无损，因此始终保留原文与备份。附件原件不包含在普通对话记忆 ZIP 中，需要整套迁移时使用实例备份。

[上下文与对话导出](docs/context-and-export.md) · [实例数据与恢复](docs/data-management.md)

## 安全与登录

Web 登录默认在正常使用中自动续期，连续 30 天未使用才需要重新登录，普通更新与 PM2 重启保留有效登录。可在 **设置 → Web 与安全 → 已登录设备** 修改有效期（1–365 天）、关闭自动续期、查看设备与当前到期时间，踢出指定设备或其他设备；密码、两步验证或授权身份变化仍会撤销旧登录。

网页访问保护默认连续认证失败五次后等待三分钟，等待结束再失败三次即封禁关联 IP 和设备。规则可修改，页面说明随当前输入更新，保存后生效。后台可查看访问次数、失败次数、封禁名单和 IP 黑白名单。

网页陌生访问与 Telegram 未授权访问的告警区分来源，并按原有规则同步。网页封禁卡片可在 Telegram 同时解除关联 IP 和设备封禁；解除不会恢复被撤销的登录。

两步验证使用标准 TOTP，可保存一次性恢复码。它用于网页密码登录；已授权、签名有效的 Telegram Web App 入口保留免密登录。代理来源 IP 必须按实际部署设置，不能直接信任客户端提供的头。

**登录防护与执行权限是两件事。** Agent 和网页终端仍可使用运行账号能访问的文件、命令和网络。命令黑名单不是完整安全边界；页面渲染 iframe 的沙箱只保护预览与宿主网页。

[访问安全与设备管理](docs/web-access-security.md) · [两步验证与恢复](docs/web-two-factor.md)

## 更新与备份

网页入口：**设置 → 系统状态 → 版本与更新**。Telegram／CLI 可使用 `/update`，服务器也可运行：

```bash
./install.sh update
```

默认从公开主仓库更新，无需 GitHub Token；私有测试源需要有读取权限的 Token。更新可选择保留或覆盖提示词与公共技能，覆盖前保存备份；私有技能与实例数据按既有保留规则处理。

**升级前备份数据，并停止服务端和所有 CLI，避免新旧版本同时访问数据库。** 数据库迁移会保留已有记录并创建升级前备份。回退旧程序时需要恢复相匹配的数据库，不能只替换代码。

实例备份入口为 **设置 → 数据与备份**，也可运行 `./install.sh data` 或 `./install.sh backup`。支持 ZIP、Zstd、XZ，以及旧 TAR.GZ 读取；默认保存到项目同级的 `xgent-backups/`，可配置其他项目外目录。

备份按配置、对话、提示词、任务、附件、命令输出和运行状态分组选择。导入页面始终列出所有选项，压缩包没有的内容置灰。数据库、附件原件、私有技能等需要一起恢复；含密钥的备份不能公开分享。

[备份范围与迁移](docs/data-management.md) · [Telegram 备份入口](docs/bot-backups.md) · [维护命令](docs/usage-reference.md#安装与维护)

## 本地终端

安装 CLI 组件后：

```bash
xgent          # 默认全屏终端界面，需要交互式终端
xgent --tui    # 全屏 TUI，需要交互式终端
xgent --no-tui # 行式界面
```

CLI 使用斜杠命令与编号菜单。全屏 TUI 支持对话面板、折叠内容、滚轮浏览、拖选复制与独立草稿；`F1` 查看帮助，`F2` 切换原生选择，`F4` 管理对话，`F5` 读取更早历史。生成中 `Ctrl+C` 停止当前回合。

启动 CLI 默认进入新对话首页，发送首条消息后才创建并保存对话；`/new [名称]` 返回新的空白草稿，不改变 Bot 当前对话。发送前仍可用 `/start`、`/providers`、`/update` 管理全局配置，已有对话通过 `/chats` 或 `F4` 选择。

模型只返回工具调用时，CLI 仍显示可展开的调用卡片，包含命令或文件路径，历史同步后保留。工具执行过程与最终正文分开呈现，不用一条空回复代替工具调用。

网页终端是另一项功能：它在浏览器中运行服务器 Shell，与 Web 共用登录、默认关闭。收起面板不结束命令；服务重启会结束旧终端进程，不会自动重跑。

[终端操作参考](docs/usage-reference.md#cli-与-tui)

## 开发与检查

服务端和 Web 前端不需要 Node 构建。前端是原生 JavaScript／CSS 模块，Python 提供 HTTP 和事件接口；入口为 `xgent_server.py`。

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install pytest pytest-xdist
python tools/check_split_integrity.py
pytest
```

浏览器回归额外需要 Python Playwright 和 Chromium：

```bash
python -m pip install playwright
python -m playwright install chromium
pytest tests/test_visual_pages_browser.py tests/test_web_two_factor_browser.py
```

可用隔离数据预览网页，无需真实 Bot Token 或模型：

```bash
python tools/workbench_fixture.py --port 8791 --messages 10000
```

夹具会打印地址和测试密码；它不是生产实例。运行数据位于项目中的 `.env`、`xgent_memory.db`、`xgent_storage/`、`memory/`、`skill-private/` 和 `workspace/`，这些目录不提交到仓库。

GitHub Actions 在 Python 3.11／3.12 上运行测试、源码完整性与语法检查，并执行 Ruff 和依赖漏洞检查。

[架构](docs/architecture.md) · [完整文档索引](docs/README.md) · [问题与建议](https://github.com/HANLINGVABCN/xgent/issues)

## 许可证

[MIT License](LICENSE)
