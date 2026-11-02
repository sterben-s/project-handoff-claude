# 来源与改编说明

本技能改编自 [duoduoler-ops/Table-skills](https://github.com/duoduoler-ops/Table-skills) 的 `project-handoff`（MIT License，见 [LICENSE](LICENSE)）。

## 改了什么

原仓库的实现以 Codex 桌面端为主，依赖 `PostCompact`、`prompt_id`、`last_assistant_message` 等字段和一份独立的 `PROJECT_STATE.md`。本版为 Claude Code 重写：

| 方面 | 原版 | 本版 |
| --- | --- | --- |
| 记录载体 | `PROJECT_STATE.md` | 项目 `CURRENT.md` 里唯一的 `## 当前接续` 区，与项目其他记录同处一文件 |
| 压缩计数 | `PostCompact` + 最终答复核验 | `PreCompact(auto)` 计数 + `SessionStart(compact)` 注入一行提示，不做强制校验 |
| 会话标识 | `prompt_id` 等 | 只用 `session_id` |
| 自动接续 | 宿主能力 | 有应用私有工具时用它新建 `fresh` 会话，否则只给可粘贴开场白，不假装已接续 |
| 工作区适配 | — | 单独的 `references/workspace-*.md` 约定，规则正文留在项目自己的文档里 |

保留的设计思想：三个动作与三份授权；“安全位置 / 明确后续 / 切换收益”三条评估；“交接建议：”放在最终答复第一段；提醒、保存、新建互不授权。

本版不是原仓库文件的逐字复制，而是重新写的文本与实现；脚本、模板、测试为本仓库原创。

## 注意

- 与原技能同名（`project-handoff`），安装本技能时不要同时安装原仓库的 `project-handoff`，避免触发冲突。
- 本技能不包含、不读取任何 `settings.json` 内容；`hooks/install.py` 只在用户主动运行时修改配置，且改前备份、不打印文件内容。
