import json
import os
import httpx
from mcp.server import MCPServer

# 连接参数全部来自环境变量，源码里不再写死任何密钥。
# 本地运行前先设置（PowerShell）：
#     $env:ANYTHINGLLM_KEY = "你的密钥"
# 可选覆盖：ANYTHINGLLM_BASE（默认 http://localhost:3001/api/v1）、
#           ANYTHINGLLM_WORKSPACE（默认 mods）。
ANYTHINGLLM_BASE = os.environ.get(
    "ANYTHINGLLM_BASE", "http://localhost:3001/api/v1"
).rstrip("/")
ANYTHINGLLM_KEY = os.environ.get("ANYTHINGLLM_KEY", "")
WORKSPACE_SLUG = os.environ.get("ANYTHINGLLM_WORKSPACE", "mods")

mcp = MCPServer("anythingllm")


@mcp.tool()
async def query_mods(question: str) -> str:
    """Query the mods workspace in AnythingLLM. Returns AI-generated answer based on workspace documents."""
    if not ANYTHINGLLM_KEY:
        return (
            "未配置 AnythingLLM 密钥：请设置环境变量 ANYTHINGLLM_KEY 后重启本服务。"
        )
    url = f"{ANYTHINGLLM_BASE}/workspace/{WORKSPACE_SLUG}/stream-chat"
    headers = {
        "Authorization": f"Bearer {ANYTHINGLLM_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"message": question, "mode": "query"}

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            full_text = []
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:"):].strip()
                if not data_str:
                    continue
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                if chunk.get("type") in ("textResponseChunk", "textResponse"):
                    full_text.append(chunk.get("textResponse", ""))
                if chunk.get("close"):
                    break
            return "".join(full_text) or "No response from AnythingLLM."


if __name__ == "__main__":
    mcp.run("streamable-http")
