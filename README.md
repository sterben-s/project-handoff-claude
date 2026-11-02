# project-handoff（Claude Code 版）

把“这次做到哪、哪些决定有效、下一步是什么、哪些事还不能做”写成一份接得住的记录，让新会话核对后继续，不用你重述，也不会两个会话同时改同一批文件。

改编自 [duoduoler-ops/Table-skills](https://github.com/duoduoler-ops/Table-skills) 的 `project-handoff`（MIT）。原版以 Codex 桌面端为主，这里是为 Claude Code 重写的实现：更短、只依赖一个记录文件、不带未验证的强制校验。

## 它解决什么

长任务做到一半，换个会话就要重新讲一遍背景；讲漏了，新会话就会重复调查、覆盖未提交的改动、或者把“还没验收”当成“已验收”。

这个技能把交接拆成三个**互不授权**的动作：

| 动作 | 做什么 | 需要什么 |
| --- | --- | --- |
| 提醒 | 建议“这里适合换会话”，并说明原因 | 不需要授权，只说话 |
| 保存 | 维护项目 `CURRENT.md` 的“当前接续”区 | 当前工作已授权写项目文件 |
| 新建接续 | 真的开一个新会话 | 你明确要求，或确认了写明动作的提议 |

提醒不写文件，保存不开新会话，保存也不等于提交、推送、部署。这是原版最有价值的设计，保留了。

## 安装

```bash
git clone https://github.com/sterben-s/project-handoff-claude.git ~/.claude/skills/project-handoff
```

（Windows PowerShell 同样适用，`~` 会展开到用户目录。）

装完重开一个会话，输入 `/project-handoff` 能看到即生效。技能列表在会话启动时加载，当前会话不会热更新。

## 怎么用

不用记命令，说人话就行：

- “保存一下进度” → 写 `CURRENT.md`
- “整理个交接” → 同上，并给你一段可粘贴的开场白
- “开个新会话接着做” → 保存后新建，并传入自包含简报
- “读 CURRENT 继续” → 先只读核对现场，报告差异，再按已有授权推进

它也会在阶段完成、用户验收、阻塞、批次边界时主动评估要不要建议交接。判断标准只有三条，同时满足才建议：

1. **安全位置**：手上的操作已收拢，成果和验证都有归属；
2. **明确后续**：新会话知道第一步做什么；
3. **切换收益**：能说出这次换会话的具体好处。

连续微调、还没收敛的排错、纯问答，都不会被劝去换会话——记录写在文件里，但对话留在原地。

## 记录长什么样

`CURRENT.md` 顶部一个区，10–15 行，已有就整段替换，历史条目不动：

```md
## 当前接续

- 更新：2026-11-02；记录不新增授权；现场须重新核对。
- 目标 / 验收：把设置页改成新版布局 / 四种主题下都能正常保存
- 进度与证据：已完成布局骨架（src/pages/Settings.tsx）；进行中表单校验
- 验证 / 用户验收：已跑类型检查与两个页面；未跑全量回归；用户未验收
- 决定：用户确认沿用旧配色；已否决换组件库（回归面太大）
- 未完成 / 阻塞：移动端断点未调；等设计稿
- 授权边界：已授权改前端；未授权提交与部署
- 现场快照：2026-11-02；main @ 333cdeb，领先 origin 7 个提交（未 fetch）
- 下一步：
  1. 补 768 断点样式（验收：三种宽度截图）
  2. 用户验收后提交（验收：git diff 仅含本次文件）
```

没有 `CURRENT.md` 的项目，技能会先判断跨会话接续是否真的需要，需要才建；简单任务不给你造文档。

## 可选：压缩计数钩子

默认**不安装**。装了以后，第 3 次自动压缩后会注入一行提示，提醒模型评估是否建议交接；之后每 3 次再提示。手动 `/compact` 不计数。

```bash
python hooks/install.py --dry-run    # 先看会改什么
python hooks/install.py              # 备份 settings.json 后合并
python hooks/install.py --uninstall  # 只移除这两个事件
```

安装器只增删调用本技能脚本的钩子条目，不动 `settings.json` 的其他键，改前写带时间戳的备份，不打印文件内容。

已知限制，请先看清楚再决定装不装：

- 事件契约（`PreCompact.trigger`、`SessionStart.source=compact`、`hookSpecificOutput.additionalContext`）按官方文档实现，但**没有在真实压缩事件上验证过**；装好后压缩一次，看 `~/.claude/state/project-handoff/` 下有没有文件即可确认。
- `command` + `args` 的 exec 形式是较新的能力，你的版本不认时改用手动合并 `hooks/settings.example.shell.json`（单字符串形式，不经 `args`）。
- 钩子只能提示，不能判断业务是否到了安全位置，也不能证明你看到了提醒。它不做最终答复的强制校验。

## 和 Codex / 其他工具共存

同一项目可能同时被 Codex 和 Claude Code 使用。两个工具的技能、状态目录、钩子配置互不读取；唯一共享的是项目里的 `CURRENT.md`。

- 只维护一个 `## 当前接续` 区，不要为每个工具各建一份 `PROJECT_STATE.md`；
- 不要让两个会话同时写同一区，发现归属不明的改动先暂停、核对后再写；
- 想让 Codex 也遵守时，在项目 `AGENTS.md` 里写明“交接写 `CURRENT.md` 的当前接续区”。

## 目录

```
SKILL.md                      入口：何时用、怎么评估、三个动作的授权
references/
  save.md                     保存：载体选择、单一当前区、字段、回读核对
  resume.md                   恢复：读取顺序、现场核对、新建接续会话
  compaction.md               可选钩子：计数策略、安装、失败与限制
  workspace-rules.md          适配到你自己的工作区（含最小例子）
assets/current-handoff.template.md   当前接续区模板
scripts/handoff_hook.py       钩子脚本（默认不启用，失败放行，不删文件）
hooks/install.py              写 settings.json 的安装器（带备份与 dry-run）
hooks/settings.example.json   手动合并用的示例（exec 形式）
hooks/settings.example.shell.json   同上，单字符串命令形式
tests/test_handoff_hook.py    合成事件单元测试
```

跑测试：

```bash
python -X utf8 tests/test_handoff_hook.py
```

## 许可

MIT，见 [LICENSE](LICENSE)。上游版权与改编说明见 [NOTICE.md](NOTICE.md)。

同名技能不要和原仓库的 `project-handoff` 同时安装，会触发冲突。
