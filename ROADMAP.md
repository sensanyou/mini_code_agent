# Learning Roadmap

当前项目已经覆盖参考课程主线的 17 个主题。学习时仍然建议每次只抓一个
机制，弄清楚它给 Agent Loop 增加了什么边界。

## 1. Agent Loop

文件：`main.py` / `agent.py`

理解：

- `while` 循环
- LLM call
- assistant tool calls
- tool result
- `messages[]`
- 最大回合限制

## 2. Tool Calling

文件：`tools.py`

理解：

- tools schema
- handler mapping
- JSON 参数解析
- 统一 `execute_tool`
- 工具结果回填

## 3. Permission

文件：`permissions.py`

理解：

- deny list
- 路径边界
- 危险命令识别
- 用户审批
- MCP 外部进程审批

## 4. Hooks

文件：`hooks.py`

理解：

- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `Stop`
- Hook 返回非空值时阻止或继续

## 5. Todo

文件：`todo.py`

理解：

- Todo 也是 Tool
- Todo 是当前任务的执行计划
- Todo 不负责跨会话恢复

## 6. Subagent

文件：`subagent.py`

理解：

- 新的 `messages[]`
- 新的 Agent Loop
- 独立上下文
- 最终只把文本结果交还父 Agent

## 7. Skill Loading

文件：`skill_loader.py`

理解：

- 先暴露技能目录
- 相关时才加载完整说明
- 技能内容不能绕过权限

## 8. Context Compact

文件：`context_compactor.py`

理解：

- 消息数量裁剪
- 工具结果转存
- 旧工具结果微压缩
- 历史摘要
- 完整 transcript 归档

## 9. Memory

文件：`memory.py`

理解：

- `.memory/MEMORY.md` 索引
- 一条记忆一个 Markdown 文件
- 按当前请求召回
- 自动提取持久信息
- 拒绝临时任务状态
- 达到阈值后整理

## 10. Task System

文件：`task_system.py`

理解：

- 一个任务一个 JSON 文件
- `blockedBy` 依赖图
- `pending -> in_progress -> completed`
- 原子认领
- 完成时解锁下游
- 依赖环检测

## 11. Background Tasks

文件：`background_tasks.py`

理解：

- `run_in_background`
- daemon thread
- `bg_xxxxxxxx`
- 占位 tool result
- 完成通知注入
- 状态持久化

## 12. Cron Scheduler

文件：`cron_scheduler.py`

理解：

- 5 段 Cron 表达式
- 到期判断
- 同一分钟去重
- 待处理触发持久化
- 单次任务自动禁用

## 13. Agent Teams

文件：`agent_teams.py`

理解：

- teammate 是异步 worker
- 独立角色和消息队列
- 可选任务认领
- 团队结果通过通知回到主 Agent
- 当前实现是进程内线程协作

## 14. MCP Plugin

文件：`mcp_plugin.py`

理解：

- stdio JSON-RPC
- initialize
- `tools/list`
- `tools/call`
- 动态加入工具池
- namespaced tool name

## 15. Integrated Harness

文件：`agent.py`

理解：

- 所有机制共用一个 Agent Loop
- 动态工具池
- 运行时通知注入
- Memory + Goal 进入 system context
- 工具结果进入上下文压缩

## 16. Workflow Runtime

文件：`workflow_runtime.py`

理解：

- 固定编排写入 JSON
- agent step 与 tool step
- 模板引用前序输出
- 每步写 journal
- 失败后从失败步骤恢复

## 17. Goal Loop

文件：`goal_loop.py`

理解：

- 目标与验收条件
- 独立评估器
- 工具证据参与评估
- 未达标时自动继续
- 最大评估次数
- 达标、失败后交还用户

## 推荐观察点

每加一个机制，都问同一个问题：

```text
它修改的是 LLM、工具、上下文、权限，
还是 Agent 循环的停止条件？
```

Agent Loop 本身应尽量保持简单。复杂度应该落在 Harness 的边界上。
