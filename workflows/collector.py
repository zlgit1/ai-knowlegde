"""采集节点 — 从 GitHub Search API 拉取 AI 仓库数据，清洗后注入状态。"""

import json
import os
import urllib.request
from datetime import datetime, timezone

from workflows.state import KBState
from tests.security import sanitize_input

_COLLECT_QUERY = "AI+language:python+sort:stars"
_GITHUB_API = "https://api.github.com/search/repositories"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_node(state: KBState) -> dict:
    """调用 GitHub Search API 采集 AI 相关仓库，并通过 sanitize_input 清洗文本字段。"""
    plan = state.get("plan", {}) or {}
    limit = int(plan.get("per_source_limit", 10))
    print(f"[CollectNode] 开始采集 GitHub AI 仓库 (per_page={limit})...")

    token = os.environ.get("GITHUB_TOKEN")
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{_GITHUB_API}?q={_COLLECT_QUERY}&per_page={limit}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    sources = []
    for item in data.get("items", []):
        sources.append({
            "source": "github-search",
            "url": item["html_url"],
            "title": item["full_name"],
            "collected_at": _now(),
            "summary": item.get("description") or "",
            "stars": item.get("stargazers_count", 0),
            "language": item.get("language") or "",
        })

    # ★ 接入点 ④ · sanitize 每条 source 的文本字段
    cleaned_sources = []
    total_warnings = 0
    for s in sources:
        for field in ("title", "summary"):
            if field in s and isinstance(s[field], str):
                cleaned, warnings = sanitize_input(s[field])
                s[field] = cleaned
                total_warnings += len(warnings)
                if warnings:
                    print(f"[Security] {s.get('url', '?')} {field} 检出注入模式：{warnings}")
        cleaned_sources.append(s)

    if total_warnings > 0:
        print(f"[Security] collect 阶段共拦截 {total_warnings} 处可疑输入")

    print(f"[Collector] 采集到 {len(cleaned_sources)} 条原始数据")
    return {"sources": cleaned_sources}
