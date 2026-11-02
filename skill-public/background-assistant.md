```!
后台助手：把独立任务发到当前对话下面的子对话，主对话继续处理；完成后 trigger 自动带回真实结果并唤醒当前父对话。不需要 Web 或 Telegram。子对话命令也供其他技能使用。
```

# 后台助手

适合把可独立处理的查找、资料整理、复核等任务交给另一份 AI 上下文。子对话显示在父对话下方，可以正常查看、继续聊天和删除；删除父对话会一起删除子对话与任务。

用当前模式的命令执行工具运行：

```sh
python3 skill-public/script/background-assistant/background_assistant.py delegate --name '核对依赖' --message '核对 requirements.txt 的依赖兼容性，给出实际证据和结果。'
```

命令立即返回 `request_id`、子对话 ID 和 trigger 任务 ID。登记不等于完成，主对话继续工作，不反复轮询、睡眠等待或重复发送。后台 waiter 由 trigger 管理，子对话真正完成后才向绑定的父对话回传并触发 AI；它等待表单填写时也不会冒充完成。

任务很长或含复杂引号时先写 UTF-8 文件，再用 `--message-file 文件路径`，不需要改写任务正文。要复用已有子对话，增加 `--conversation 子对话ID`。父对话从执行环境自动取得，手动调用可用 `--parent 父对话ID`。

需要主动查看或取消时：

```sh
python3 xgent_conversation.py status --request-id 原请求ID
python3 xgent_conversation.py cancel --request-id 原请求ID
```

收到结果后根据实际状态、原始错误和文件路径继续处理；不把登记成功或中间一次操作成功说成任务全部完成。重试发送时复用原 `--request-id`，不会重复创建或执行。

子对话独立保存聊天、工具结果和运行，默认使用现有全局模型、人设、工具和调用模式；不会自动复制父对话历史，需要的背景直接写进任务。文件仍与父对话共享，安排任务时避免同时修改同一个文件。

关闭本技能会阻止这个包装脚本创建新任务，并停止本技能尚未完成的任务与回传。已保存的子对话仍可查看；通用的 `xgent_conversation.py create/send/delegate/status/wait/cancel/list` 保留给其他技能和手动调用。
