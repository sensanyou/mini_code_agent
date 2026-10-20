import json
import sys


for line in sys.stdin:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        continue

    request_id = message.get("id")
    method = message.get("method")

    if request_id is None:
        continue

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "echo", "version": "1.0"},
        }
    elif method == "tools/list":
        result = {
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }
            ]
        }
    elif method == "tools/call":
        arguments = message.get("params", {}).get("arguments", {})
        result = {
            "content": [
                {
                    "type": "text",
                    "text": f"echo: {arguments.get('text', '')}",
                }
            ]
        }
    else:
        result = {}

    print(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
        ),
        flush=True,
    )
