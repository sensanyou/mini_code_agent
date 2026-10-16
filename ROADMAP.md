# Learning Roadmap

## 1. Agent Loop
理解：
- while True
- LLM call
- tool_use
- tool_result
- messages[]

## 2. Tool Calling
理解：
- tools schema
- block.name
- block.input
- handler mapping
- `handler(**block.input)`

## 3. Permission
理解：
- deny list
- rule matching
- user approval
- execution before permission

## 4. Hooks
理解：
- register_hook
- trigger_hooks
- PreToolUse
- PostToolUse
- Stop
- UserPromptSubmit

## 5. Todo
理解：
- Todo 本身也是 Tool
- Agent 通过 Tool 修改任务状态
- Todo 不等于 Agent Loop

## 6. Subagent
理解：
- task 本身是 Tool
- 新的 messages[]
- 新的 Agent Loop
- 子 Agent 没有 task
- 父子 Agent 共享 WORKDIR
- 子 Agent 最终只把文本结果交还父 Agent
