# AnythingLLM MCP Bridge

将 AnythingLLM 的 `mods` 工作区封装成一个 MCP 工具，供支持 Streamable HTTP
的 MCP 客户端调用。

## 功能

工具名：`query_mods`

| 参数 | 类型 | 说明 |
|------|------|------|
| `question` | string | 向 `mods` 工作区提出的问题 |

工具会把问题发送到 AnythingLLM 的流式对话接口，累积 `textResponseChunk`
和 `textResponse` 内容，然后返回完整文本。

## 前置条件

- AnythingLLM 运行在 <http://localhost:3001>
- 已创建 `mods` 工作区并完成文档嵌入
- Python 3.10+

## 安装与启动

```powershell
pip install mcp httpx
# 先设置密钥（必选，源码里不再写死）
$env:ANYTHINGLLM_KEY = "你的 AnythingLLM API Key"
python server.py
```

依赖 `mcp` 2.x（`from mcp.server import MCPServer`）与 Python 3.10+。
服务使用 MCP Streamable HTTP 传输。默认 MCP 地址由 `mcp.run("streamable-http")`
决定，通常为 <http://127.0.0.1:8000/mcp>，请以启动日志为准。

> 没有设置 `ANYTHINGLLM_KEY` 时服务照常启动，但 `query_mods` 会直接返回
> 「未配置 AnythingLLM 密钥」的中文提示，不会真的发请求。

## 配置

三个环境变量控制连接，都有默认值：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ANYTHINGLLM_KEY` | 空（**必须设置**） | AnythingLLM 的 API Key |
| `ANYTHINGLLM_BASE` | `http://localhost:3001/api/v1` | 服务地址（末尾斜杠会被去掉） |
| `ANYTHINGLLM_WORKSPACE` | `mods` | 工作区 slug |

Linux / macOS 下用 `export ANYTHINGLLM_KEY=...`，或写进 `.env` 由启动脚本加载。

> 本文件原先把一个课程演示 Key 写死在 `server.py` 源码里；现已改为只从环境变量读取，
> 源码与仓库中不再包含任何密钥（本仓库首次提交之前完成，因此提交历史里也不会出现它）。
> 那把演示 Key 仍然建议直接作废：它曾经以明文形式存在于课程文件中。

## 直接请求 AnythingLLM

服务调用以下接口：

```text
POST /api/v1/workspace/mods/stream-chat
```

请求模式为 `query`，超时时间为 120 秒。

## 安全说明

- API Key 只从环境变量 `ANYTHINGLLM_KEY` 读取，源码与仓库里没有任何密钥。
- AnythingLLM 和本服务都不应直接暴露到公网。
- 不要通过命令行参数传密钥（会留在 shell 历史里）；用环境变量或 `.env`（已在 `.gitignore` 中）。

