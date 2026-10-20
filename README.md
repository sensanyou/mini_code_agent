# Mini Code Agent

一个用于学习 Agent Harness 的小项目。代码采用 OpenAI Chat Completions
兼容接口，默认连接 DeepSeek。

当前已经不只有 Agent Loop、Tool、Permission、Hooks、Todo 和 Subagent，
还补齐了从 `memory` 到 `goal_loop` 的后续机制。

## 已实现能力

| 课程主题 | 本项目文件 | 关键能力 |
|---|---|---|
| Agent Loop | `agent.py` / `main.py` | 模型调用、工具调用、消息循环 |
| Tool / Permission / Hooks | `tools.py` / `permissions.py` / `hooks.py` | 工具分发、危险操作审批、扩展点 |
| Todo / Subagent | `todo.py` / `subagent.py` | 当前执行清单、独立上下文子 Agent |
| Skill Loading | `skill_loader.py` | 按需加载 `SKILL.md` |
| Context Compact | `context_compactor.py` | 归档、裁剪、工具结果压缩、历史摘要 |
| Memory | `memory.py` | `.memory/` 持久化、召回、自动提取、合并整理 |
| Task System | `task_system.py` | `.tasks/` 任务图、依赖、认领、完成解锁 |
| Background Tasks | `background_tasks.py` | 后台命令、结果通知、状态持久化 |
| Cron Scheduler | `cron_scheduler.py` | 5 段 Cron、持久化、到期触发队列 |
| Agent Teams | `agent_teams.py` | 异步 teammate、消息队列、任务认领 |
| MCP Plugin | `mcp_plugin.py` | stdio JSON-RPC、动态加载外部工具 |
| Workflow Runtime | `workflow_runtime.py` | JSON 工作流、步骤模板、运行日志、失败恢复 |
| Goal Loop | `goal_loop.py` | 独立评估器、验收条件、最大回合限制 |

## 架构

```text
User / Cron / Background / Teammate
                |
                v
        messages[] + Memory + Goal
                |
                v
             Agent Loop
                |
        +-------+--------+
        |                |
      LLM             Tool Pool
                         |
       +---------+-------+------+---------+
       |         |              |         |
     File      Task          Background   MCP
       |       Graph            Thread    Server
       |         |                |
       +---------+----------------+
                 |
              Tool Result
                 |
                 v
             messages[]
```

`agent.py` 负责组装 Harness，各机制仍保持独立模块。新增一种工具只需要注册
schema 和 handler，不需要重写 Agent Loop。

## 环境

- Python 3.10+
- DeepSeek 或其他 OpenAI 兼容 API

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

编辑 `.env`：

```text
DEEPSEEK_API_KEY=你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
MODEL_ID=你的模型
AUTO_MEMORY_EXTRACTION=true
MAX_AGENT_TURNS=50
```

也支持使用 `OPENAI_API_KEY`。如果使用其他兼容服务，同时修改
`DEEPSEEK_BASE_URL` 和 `MODEL_ID`。

## 运行

```powershell
.\venv\Scripts\python.exe main.py
```

示例任务：

```text
请检查 sample_project，找出 calculator.py 里的问题并修复，然后运行测试。
```

```text
创建三个持久任务：修复计算器、运行测试、更新文档。
让测试依赖修复，让文档依赖测试，然后列出任务图。
```

```text
在后台运行完整测试；等待时先检查 README。
```

```text
设置目标：修复 calculator.py 且测试通过。验收标准是测试命令退出码为 0。
```

## 机制说明

### Memory

- 每条记忆是 `.memory/*.md`，索引是 `.memory/MEMORY.md`。
- 启动新会话时会加载短索引，并按当前请求召回相关正文。
- 记忆正文被明确标记为不可信背景，不是新的用户命令。
- `AUTO_MEMORY_EXTRACTION=true` 时，每轮结束会提取持久偏好和项目事实。
- “本次任务”“当前会话”等临时信息会被拒绝写入长期记忆。

### Task System

- 每个任务是 `.tasks/task_xxxxxxxx.json`。
- 先创建节点，再根据工具返回的 ID 添加 `blockedBy` 依赖。
- 依赖未完成时不能认领；完成任务后会报告新解锁的任务。
- 依赖环、自依赖、重复认领都会被拒绝。

### Background / Cron

- 调用 `bash` 时传 `run_in_background=true`，立即得到 `bg_xxxxxxxx`。
- 完成结果在下一轮以 `<background_task_notification>` 注入。
- Cron 使用标准 5 段表达式：分、时、日、月、周。
- 调度器在 Agent 进程运行期间轮询，到期事件可以主动唤醒 CLI 中的 Agent。
- 进程退出后不会作为系统服务继续运行。

### Agent Teams

- `team_spawn` 启动一个异步 teammate。
- teammate 可以有独立角色、消息队列和可选 `task_id`。
- 指定任务时，teammate 会先原子认领，成功后完成任务并触发下游解锁。
- 当前实现是单进程线程级协作，不是分布式 Agent 集群。

### MCP

MCP 通过 stdio JSON-RPC 连接，不依赖额外 SDK。模型可以调用
`mcp_connect` 启动服务器，连接成功后外部工具会以
`mcp__server__tool` 的形式出现在下一轮工具池中。

启动外部 MCP 进程前会经过 Permission Hook 审批。

### Workflow

示例定义在 `workflows/inspect-and-test.json`：

```text
workflow_run(workflow_path="workflows/inspect-and-test.json")
```

步骤可以是 `agent` 或 `tool`，并可使用：

```text
{{inputs.name}}
{{steps.inspect.output}}
```

运行日志保存在 `.workflows/runs/`。步骤失败后使用 `workflow_resume`
从失败步骤继续。

### Goal Loop

- `goal_set` 设置目标、验收条件和最大评估次数。
- Agent 准备停止时，独立评估器检查最终回答和最近的工具证据。
- 验收不通过时，评估理由会作为新消息注入，Agent 继续工作。
- 达到上限后目标标记为 `failed`，控制权交还用户。

## 数据目录

| 目录 | 内容 |
|---|---|
| `.memory/` | 长期记忆与索引 |
| `.tasks/` | 持久任务图 |
| `.background/` | 后台命令状态与结果 |
| `.cron/` | Cron 配置 |
| `.teams/` | 团队运行时目录（teammate 当前仅在进程内） |
| `.goals/` | 当前目标 |
| `.workflows/runs/` | 工作流运行日志 |
| `.task_outputs/` | 大型工具结果 |
| `.transcripts/` | 上下文压缩前的完整归档 |

这些运行时目录默认不提交到 Git。

## 测试

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

测试覆盖记忆、任务依赖、后台任务、Cron、团队任务认领、MCP 工具调用、
工作流恢复和目标评估，不调用真实模型。

## 建议阅读顺序

1. `main.py`：程序入口和运行时生命周期
2. `config.py`：工作目录、模型和运行参数
3. `tools.py`：工具 schema 与 handler
4. `hooks.py` / `permissions.py`：扩展点和权限边界
5. `agent.py`：所有机制如何接回一个 Agent Loop
6. `memory.py` / `task_system.py`：跨会话知识与任务状态
7. `background_tasks.py` / `cron_scheduler.py`：异步和定时
8. `agent_teams.py` / `mcp_plugin.py`：协作与外部能力
9. `workflow_runtime.py` / `goal_loop.py`：固定编排与目标闭环

## 实现边界

这是一个可运行的学习版 Harness，重点是把机制边界和组合方式讲清楚。
生产环境还需要补充跨进程文件锁、身份认证、资源配额、网络沙箱、
MCP 生命周期管理、持久队列和可观测性。
