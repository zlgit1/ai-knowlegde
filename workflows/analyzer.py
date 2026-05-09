"""分析节点 — 对每条 source 调用 LLM 生成摘要、标签、评分。"""

import json

from workflows.state import KBState
from workflows.nodes import chat_json, accumulate_usage

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
