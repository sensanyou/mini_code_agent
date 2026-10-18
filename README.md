# Mini Code Agent

一个用于学习 Agent 架构的小项目。

你学过的几个核心概念都放在这里：

- Agent Loop
- Tool Calling
- Permission
- Hooks
- Todo
- Subagent
- skill
- context

## 环境

Python 3.10+

## 安装

```bash
pip install -r requirements.txt
```

复制 `.env.example` 为 `.env`，填写：

```text
DEEPSEEK_API_KEY=你的key
<!-- cspell:ignore DEEPSEEK -->
DEEPSEEK_API_KEY=你的key
MODEL_ID=你的模型
```



## 运行

```bash
python main.py
```

例如：

```text
s01 >> 请检查 sample_project，找出 calculator.py 里的问题并修复，然后运行测试。
```


```
