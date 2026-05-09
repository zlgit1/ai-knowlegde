"""基础设施 — LLM chat / chat_json / accumulate_usage / get_cost_guard.

各 Agent 节点已拆分到独立模块（collector / analyzer / organizer / reviewer / reviser），
本文件仅保留各模块共享的底层函数。
"""

import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.model_client import get_provider, chat_with_retry
from tests.cost_guard import CostGuard, BudgetExceededError


_COST_GUARD: CostGuard | None = None


def get_cost_guard() -> CostGuard:
    """获取全局 CostGuard 单例（懒加载）。"""
    global _COST_GUARD
    if _COST_GUARD is None:
        budget = float(os.environ.get("BUDGET_YUAN", "1.0"))
        _COST_GUARD = CostGuard(budget_yuan=budget)
    return _COST_GUARD


def chat(prompt: str, system: str = "", node_name: str = "unknown", **kwargs) -> tuple[str, dict]:
    """发送 prompt 给 LLM，返回 (text, usage)。

    Args:
        prompt: 用户提示词。
        system: 系统提示词（可选）。
        node_name: 调用节点名称（用于成本追踪）。
        **kwargs: 传递给 chat_with_retry 的额外参数。

    Returns:
        (response_text, usage_dict)

    Raises:
        BudgetExceededError: 当全局预算超限时。
    """
    provider = get_provider()
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        temperature = kwargs.pop("temperature", 0.3)
        response = chat_with_retry(provider, messages, temperature=temperature)
        usage_dict = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
        guard = get_cost_guard()
        guard.record(node_name, usage_dict, provider.model)
        guard.check()
        return response.content, usage_dict
    finally:
        provider.close()


def chat_json(prompt: str, system: str = "", node_name: str = "unknown", **kwargs) -> tuple[Any, dict]:
    """发送 prompt 给 LLM 并解析 JSON 响应，返回 (parsed_json, usage)。"""
    sys_prompt = (
        (system + "\nYou must respond with valid JSON only, no other text.")
        if system else
        "You must respond with valid JSON only, no other text."
    )
    text, usage = chat(prompt, system=sys_prompt, node_name=node_name, **kwargs)
    text = text.strip()
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith(("{", "[")):
                text = part
                break
    return json.loads(text), usage


def accumulate_usage(tracker: dict, usage: dict) -> dict:
    """累加 token 用量到 tracker 并返回新 dict。"""
    t = dict(tracker) if tracker else {}
    records = list(t.get("records", []))
    records.append(usage)
    t["records"] = records
    t["total_prompt_tokens"] = t.get("total_prompt_tokens", 0) + usage.get("prompt_tokens", 0)
    t["total_completion_tokens"] = t.get("total_completion_tokens", 0) + usage.get("completion_tokens", 0)
    t["total_tokens"] = t.get("total_tokens", 0) + usage.get("total_tokens", 0)
    return t
