"""连通性自检：给配置页的「测试连接」按钮用，不参与对话流程。

第一性原理：用户填完接口地址 / 密钥 / 模型后，最想知道的只有一件事——
「这套配置能不能真的发出去」。失败原因（密钥错、模型名错、地址不可达）
差别很大，所以这里把 SDK 的异常种类翻成中文，而不是笼统一句「请求失败」。

本模块只依赖 openai，不碰任何界面技术，可以脱离终端被别的前端复用。
"""

from __future__ import annotations

from typing import Any

#: 探针用的极小请求：只要求模型回一个字符，尽量不吃额度
PROBE_MAX_TOKENS = 8
PROBE_PROMPT = "只回复两个字：可用"
PROBE_TIMEOUT = 20.0


def probe_connection(
    base_url: str,
    api_key: str,
    model_name: str,
    *,
    timeout: float = PROBE_TIMEOUT,
    client: Any | None = None,
) -> tuple[bool, str]:
    """发一次极小的非流式请求；返回 ``(可用?, 一句话说明)``。

    ``client`` 用于测试注入：给定时不再新建 OpenAI 客户端，也不校验参数格式。
    """
    if client is None:
        missing = [
            name
            for name, value in (
                ("接口地址", base_url),
                ("API 密钥", api_key),
                ("模型名称", model_name),
            )
            if not str(value or "").strip()
        ]
        if missing:
            return False, "缺少必填项：%s" % "、".join(missing)
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=base_url.strip(), api_key=api_key.strip(), timeout=timeout
            )
        except Exception as exc:
            return False, "无法创建客户端：%s" % _brief(str(exc))

    try:
        result = client.chat.completions.create(
            model=model_name.strip(),
            messages=[{"role": "user", "content": PROBE_PROMPT}],
            max_tokens=PROBE_MAX_TOKENS,
            stream=False,
        )
    except Exception as exc:
        return False, _explain(exc)

    text = _first_content(result)
    if text is None:
        return True, "接口有响应，但没有可读内容（可能是非标准兼容实现）"
    return True, "连接正常：%s" % (text[:40] or "(空回复)")


def _first_content(result: Any) -> str | None:
    """尽最大努力从响应里取出正文；结构不认识时返回 None。"""
    try:
        choices = getattr(result, "choices", None) or result["choices"]
    except (TypeError, KeyError):
        return None
    if not choices:
        return ""
    first = choices[0]
    message = getattr(first, "message", None) or (
        first.get("message") if isinstance(first, dict) else None
    )
    if message is None:
        return None
    content = getattr(message, "content", None)
    if content is None and isinstance(message, dict):
        content = message.get("content")
    return "" if content is None else str(content)


def _explain(exc: Exception) -> str:
    """把 SDK 异常翻成一句可操作的中文提示。"""
    name = type(exc).__name__
    detail = _brief(str(exc))
    status = getattr(exc, "status_code", None)
    if name in ("AuthenticationError", "PermissionDeniedError") or status == 401:
        return "API 密钥无效或被拒（401）：请核对密钥与接口地址是否配对"
    if name == "NotFoundError" or status == 404:
        return (
            "接口或模型不存在（404）：检查 base_url 是否要带 /v1、"
            "模型名是否与服务商一致"
        )
    if name in ("BadRequestError", "UnprocessableEntityError") or status in (400, 422):
        return "请求被拒绝（%s）：%s" % (status or "400", detail)
    if status == 429 or name == "RateLimitError":
        return "额度或速率限制（429）：余额不足、并发超限，稍后再试或换模型"
    if name in ("APIConnectionError", "APITimeoutError") or status is None:
        return "连不上接口：%s（检查网络、代理与 base_url 的协议头）" % (detail or name)
    if status is not None and status >= 500:
        return "服务端错误（%s）：%s" % (status, detail)
    return "%s：%s" % (name, detail)


def _brief(text: str, limit: int = 200) -> str:
    cleaned = " ".join(str(text or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "…"
