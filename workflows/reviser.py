"""Reviser 节点 — 根据审核反馈修正 analyses."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflows.nodes import accumulate_usage, chat_json
from workflows.state import KBState

_REVISE_SYSTEM = """\
You are a skilled editor. Revise the following analyses according to the feedback.
Improve each item's summary, tags, and highlights based on the critique.
Keep the same JSON structure: list of objects with fields (summary, tags, highlights, score, score_reason).
Output ONLY valid JSON, no other text.
"""


def revise_node(state: KBState) -> dict:
    """根据 review_feedback 修正 analyses 列表。"""
    analyses = state.get("analyses", [])
    feedback = state.get("review_feedback", "")

    if not analyses or not feedback:
        print("[ReviseNode] analyses 或 feedback 为空，跳过")
        return {}

    print(f"[ReviseNode] 根据 feedback 修正 {len(analyses)} 条 analyses")

    prompt = (
        f"Feedback:\n{feedback}\n\n"
        f"Analyses:\n"
        f"{__import__('json').dumps(analyses, ensure_ascii=False, indent=2)}\n\n"
        "Revise each item's summary to address the feedback. "
        "Improve tags and highlights where appropriate. "
        "Return the full revised analyses list."
    )

    tracker = dict(state.get("cost_tracker", {}))
    result, usage = chat_json(prompt, 
                              system=_REVISE_SYSTEM, 
                              temperature=0.4,
                              node_name="revise")
    tracker = accumulate_usage(tracker, usage)

    improved = result if isinstance(result, list) else result.get("analyses", analyses)

    print(f"[ReviseNode] 修正完成，返回 {len(improved)} 条")
    return {"analyses": improved, "cost_tracker": tracker}
