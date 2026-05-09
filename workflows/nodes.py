"""LangGraph 工作流节点函数 — 采集 → 分析 → 整理 → 审核 → 保存."""

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflows.state import KBState
from pipeline.model_client import get_provider, chat_with_retry


def chat(prompt: str, system: str = "", **kwargs) -> tuple[str, dict]:
    """发送 prompt 给 LLM，返回 (text, usage)。"""
    provider = get_provider()
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        temperature = kwargs.pop("temperature", 0.3)
        response = chat_with_retry(provider, messages, temperature=temperature)
        return response.content, {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    finally:
        provider.close()


def chat_json(prompt: str, system: str = "", **kwargs) -> tuple[Any, dict]:
    """发送 prompt 给 LLM 并解析 JSON 响应，返回 (parsed_json, usage)。"""
    sys_prompt = (
        (system + "\nYou must respond with valid JSON only, no other text.")
        if system else
        "You must respond with valid JSON only, no other text."
    )
    text, usage = chat(prompt, system=sys_prompt, **kwargs)
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Node: Collect ──────────────────────────────────────────

_COLLECT_QUERY = "AI+language:python+sort:stars"
_GITHUB_API = "https://api.github.com/search/repositories"


def collect_node(state: KBState) -> dict:
    """调用 GitHub Search API 采集 AI 相关仓库，返回部分状态更新。"""
    plan = state.get("plan", {}) or {}
    limit = int(plan.get("per_source_limit", 10))
    print(f"[CollectNode] 开始采集 GitHub AI 仓库 (per_page={limit})...")
    url = f"{_GITHUB_API}?q={_COLLECT_QUERY}&per_page={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github.v3+json"})
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

    print(f"[CollectNode] 采集到 {len(sources)} 条数据")
    return {"sources": sources}


# ── Node: Analyze ──────────────────────────────────────────

_ANALYZE_SYSTEM = """\
You are a technical analyst. Analyze the given GitHub repository data and output a JSON object with:
- score: float from 0.0 to 1.0 (quality and relevance)
- score_reason: string (why this score was given)
- summary: string (Chinese summary, 2-3 sentences)
- tags: list of strings (lowercase, 3-5 tags)
- highlights: list of strings (3 key highlights)
"""


def analyze_node(state: KBState) -> dict:
    """对每条 source 调用 LLM 生成中文摘要、标签和评分。"""
    print("[AnalyzeNode] 开始分析采集数据...")
    analyses = list(state.get("analyses", []))
    tracker = dict(state.get("cost_tracker", {}))

    for src in state.get("sources", []):
        prompt = json.dumps(src, ensure_ascii=False, indent=2)
        result, usage = chat_json(prompt, system=_ANALYZE_SYSTEM)
        tracker = accumulate_usage(tracker, usage)
        analyses.append({
            "source_id": src.get("source", ""),
            "url": src.get("url", ""),
            "title": src.get("title", ""),
            "score": result.get("score", 0.0),
            "score_reason": result.get("score_reason", ""),
            "summary": result.get("summary", ""),
            "tags": result.get("tags", []),
            "highlights": result.get("highlights", []),
        })

    print(f"[AnalyzeNode] 完成 {len(analyses)} 条分析")
    return {"analyses": analyses, "cost_tracker": tracker}


# ── Node: Organize ─────────────────────────────────────────

_ORGANIZE_FIX_SYSTEM = """\
You are a knowledge organizer. Revise the article based on the feedback.
Output a JSON object with the same fields: title, url, summary, tags, score, language, topics, source.
"""


def organize_node(state: KBState) -> dict:
    """过滤低分条目、按 URL 去重、有反馈时用 LLM 修正。"""
    plan = state.get("plan", {}) or {}
    threshold = float(plan.get("relevance_threshold", 0.5))
    print(f"[OrganizeNode] 开始整理数据 (threshold={threshold})...")
    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")
    tracker = dict(state.get("cost_tracker", {}))

    articles: list[dict] = []
    seen_urls: set[str] = set()

    for item in analyses:
        score = item.get("score", 0)
        try:
            if float(score) < threshold:
                continue
        except (ValueError, TypeError):
            continue

        url = item.get("url", "")
        if url in seen_urls:
            continue
        seen_urls.add(url)

        base = {
            "title": item.get("title", ""),
            "url": url,
            "summary": item.get("summary", ""),
            "tags": item.get("tags", []),
            "score": score,
            "language": "",
            "topics": item.get("tags", []),
            "source": "github-search",
        }

        if feedback and state.get("iteration", 0) > 0:
            prompt = (
                f"Original article:\n{json.dumps(base, ensure_ascii=False, indent=2)}\n\n"
                f"Feedback:\n{feedback}\n\nRevise accordingly."
            )
            result, usage = chat_json(prompt, system=_ORGANIZE_FIX_SYSTEM)
            tracker = accumulate_usage(tracker, usage)
            result["url"] = base["url"]
            result["title"] = result.get("title") or base["title"]
            articles.append(result)
        else:
            articles.append(base)

    print(f"[OrganizeNode] 整理完成，保留 {len(articles)} 条")
    return {"articles": articles, "cost_tracker": tracker}


# ── Node: Review ───────────────────────────────────────────

_REVIEW_SYSTEM = """\
You are a quality reviewer. Score the knowledge articles on 4 dimensions:
- 摘要质量 (summary_quality): 1-10, clarity and informativeness of the summary
- 标签准确 (tag_accuracy): 1-10, relevance and precision of tags
- 分类合理 (category_reasonableness): 1-10, appropriateness of categorization
- 一致性 (consistency): 1-10, internal consistency of the article data

Output JSON:
{
  "passed": bool,
  "overall_score": float,
  "feedback": string,
  "scores": { "summary_quality": int, "tag_accuracy": int, "category_reasonableness": int, "consistency": int }
}
"""


def review_node(state: KBState) -> dict:
    """LLM 四维度评分审核，iteration >= 2 时强制通过。"""
    iteration = state.get("iteration", 1)
    print(f"[ReviewNode] 开始审核 (第 {iteration} 轮)...")

    if iteration >= 2:
        print("[ReviewNode] 已达最大轮次，强制通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration,
        }

    articles = state.get("articles", [])
    if not articles:
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    tracker = dict(state.get("cost_tracker", {}))
    prompt = json.dumps(articles, ensure_ascii=False, indent=2)
    result, usage = chat_json(prompt, system=_REVIEW_SYSTEM)
    tracker = accumulate_usage(tracker, usage)

    passed = result.get("passed", False)
    overall = result.get("overall_score", 0.0)

    print(f"[ReviewNode] 评分={overall}, 通过={passed}")
    return {
        "review_passed": passed,
        "review_feedback": "" if passed else result.get("feedback", ""),
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }


# ── Node: Save ─────────────────────────────────────────────

_ARTICLES_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "articles"


def save_node(state: KBState) -> dict:
    """将 articles 写入 knowledge/articles/ 目录并更新 index.json。"""
    print("[SaveNode] 开始保存知识条目...")
    _ARTICLES_DIR.mkdir(parents=True, exist_ok=True)

    articles = state.get("articles", [])
    saved = []
    for art in articles:
        fname = f"article-{len(saved)}.json"
        fpath = _ARTICLES_DIR / fname
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(art, f, ensure_ascii=False, indent=2)
        saved.append(fname)

    index_path = _ARTICLES_DIR / "index.json"
    existing = []
    if index_path.exists():
        with open(index_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    existing = existing if isinstance(existing, list) else existing.get("articles", [])

    existing_map = {a.get("url", ""): a for a in existing}
    for art in articles:
        existing_map[art.get("url", "")] = art

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(list(existing_map.values()), f, ensure_ascii=False, indent=2)

    print(f"[SaveNode] 保存 {len(saved)} 个文件，索引 {len(existing_map)} 条")
    return {"articles": list(existing_map.values())}
