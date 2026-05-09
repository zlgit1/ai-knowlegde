
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import END, StateGraph

from workflows.human_flag import human_flag_node
from workflows.collector import collect_node
from workflows.analyzer import analyze_node
from workflows.organizer import organize_node
from workflows.planner import planner_node
from workflows.reviewer import review_node
from workflows.reviser import revise_node
from workflows.state import KBState


def route_after_review(state: KBState) -> str:
    """条件路由：读 state['plan']['max_iterations']，不再硬编码 3"""
    plan = state.get("plan", {}) or {}
    max_iter = int(plan.get("max_iterations", 3))
    iteration = state.get("iteration", 0)

    if state.get("review_passed", False):
        return "organize"
    elif iteration >= max_iter:
        return "human_flag"
    else:
        return "revise"


def build_graph() -> StateGraph:
    graph = StateGraph(KBState)

    graph.add_node("plan", planner_node)
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("review", review_node)
    graph.add_node("revise", revise_node)
    graph.add_node("organize", organize_node)
    graph.add_node("human_flag", human_flag_node)

    graph.add_edge("plan", "collect")
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "review")

    graph.add_conditional_edges(
        "review",
        route_after_review,
        {
            "organize": "organize",
            "revise": "revise",
            "human_flag": "human_flag",
        },
    )

    graph.add_edge("revise", "review")
    graph.add_edge("organize", END)
    graph.add_edge("human_flag", END)

    graph.set_entry_point("plan")
    return graph.compile()


def print_node_output(step: str, state: KBState):
    """打印节点的关键输出摘要，用于流式执行时观察中间结果。"""
    if step == "plan":
        plan = state.get("plan", {})
        print(f"  ├ strategy: {plan.get('strategy')}, threshold: {plan.get('relevance_threshold')}")
        print(f"  ├ per_source_limit: {plan.get('per_source_limit')}, max_iterations: {plan.get('max_iterations')}")
    elif step == "collect":
        sources = state.get("sources", [])
        print(f"  ├ sources: {len(sources)} 条")
        for s in sources[:3]:
            print(f"  │  - {s.get('title', '')}")
    elif step == "analyze":
        analyses = state.get("analyses", [])
        print(f"  ├ analyses: {len(analyses)} 条")
        for a in analyses[:2]:
            print(f"  │  - score={a.get('score', 'N/A')}, tags={a.get('tags', [])}")
    elif step == "review":
        print(f"  ├ passed={state.get('review_passed')}, iteration={state.get('iteration')}")
        if state.get("review_feedback"):
            print(f"  └ feedback: {state['review_feedback'][:80]}")
    elif step == "revise":
        print(f"  ├ revise done, analyses: {len(state.get('analyses', []))} 条")
    elif step == "organize":
        articles = state.get("articles", [])
        print(f"  ├ articles: {len(articles)} 条")
        for a in articles[:2]:
            print(f"  │  - {a.get('title', '')}")
        tracker = state.get("cost_tracker", {})
        print(f"  └ total_tokens: {tracker.get('total_tokens', 0)}")
    elif step == "human_flag":
        print(f"  ├ needs_human_review: {state.get('needs_human_review')}")


if __name__ == "__main__":
    from workflows.nodes import get_cost_guard, BudgetExceededError

    app = build_graph()

    initial_state: KBState = {
        "plan": {},
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 1,
        "cost_tracker": {},
        "needs_human_review": False,
    }

    print("=" * 60)
    print("LangGraph 工作流 开始执行")
    print("=" * 60)

    full_state: KBState = dict(initial_state)

    try:
        for update in app.stream(initial_state, stream_mode="updates"):
            for node_name, node_output in update.items():
                print(f"\n[{node_name}]")
                full_state.update(node_output)
                print_node_output(node_name, full_state)
        print("\n=== 工作流完成 ===")
    except BudgetExceededError as e:
        print(f"\n[FATAL] 预算熔断触发：{e}")

    # ★ 收尾打报告 · 落盘到 knowledge/cost-report.json
    guard = get_cost_guard()
    report = guard.get_report()
    print(f"\n[CostGuard] 总调用 {report['total_calls']} 次 · 总成本 ¥{report['total_cost_yuan']}")
    print(f"[CostGuard] 按节点：{report['cost_by_node']}")
    guard.save_report()

    print("\n" + "=" * 60)
    print("执行完成")