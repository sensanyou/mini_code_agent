
import json
import re
import uuid
from pathlib import Path


class ContextCompactor:
    LARGE_RESULT_CHAR_LIMIT = 30_000
    PREVIEW_CHAR_LIMIT = 2_000
    CONTEXT_CHAR_LIMIT = 50_000
    KEEP_RECENT_RESULTS = 3
    def __init__(self, workdir: Path):
        self.tool_results_dir = (
            workdir / ".task_outputs" / "tool-results"
        )

    def persist_large_output(
        self,
        tool_call_id: str,
        output: str,
    ) -> str:
        # 小结果不需要处理
        if len(output) <= self.LARGE_RESULT_CHAR_LIMIT:
            return output

        # 确保存储目录存在
        self.tool_results_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # 清理文件名，避免把不安全字符放进路径
        safe_id = re.sub(
            r"[^A-Za-z0-9_.-]",
            "_",
            tool_call_id,
        )
        safe_id = safe_id or uuid.uuid4().hex

        file_path = self.tool_results_dir / f"{safe_id}.txt"

        # 完整结果写入文件
        file_path.write_text(
            output,
            encoding="utf-8",
        )

        # 只把路径和预览返回给 Agent
        preview = output[:self.PREVIEW_CHAR_LIMIT]

        return (
            f"[Large tool output saved to: {file_path}]\n"
            f"Preview:\n{preview}\n"
            "[The full output is saved in the file above.]"
        )
    @staticmethod
    def estimate_chars(messages: list) -> int:
     return len(
        json.dumps(
            messages,
            ensure_ascii=False,
            default=str,
        )
    ) 
    def save_output(self, tool_call_id: str, output: str) -> Path:
      self.tool_results_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

      safe_id = re.sub(
         r"[^A-Za-z0-9_.-]",
        "_",
        tool_call_id,
    )
      safe_id = safe_id or uuid.uuid4().hex

      file_path = self.tool_results_dir / f"{safe_id}.txt"

      file_path.write_text(
        output,
        encoding="utf-8",
    )

      return file_path 

    def persisted_output_path(self, content: str) -> str | None:
       prefixes = (
         "[Large tool output saved to: ",
        "[Earlier tool result saved at ",
    )

       for prefix in prefixes:
        if content.startswith(prefix):
            end = content.find("]", len(prefix))

            if end != -1:
                return content[len(prefix):end]

        return None


    def micro_compact(
        self,
        messages: list,
        target_chars: int,
    ) -> list:
        # 已经足够小，就不需要压缩
        if self.estimate_chars(messages) <= target_chars:
            return messages

        # 找到最后一条 assistant 消息
        last_assistant_index = max(
            (
                index
                for index, message in enumerate(messages)
                if message.get("role") == "assistant"
            ),
            default=-1,
        )

        # 只考虑已经被后续 assistant 消息处理过的工具结果
        consumed = [
            (index, message)
            for index, message in enumerate(messages)
            if message.get("role") == "tool"
            and index < last_assistant_index
        ]

        # 最近的结果优先保留
        old_results = consumed[:-self.KEEP_RECENT_RESULTS]

        for _, block in old_results:
            if self.estimate_chars(messages) <= target_chars:
                break

            content = str(block.get("content", ""))

            # 很短的结果，压缩意义不大
            if len(content) <= 120:
                continue

            # 如果原结果已经保存过，直接复用路径
            saved_path = self.persisted_output_path(content)
            if saved_path is None:
                tool_call_id = block.get(
                    "tool_call_id",
                    uuid.uuid4().hex,
                )
                saved_path = str(
                    self.save_output(tool_call_id, content)
                )

            # 用短占位符替换完整结果
            block["content"] = (
                f"[Earlier tool result saved at {saved_path}]"
            )

        return messages