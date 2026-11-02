# 压缩检查点与可选钩子

仅在到达压缩检查点、准备提醒，或考虑启用钩子时读取。

## 无钩子时

- 只在自然节点评估：阶段完成、用户验收、阻塞、批次边界、准备换会话。
- 不知道压缩次数就不猜，不写“已经压缩 N 次”，不声称有程序兜底。
- 判断条件与展示方式见 `SKILL.md` 的“评估”和“提醒怎么展示”。

## 钩子做什么

`scripts/handoff_hook.py` 只做两件事：

1. `PreCompact`（matcher `auto`）：按 `session_id` 增加自动压缩计数；手动压缩不计数。
2. `SessionStart`（matcher `compact`）：达到阈值时注入一行检查点，提醒模型评估是否建议交接；不保存、不新建、不校验最终答复。

阈值 3 次；提示后下一次阈值加 3。手动 `/compact`、恢复、clear 不计数；新会话从 0 开始。策略是提示而非强制：模型仍然要考虑安全位置、明确后续和切换收益；用户说“不提醒”时忽略注入。

## 状态与失败

- 状态目录：`%USERPROFILE%\.claude\state\project-handoff\`；每个会话一个 `<sha256(session_id)>.json`。
- 只存会话 ID、计数、下次阈值、更新时间；不存提示词、聊天或文件内容。
- 带锁和原子替换；缺字段、状态损坏、锁失败、Python 不可用一律静默放行，不阻塞会话。
- 状态文件很小，默认不自动删除；需要清理旧会话状态时由用户明确处理，钩子不删除任何文件。

## 契约状态

按官方 hooks 文档：`PreCompact` 有 `trigger: auto|manual`；`SessionStart` 的 `source` 含 `compact`，支持 `hookSpecificOutput.additionalContext`。脚本只依赖这两个字段，`PostCompact` 和 `Stop` 未使用。

**事件契约与投递仍未实测**：脚本自身逻辑有合成事件测试，但“真实压缩时宿主是否投递该事件”“`command` + `args` 的 exec 形式是否被你的版本接受”需要在你的机器上验证。装好后开一个长会话压缩一次，查看状态文件是否增长（见下）即可确认。

## 安装（可选，默认不装）

安装会写 `~/.claude/settings.json`，先确认三件事：本机有 Python 3.9+；愿意让本技能改这个文件；已备份。

用仓库自带的安装器（只增删 `PreCompact` / `SessionStart` 两个事件，不动其他键，先备份再写）：

```bash
python hooks/install.py --dry-run               # 先看会改什么
python hooks/install.py                        # 备份 settings.json 后合并
python hooks/install.py --uninstall            # 只移除这两个事件
```

安装器参数：`--settings <路径>` 指定配置（默认 `~/.claude/settings.json`）、`--python <解释器>` 指定 Python（默认当前解释器）、`--dry-run` 只打印不写。它不读取、不打印任何配置内容，只报告键名。

也可以手动合并：把 `hooks/settings.example.json` 里的 `<PYTHON>`、`<SKILL_DIR>` 换成你自己的绝对路径，再并入 `settings.json` 的 `hooks` 键。宿主不认 `command` + `args` 的 exec 形式时，改用 `hooks/settings.example.shell.json`（单字符串命令）。

装好后：

- 状态目录 `~/.claude/state/project-handoff/`（可用环境变量 `PROJECT_HANDOFF_STATE_DIR` 改），每个会话一个 `<sha256(session_id)>.json`；
- 压缩一次后该文件出现并计数，说明事件已投递；始终没有文件说明宿主没投递或被拦下，此时按“无钩子时”的方式工作，不要声称有程序兜底。

## 关闭

删除 `settings.json` 里这两个事件（或用 `install.py --uninstall`，或从备份恢复），不要删除技能目录。改配置前先备份，合并时不覆盖其他键。

## 已知限制

- 钩子只能提示，不能判断业务阶段是否安全，也不能证明用户看到了提醒。
- 用户说“不提醒”时模型不再展示；钩子仍可能在下一次压缩后注入，模型按用户指令忽略。
- 没有钩子时，本技能仍可完整保存和恢复，只是不做压缩计数。
