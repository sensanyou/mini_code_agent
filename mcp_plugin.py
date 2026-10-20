import json
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable


class MCPError(RuntimeError):
    pass


def normalize_mcp_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
    return (name or "tool")[:64]


class MCPServer:
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str],
        cwd: Path,
        timeout: float = 30,
    ):
        self.name = name
        self.command = command
        self.args = args
        self.cwd = cwd
        self.timeout = timeout
        self.process: subprocess.Popen | None = None
        self.tools: list[dict] = []
        self._request_id = 0
        self._lock = threading.RLock()
        self._responses: queue.Queue[dict] = queue.Queue()
        self._stderr_lines: list[str] = []

    def _reader(self) -> None:
        assert self.process and self.process.stdout

        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(message, dict):
                self._responses.put(message)

    def _stderr_reader(self) -> None:
        assert self.process and self.process.stderr

        for line in self.process.stderr:
            self._stderr_lines.append(line.rstrip())
            del self._stderr_lines[:-30]

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(
                [self.command, *self.args],
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as error:
            raise MCPError(f"Could not start MCP server: {error}") from error

        threading.Thread(
            target=self._reader,
            name=f"mcp-reader-{self.name}",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._stderr_reader,
            name=f"mcp-stderr-{self.name}",
            daemon=True,
        ).start()

        self._request(
            "initialize",
            {
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "mini-code-agent",
                    "version": "1.0",
                },
            },
        )
        self._notify("notifications/initialized", {})
        result = self._request("tools/list", {})
        tools = result.get("tools", [])
        self.tools = [tool for tool in tools if isinstance(tool, dict)]

    def _write(self, message: dict) -> None:
        if not self.process or not self.process.stdin:
            raise MCPError("MCP server is not running")

        self.process.stdin.write(
            json.dumps(message, ensure_ascii=False) + "\n"
        )
        self.process.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        self._write(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def _request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict:
        with self._lock:
            self._request_id += 1
            request_id = self._request_id
            self._write(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            deadline = time.monotonic() + self.timeout

            while True:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    raise MCPError(
                        f"MCP request timed out: {self.name}.{method}"
                    )

                try:
                    message = self._responses.get(timeout=remaining)
                except queue.Empty as error:
                    raise MCPError(
                        f"MCP request timed out: {self.name}.{method}"
                    ) from error

                if message.get("id") != request_id:
                    continue

                if "error" in message:
                    raise MCPError(
                        f"MCP error from {self.name}: "
                        f"{message['error']}"
                    )

                result = message.get("result", {})
                return result if isinstance(result, dict) else {
                    "value": result
                }

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        result = self._request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        content = result.get("content", [])
        parts = []

        if isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    parts.append(str(block))
                elif block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(
                        json.dumps(block, ensure_ascii=False, default=str)
                    )

        if not parts and "structuredContent" in result:
            parts.append(
                json.dumps(
                    result["structuredContent"],
                    ensure_ascii=False,
                    indent=2,
                )
            )

        text = "\n".join(parts).strip() or json.dumps(
            result,
            ensure_ascii=False,
            default=str,
        )

        if result.get("isError"):
            return f"Error: {text}"

        return text

    def stop(self) -> None:
        process = self.process

        if not process:
            return

        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except OSError:
                pass

        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass

        self.process = None


class MCPManager:
    def __init__(self, workdir: Path):
        self.workdir = workdir.resolve()
        self._servers: dict[str, MCPServer] = {}
        self._handlers: dict[str, Callable] = {}

    def connect(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
    ) -> str:
        name = normalize_mcp_name(name)
        args = args or []

        if not name:
            raise ValueError("MCP server name cannot be empty")
        if not command.strip():
            raise ValueError("MCP command cannot be empty")
        if name in self._servers:
            self.disconnect(name)

        server_cwd = (
            (self.workdir / cwd).resolve()
            if cwd
            else self.workdir
        )

        if not server_cwd.is_relative_to(self.workdir):
            raise ValueError("MCP cwd must stay inside the workspace")

        server = MCPServer(
            name=name,
            command=command,
            args=[str(item) for item in args],
            cwd=server_cwd,
        )

        try:
            server.start()
        except Exception:
            server.stop()
            raise

        self._servers[name] = server
        return (
            f"Connected MCP server '{name}' with "
            f"{len(server.tools)} tool(s)"
        )

    def disconnect(self, name: str) -> str:
        name = normalize_mcp_name(name)
        server = self._servers.pop(name, None)

        if not server:
            return f"MCP server not found: {name}"

        server.stop()
        return f"Disconnected MCP server '{name}'"

    def tool_specs(self) -> tuple[list[dict], dict[str, Callable]]:
        specs = []
        handlers = {}

        for server_name, server in self._servers.items():
            for tool in server.tools:
                tool_name = str(tool.get("name", "")).strip()

                if not tool_name:
                    continue

                full_name = (
                    f"mcp__{normalize_mcp_name(server_name)}__"
                    f"{normalize_mcp_name(tool_name)}"
                )
                description = str(
                    tool.get("description")
                    or f"MCP tool {server_name}.{tool_name}"
                )
                schema = tool.get("inputSchema")

                if not isinstance(schema, dict):
                    schema = {
                        "type": "object",
                        "properties": {},
                    }

                specs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": full_name,
                            "description": description,
                            "parameters": schema,
                        },
                    }
                )

                def handler(
                    server=server,
                    tool_name=tool_name,
                    **arguments,
                ) -> str:
                    return server.call_tool(tool_name, arguments)

                handlers[full_name] = handler

        return specs, handlers

    def format_servers(self) -> str:
        if not self._servers:
            return "No MCP servers connected."

        return "\n".join(
            (
                f"- {name}: {len(server.tools)} tool(s), "
                f"pid={server.process.pid if server.process else 'stopped'}"
            )
            for name, server in self._servers.items()
        )

    def stop_all(self) -> None:
        for server in list(self._servers.values()):
            server.stop()
        self._servers.clear()


def build_mcp_tools(
    manager: MCPManager,
) -> tuple[list[dict], dict[str, Callable]]:
    tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_connect",
                "description": (
                    "Connect a stdio MCP server and load its tools. The "
                    "command is executed directly without a shell."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "command": {"type": "string", "minLength": 1},
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "cwd": {"type": "string"},
                    },
                    "required": ["name", "command"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_list",
                "description": "List connected MCP servers.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "mcp_disconnect",
                "description": "Disconnect an MCP server by name.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                    },
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
    ]

    def mcp_connect(
        name: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
    ) -> str:
        return manager.connect(name, command, args, cwd)

    def mcp_list() -> str:
        return manager.format_servers()

    def mcp_disconnect(name: str) -> str:
        return manager.disconnect(name)

    handlers = {
        "mcp_connect": mcp_connect,
        "mcp_list": mcp_list,
        "mcp_disconnect": mcp_disconnect,
    }
    return tools, handlers
