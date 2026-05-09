"""Reviewer 节点 — 对 analyses 进行五维度加权评分审核."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflows.nodes import accumulate_usage, chat_json
from workflows.state import KBState

_DIMENSIONS = [
    ("summary_quality", "摘要质量", 0.25),
    ("technical_depth", "技术深度", 0.25),
    ("relevance", "相关性", 0.20),
    ("originality", "原创性", 0.15),
    ("formatting", "格式规范", 0.15),
]

_REVIEW_SYSTEM = """\
You are a strict quality reviewer. Score the following analyses on 5 dimensions (1-10 each).

Dimensions:
- summary_quality (摘要质量): clarity, informativeness, conciseness
- technical_depth (技术深度): depth of technical insight, detail level
- relevance (相关性): relevance to the task/domain
- originality (原创性): novelty, unique perspective
- formatting (格式规范): structure, completeness, adherence to format

Output ONLY valid JSON:
{
  "scores": { "summary_quality": int, "technical_depth": int, "relevance": int, "originality": int, "formatting": int },
  "feedback": "string (detailed feedback in Chinese, point out weaknesses)"
}
"""


def _calc_weighted_score(scores: dict) -> float:
    total = 0.0
    for dim_key, _dim_name, weight in _DIMENSIONS:
        val = scores.get(dim_key, 5)
        total += float(val) * weight
    return round(total, 2)


def review_node(state: KBState) -> dict:
    """对 state['analyses'] 进行五维度加权评分审核。"""
    iteration = state.get("iteration", 1)
    print(f"[ReviewNode] 开始审核 analyses (第 {iteration} 轮)...")

    if iteration >= 2:
        print("[ReviewNode] 已达最大轮次，强制通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration,
        }

    analyses = state.get("analyses", [])[:5]
    if not analyses:
        print("[ReviewNode] 无 analyses，自动通过")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
        }

    plan = state.get("plan", "")
    prompt_parts = [f"Task: {plan}\n"] if plan else []
    prompt_parts.append("Analyses to review:")
    prompt_parts.append("\n".join(
        f"[{i}] {a.get('summary', '')[:200]} | tags={a.get('tags', [])}"
        for i, a in enumerate(analyses)
    ))
    prompt = "\n".join(prompt_parts)

    tracker = dict(state.get("cost_tracker", {}))
    try:
        result, usage = chat_json(prompt, system=_REVIEW_SYSTEM, temperature=0.1)
        tracker = accumulate_usage(tracker, usage)
        raw_scores = result.get("scores", {})
        feedback = result.get("feedback", "")
    except Exception as e:
        print(f"[ReviewNode] LLM 调用失败，自动通过: {e}")
        return {
            "review_passed": True,
            "review_feedback": "",
            "iteration": iteration + 1,
            "cost_tracker": tracker,
        }

    weighted = _calc_weighted_score(raw_scores)
    passed = weighted >= 7.0

    print(f"[ReviewNode] 加权总分={weighted}, 通过={passed}")
    if not passed:
        print(f"  └ feedback: {feedback[:100]}")

    return {
        "review_passed": passed,
        "review_feedback": "" if passed else feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }
