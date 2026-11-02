# 子对话与后台助手

子对话是通用的对话归属功能，不属于某个技能。Web 对话列表的父行尾部、`⋯` 左侧显示小箭头，点击展开下面缩进的子对话；刷新保留展开状态，打开子对话时自动展开它的上级。`⋯ → 新建子对话` 直接创建并打开一份空白上下文。

子对话可查看、继续聊天、重命名、归档和删除。分组跟随父对话，移动父对话会一起移动子对话。删除父对话会删除所有所属子对话、停止运行中的请求、删除任务和结果回传；删除一个子对话保留父对话与其他子对话。原有“分支来源”单独保存，不参与这个连删关系。共享文件和全局用量统计继续保留。

子对话拥有独立聊天、工具结果、运行、待发队列和表单；文件使用现有共享目录，没有自动创建独立文件工作区。默认模型、人设、工具和调用模式沿用现有全局设置，不自动复制父对话历史，需要的背景写进任务即可。

清空或手动压缩父对话保留已经登记的后台任务，结果进入同一个父对话的新回合；清空子对话则使原任务失效。挂起表单仍使用原来的进程内存储，重启后只标记中断，不新增表单恢复或自动重跑工具。

## 通用命令

主服务运行时，Bot、Web 是否开启不影响后台接纳。CLI 只登记请求和读取结果，模型与工具在主服务的原队列中执行，不改变 Web、Bot 或终端正在选择的对话。

```sh
python3 xgent_conversation.py create --name '资料核对'
python3 xgent_conversation.py send --conversation 子对话ID --message '独立处理这项任务'
python3 xgent_conversation.py delegate --name '资料核对' --message-file workspace/task.txt
python3 xgent_conversation.py status --request-id 请求ID
python3 xgent_conversation.py cancel --request-id 请求ID
```

父对话默认取执行环境中的 `XGENT_CONVERSATION_ID`；手动调用可用 `--parent` 指定，环境里没有时取当前 Web 对话。`send` 省略 `--conversation` 也会创建子对话，但只登记任务；`delegate` 同时登记现有 trigger，自动回传结果。返回请求 ID、子对话 ID、trigger ID，登记成功不表示生成完成。

长任务使用 UTF-8 的 `--message-file`，换行和内容完整传递。重复发送使用同一个 `--request-id`，不会重复创建或执行。结果绑定请求、会话、运行及回复组，后来的其他回答不会被误取；表单等待不算完成，恢复后的运行继续绑定原请求。失败、停止及原始错误如实返回。`wait` 是供 trigger 执行的后台等待入口，主对话不持续等候；`--timeout` 只结束等待，不重复发送任务。

## 可选公共技能

[background-assistant.md](../skill-public/background-assistant.md) 提供使用说明，包装脚本调用同一份通用命令。关闭或隐藏这个技能会阻止包装脚本的新任务，停止本技能尚未完成的请求与回传；已经保存的子对话仍可查看。菜单和其他技能的通用功能保持可用。

## 数据与验证

schema v9 → v10 在迁移前自动生成 `*.pre-conversations-v10.sqlite3` 备份。`owner_conversation_id` 保存子对话归属；原来的 `parent_conversation_id` 继续表示分支来源。`conversation_jobs` 保存请求与接纳、续接和 trigger 的关系，归入任务备份；普通历史导入不会自动发送这些后台请求。

测试覆盖子对话树、选择与上下文隔离、请求去重、表单暂停恢复、取消和删除竞争、原始错误、两种工具入口、Web 展开及刷新和手机布局。提供商测试使用模拟上游，页面测试使用本地隔离浏览器，不代表线上模型或真实 Telegram 客户端验收。
