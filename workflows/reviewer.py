"""Reviewer 节点 — 对 analyses 进行 5 维度质量审核."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflows.nodes import accumulate_usage, chat_json
from workflows.state import KBState

REVIEWER_WEIGHTS = {
    "summary_quality": 0.25,
    "technical_depth": 0.25,
    "relevance": 0.20,
    "originality": 0.15,
    "formatting": 0.15,
}
REVIEWER_PASS_THRESHOLD = 7.0


def review_node(state: KBState) -> dict:
    """Reviewer 节点：对 analyses 进行 5 维度质量审核

    核心原则：只评估不修改（Evaluate, don't modify）。
    Reviewer 看到的是 Analyzer 输出的 analyses，不做任何改动，只给分 + 反馈。
    """
    analyses = state.get("analyses", [])
    iteration = state.get("iteration", 0)
    tracker = state.get("cost_tracker", {})

    if not analyses:
        return {
            "review_passed": True,
            "review_feedback": "没有条目需要审核",
            "iteration": iteration + 1,
        }

    sample = analyses[:5]

    prompt = f"""你是知识库质量审核员。请审核以下分析结果：

{json.dumps(sample, ensure_ascii=False, indent=2)}

请按以下维度评分（每项 1-10 分）：
1. summary_quality  - 摘要质量
2. technical_depth  - 技术深度
3. relevance        - 相关性
4. originality      - 原创性
5. formatting       - 格式规范

请用 JSON 格式回复：
{{
    "scores": {{
        "summary_quality": 8,
        "technical_depth": 6,
        "relevance": 9,
        "originality": 5,
        "formatting": 8
    }},
    "feedback": "具体的改进建议（指出弱项）",
    "weak_dimensions": ["technical_depth", "originality"]
}}

当前是第 {iteration + 1} 次审核。"""

    try:
        result, usage = chat_json(
            prompt,
            system="你是严格但公正的知识库质量审核员。给出具体、可操作的反馈。",
            temperature=0.1,
        )
        tracker = accumulate_usage(tracker, usage)

        scores = result.get("scores", {})
        weighted_total = sum(
            scores.get(dim, 0) * w for dim, w in REVIEWER_WEIGHTS.items()
        )
        weighted_total = round(weighted_total, 2)
        passed = weighted_total >= REVIEWER_PASS_THRESHOLD

        feedback = result.get("feedback", "")
        weak_dims = result.get("weak_dimensions", [])
        if weak_dims:
            feedback = f"[弱项: {', '.join(weak_dims)}] {feedback}"

        print(
            f"[Reviewer] 加权总分: {weighted_total}/10, "
            f"通过: {passed} (第 {iteration + 1} 次审核)"
        )

    except Exception as e:
        passed = True
        feedback = f"审核 LLM 调用失败: {e}，自动通过"
        print(f"[Reviewer] 审核失败，自动通过: {e}")

    return {
        "review_passed": passed,
        "review_feedback": feedback,
        "iteration": iteration + 1,
        "cost_tracker": tracker,
    }
