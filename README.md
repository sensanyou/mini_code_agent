# Mini Code Agent

一个用于学习 Agent 架构的小项目。

你今天学过的几个核心概念都放在这里：

- Agent Loop
- Tool Calling
- Permission
- Hooks
- Todo
- Subagent

## 环境

Python 3.10+

## 安装

```bash
pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填写：

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

## 学习顺序

建议按下面顺序阅读：

1. `main.py` —— 程序从哪里开始
2. `config.py` —— 工作目录、模型和 system prompt
3. `tools.py` —— Tool 是怎么定义和执行的
4. `hooks.py` —— Hook 注册表和 trigger_hooks
5. `permissions.py` —— 权限闸门
6. `todo.py` —— Todo 工具
7. `subagent.py` —— 子 Agent
8. `agent.py` —— 把全部东西串起来

不要一开始试图理解所有代码。

先抓住：

```text
User
 ↓
Parent Agent Loop
 ↓
LLM
 ↓
Tool Calling
 ↓
Hook
 ↓
Tool
 ↓
Tool Result
 ↓
messages[]
 ↓
LLM
```

然后再理解：

```text
                 Parent Agent
                      │
             ┌────────┼────────┐
             ↓        ↓        ↓
           Tool      Todo     task
                                │
                                ↓
                           Subagent
                                │
                           Tool Loop
                                │
                                ↓
                           Final Text
                                │
                                ↓
                         Parent messages[]
```
