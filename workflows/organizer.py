"""整理节点 — 去重、过滤、PII 掩码后写盘。"""

import json

from workflows.state import KBState
from workflows.nodes import chat_json, accumulate_usage
from tests.security import filter_output

_ORGANIZE_FIX_SYSTEM = """\
You are a knowledge organizer. Revise the article based on the feedback.
Output a JSON object with the same fields: title, url, summary, tags, score, language, topics, source.
"""


def organize_node(state: KBState) -> dict:
    """过滤低分条目、按 URL 去重、有反馈时用 LLM 修正，写盘前对文本字段做 PII 掩码。"""
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

    # ★ 接入点 ⑤ · 写盘前对每条 article 做 PII 掩码
    masked_articles = []
    total_pii = 0
    for art in articles:
        for field in ("summary", "title"):
            if field in art and isinstance(art[field], str):
                filtered, detections = filter_output(art[field], mask=True)
                art[field] = filtered
                total_pii += len(detections)
                if detections:
                    print(f"[Security] {art.get('url', '?')} {field} 掩码 PII：{detections}")
        masked_articles.append(art)

    if total_pii > 0:
        print(f"[Security] organize 阶段共掩码 {total_pii} 处 PII")

    print(f"[Organizer] 整理出 {len(masked_articles)} 条知识条目")
    return {"articles": masked_articles, "cost_tracker": tracker}
