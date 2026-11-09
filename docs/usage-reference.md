# 操作参考

[返回文档索引](README.md) · [返回项目首页](../README.md)

## 安装与维护

建议通过安装脚本管理生产实例。脚本使用项目内的 `venv/`，源码、配置和运行数据位于项目目录；不需要单独的前端构建。

```bash
./install.sh              # 安装、部署和配置菜单
./install.sh status       # 服务、保活方式和组件状态
./install.sh start        # 按已选择的保活方式启动
./install.sh stop         # 停止服务
./install.sh restart      # 重启服务
./install.sh update       # 更新代码、Python 环境和兼容依赖
./install.sh data         # 数据导入／导出菜单
./install.sh backup       # 备份目录、计划和保留规则
```

首次安装可选择 systemd、PM2、nohup 或前台运行，后续可在菜单调整。生产环境的建议是保活进程配合实例备份，不要让多个服务进程同时接管同一实例。

| 方式 | 日志与恢复 |
| --- | --- |
| systemd | `journalctl -u xgent -f`；安装器创建 `xgent.service` |
| PM2 | `pm2 logs xgent-telegram`；安装器配置启动和保存进程清单 |
| nohup | 查看项目中的 `xgent_output.log`，不提供崩溃拉起 |
| 前台 | 在当前终端查看输出，适合调试 |

PM2 列表为空时，先确认使用的是安装时的同一账号；`pm2 list` 与 `sudo pm2 list` 不是同一份进程表。需要恢复已保存清单时使用 `pm2 resurrect`。改变清单后运行 `pm2 save`。

Web 默认监听 `127.0.0.1:8790`。需要远程访问时使用 SSH 转发或 HTTPS 反向代理。不要将本机代理 IP 当作所有访客的身份；代理头信任规则见[访问安全](web-access-security.md)。

公开主仓库为 `HANLINGVABCN/xgent`。默认更新源不需要 Token，私有测试源需要读取权限。可通过应用更新页选择来源，或在 `.env` 中设置：

```env
UPDATE_GITHUB_TOKEN=有测试仓库读取权限的Token
UPDATE_ZIP_URL=https://api.github.com/repos/HANLINGVABCN/xgent-test/zipball/main
```

Token 不要写进 URL、聊天正文或公开仓库。使用 Fine-grained Token 时，该更新源所需权限为仓库 Contents 读取。

更新前备份并停止服务端与所有 CLI，避免新旧版本混跑。当前数据库版本由代码中的 `SCHEMA_VERSION` 决定，迁移记录中的 v8／v10 等数字描述当时的升级，不是新安装配置。回退旧代码需恢复对应升级前数据库。

实例数据包含数据库、上传原件、生成媒体、附件版本、记忆、私有技能、用户文件和有关配置。只复制源码或只导出对话 ZIP 都不能完整迁移；详细范围见[数据管理](data-management.md)。

## 对话与管理命令

回复底部与用量详情共用格式：`2026-11-09 03:20 ↑1,200（800） ↓300 12s 25tok/s 服务商/模型`。
网页与 CLI 时间放在开头，Telegram 时间放在结尾；时间精确到分钟，数字使用千位分隔。
`↑` 是输入量，括号内是其中的缓存量，`↓` 是输出量；缓存已包含在输入中，不重复加总。
速度按输出 Token 数除以本轮响应耗时计算，包含模型等待与思考时间，不等同于纯正文流速。
上游没提供的缓存、输出或速率会明确标为未提供，不冒充零；详情保留思考、可见输出、总量和精确耗时。

Telegram 与 CLI 提供同一套主要菜单；Web 的管理页面和聊天命令调用现有服务。具体输入方式由客户端适配。

| 命令 | 用途 |
| --- | --- |
| `/start` | 打开主菜单 |
| `/chats` | 选择、管理、归档与恢复对话 |
| `/new [名称]` | 显式创建并切换对话 |
| `/queue` | 查看待发消息与队列操作 |
| `/stop` | 停止当前回答 |
| `/config` | 配置菜单 |
| `/providers` | 提供商、接口和模型列表 |
| `/provider_config` | 提供商配置导入／导出 |
| `/models`、`/chat_model` | 选择对话模型 |
| `/media_model` | 选择媒体模型 |
| `/prompts` | 提示词查看、编辑与重载 |
| `/clear` | 重置当前模型上下文，保留历史；`/clear_memory` 是兼容别名 |
| `/compress` | 压缩当前有效上下文并保存备份 |
| `/export` | 导出当前对话的完整记忆记录 |
| `/depth` | 普通历史的模型可见消息深度 |
| `/thinking` | 思考深度 |
| `/params` | 请求超时等参数 |
| `/agent` | Agent 模式开关 |
| `/blacklist` | 命令黑名单 |
| `/stream` | 客户端的流式开关 |
| `/skills` | 技能启用、普通关闭与隐藏 |
| `/web` | Web 配置与入口 |
| `/stats` | Token 用量报告 |
| `/status` | 运行与记忆统计；兼容 `/show_chat_info` |
| `/update` | 更新代码 |
| `/restart` | 重启服务 |

Telegram 另有 `/topics` 和 `/topic_bind` 用于话题管理。某些命令需要相应组件、权限或当前对话，不能因菜单中存在就推断本次已经执行成功。

## CLI 与 TUI

```bash
xgent                 # 默认行式 CLI
xgent --tui           # 全屏 TUI
xgent --no-tui        # 明确使用行式 CLI
python xgent_cli.py --tui  # 在已安装依赖的项目目录直接运行
```

全屏 TUI 需要交互式终端与 `prompt_toolkit`；条件不满足时使用行式界面。每个终端进程独立选择对话、保存草稿与阅读状态，重新打开的终端重新初始化选择。

行式 CLI 可直接输入文字，或输入 `/` 查看命令，按菜单编号选择；`:数字` 可明确表达菜单选择。正在回答时 `Ctrl+C` 中断当前回合，空闲时用于退出或结束当前输入流程；`Ctrl+D`、`exit`、`quit` 可退出。

| TUI 操作 | 用途 |
| --- | --- |
| `F1` | 帮助与快捷键 |
| `F2` | 切换 TUI 鼠标处理与终端原生选择 |
| `F4` | 对话面板 |
| `F5` | 加载更早的历史 |
| 滚轮／`PgUp`／`PgDn` | 浏览历史 |
| 拖选 | TUI 鼠标模式下选择并复制 |
| `Ctrl+C` | 停止正在生成的回合 |

原生选择模式的复制由终端处理，方向键可用于滚动；支持备用屏幕滚动的终端可继续使用滚轮。界面内的 `F1` 帮助说明当前模式的具体按键。

CLI 可用环境变量 `XGENT_CLI_NO_TG_MIRROR=1` 关闭其 Telegram 镜像；这不关闭网页、模型或 Telegram 自身的回复。

**网页终端与 CLI 是不同入口。** 网页终端使用 xterm.js 和服务器 PTY，默认关闭，最多三个会话，空闲三十分钟回收。开启页面不会自动新建 Shell，收起面板也不会终止命令。服务重启会清理旧终端，不自动恢复或重跑；Windows 服务端不提供 POSIX PTY。

## 工具与提示词

Agent 开启后可以执行服务器操作。新实例默认 Tool call，正则围栏模式兼容原协议。具体行为及工具结果如何进入历史见[双模式说明](tool-call-mode.md)。

| Tool call 名称 | 正则围栏协议 | 能力 |
| --- | --- | --- |
| `exec_command` | `run-x` | 一次性命令 |
| `start_terminal` | `shell-x` | 持续或交互式进程 |
| `terminal_input` | `stdin-x` | 写入输入、按键或读取新增输出 |
| `close_terminal` | `shellkill-x` | 结束交互式会话 |
| `read_file` | `read-x` | 文件、图片和支持的二进制读取 |
| `search_files` | `grep-x` | 文件内容检索 |
| `inspect_code` | `intel-x` | 定义、引用、调用方和结构分析 |
| `search_web` | `search-x` | Tavily 联网检索 |
| `fetch_urls` | `fetch-x` | 网页抓取 |
| `send_file` | `sendfile-x` | 向用户交付服务器文件 |
| `generate_media` | `media-x` | 使用媒体模型生成或编辑 |
| `write_file` | `file-x` | 创建／整体写入文本文件 |
| `write_binary` | Base64 文件围栏 | 写入二进制文件 |
| `edit_file` | `edit-x` | 精确局部替换 |
| `ask_user` | `ask-x` | 单选、多选、文本和私密表单 |
| `finish_task` | `over-x` | 满足条件时免回传收尾 |

工具调用可能需要“请求工具 → 执行 → 请求模型分析结果”多次模型请求。`finish_task` 只有在允许的操作全部成功时才省略续问，不承诺每个 Agent 任务只有一次模型调用。

后台任务通过 `trigger` 命令登记，支持延时、指定时间、cron 和条件触发，不是新的渲染协议。完整参数见[后台任务技能](../skill-public/trigger-x-protocol.md)与[子对话说明](child-conversations.md)。

正则围栏的标签、标记及完整用法以[围栏模式提示词](../prompts/agent_addon.txt)为准。Tool call 的参数由实际工具定义提供，不需要模型在正文中复述这些围栏。读取历史或页面源码不会执行其中的工具示例。

| 文件 | 用途 |
| --- | --- |
| [main.txt](../prompts/main.txt) | 基础身份与人设 |
| [global_addon.txt](../prompts/global_addon.txt) | 表达与呈现、上下文和事实规则，包括页面输出格式 |
| [toolcall_addon.txt](../prompts/toolcall_addon.txt) | Tool call 模式的执行与私密规则 |
| [agent_addon.txt](../prompts/agent_addon.txt) | 正则围栏模式的协议说明 |
| [agent_disabled_addon.txt](../prompts/agent_disabled_addon.txt) | Agent 关闭时的限制 |
| [compression.txt](../prompts/compression.txt) | 上下文压缩指令 |

每轮根据 Agent 开关与调用方式选择对应提示词，不把两套工具说明混合使用；运行目录、技能索引及查阅规则由现有构造逻辑加入。压缩使用独立流程，不沿用普通对话的全部系统提示词，见[上下文说明](context-and-export.md)。

公共技能位于 `skill-public/`，实例自定义技能放在 `skill-private/`。索引只列出根目录技能文件，辅助脚本和资料放在 `script/`。简介使用 `!` 围栏：

````text
```!
说明技能用途、适用场景和边界。
```
````

技能启用时提供简介与路径；普通关闭保留名称和路径，隐藏时不加入索引。关闭或隐藏不是文件权限隔离，Agent 关闭时也不会因此获得文件读取权限。更新公共技能可能覆盖本地改动，私有技能按既有规则保留。

## 模型参数与输入

思考深度提供关闭、自动、低、中、高、很高、超高、最高八档；实际支持范围取决于模型。默认自动不额外发送思考字段，接口拒绝参数时按原有机制去掉参数重试，不把模型内部思考伪造为可见内容。

网页回复头像下面的思考块仅显示接口实际提供的内容。用量按上游返回记录；模型名称、切换、计费与上下文窗口不同，输入 Token 数不保证每轮递增。

当前有效附件独立于普通历史深度。缺失原件会明确显示不可用，普通聊天可继续；需要完整原件的压缩或媒体请求仍可能失败。上传附件读取当前内容，工具结果副本保留已读取版本；详见[文件入口](file-ingress.md)、[附件版本](attachment-versions.md)和[模型输入与容量](model-inputs.md)。

提供商导出有不同入口：Web 默认脱敏导出，含密钥导出需明确选择；Telegram／CLI 原配置迁移入口可能包含完整 API Key。分享前检查文件，不能把配置导出当作普通聊天附件。

## 诊断

优先检查安装器的组件状态、应用的系统状态以及运行日志。模型、Telegram 与 Web 是独立通道；某一通道不可用不代表所有服务都停止。

代理地址须从实际运行环境核对。WSL 中的 `127.0.0.1` 通常指 WSL 自己，不能仅因 Windows 上有同端口代理就假定 WSL 可连通。修改代理后检查服务进程环境，而不是只看当前终端变量。

不要公开贴出 `.env`、原始 PM2 环境列表、Cookie、完整认证请求、数据库或含密钥的日志。历史排障记录的绝对路径与旧仓库名只适用于当时实例，不应作为当前更新命令。

## 可选浏览器检查

项目首页的 `pytest` 命令运行 Python 测试。下面的 Node 检查用于开发时核对 Markdown 渲染、历史和菜单传输，不是部署依赖：

```bash
npm install --no-save linkedom playwright
npx playwright install chromium
node tools/render_smoke.mjs
node tools/web_history_smoke.mjs
node tools/web_transport_smoke.mjs
node tools/web_menu_smoke.mjs
```

测试和预览夹具使用隔离数据；如需核对实际实例，另行验证其部署版本、登录、模型接口和文件原件，不能仅凭模拟测试推断线上状态。
