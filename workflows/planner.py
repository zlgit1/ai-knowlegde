"""Planner Agent — 动态规划节点（V3 流水线节点 ①）

核心原则：只规划不执行（Plan, don't execute）。
Planner 的输出写入 state["plan"]，被下游 Collector/Organizer/Reviewer 共同消费。
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from workflows.state import KBState


def plan_strategy(target_count: int | None = None) -> dict:
    """根据目标采集量选择策略 — 最小可运行 Planner"""
    if target_count is None:
        target_count = int(os.getenv("PLANNER_TARGET_COUNT", "10"))

    if target_count >= 20:
        return {
            "strategy": "full",
            "per_source_limit": 20,
            "relevance_threshold": 0.4,
            "max_iterations": 3,
            "rationale": f"目标 {target_count} 条，启用深度模式（质量优先）",
        }
    elif target_count >= 10:
        return {
            "strategy": "standard",
            "per_source_limit": 10,
            "relevance_threshold": 0.5,
            "max_iterations": 2,
            "rationale": f"目标 {target_count} 条，启用标准模式（平衡）",
        }
    else:
        return {
            "strategy": "lite",
            "per_source_limit": 5,
            "relevance_threshold": 0.7,
            "max_iterations": 1,
            "rationale": f"目标 {target_count} 条，启用精简模式（成本优先）",
        }


def planner_node(state: KBState) -> dict:
    """LangGraph 节点：把策略写入 state['plan']"""
    plan = plan_strategy()
    print(
        f"[Planner] 策略={plan['strategy']}, 每源={plan['per_source_limit']} 条, "
        f"阈值={plan['relevance_threshold']}, {plan['rationale']}"
    )
    return {"plan": plan}
