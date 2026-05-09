"""LangGraph 工作流图 — 采集 → 分析 → 整理 → 审核（循环）→ 保存."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langgraph.graph import END, StateGraph

from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from workflows.state import KBState


def _review_router(state: KBState) -> str:
    """审核路由：通过 → save，不通过 → organize（修正后重审）。

    Args:
        state: 当前工作流状态，含 review_passed 标志。

    Returns:
        目标节点名 "save" 或 "organize"。
    """
    if state.get("review_passed", False):
        return "save"
    return "organize"


def build_graph() -> StateGraph:
    """构建并编译 LangGraph 工作流，返回可执行的 app。

    工作流拓扑：
        collect → analyze → organize → review ──passed──→ save → END
                                          └──not_passed──→ organize（循环）

    Returns:
        编译后的 StateGraph，可用 .stream() 或 .invoke() 执行。
    """
    # 初始化状态图，绑定 KBState 类型
    graph = StateGraph(KBState)

    # 注册 5 个节点，每个节点是 (KBState) -> dict 的纯函数
    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    # 线性边：数据依次流过各节点
    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    # 条件边：review 后根据 review_passed 分支
    graph.add_conditional_edges(
        "review",
        _review_router,
        {"save": "save", "organize": "organize"},
    )

    # 入口与终止
    graph.set_entry_point("collect")
    graph.add_edge("save", END)

    return graph.compile()


def print_node_output(step: str, state: KBState):
    """打印节点的关键输出摘要，用于流式执行时观察中间结果。

    Args:
        step: 节点名称（collect / analyze / organize / review / save）。
        state: 当前完整工作流状态。
    """
    if step == "collect":
        sources = state.get("sources", [])
        print(f"  ├ sources: {len(sources)} 条")
        for s in sources[:3]:
            print(f"  │  - {s.get('title', '')}")
    elif step == "analyze":
        analyses = state.get("analyses", [])
        print(f"  ├ analyses: {len(analyses)} 条")
        for a in analyses[:2]:
            print(f"  │  - score={a.get('score', 'N/A')}, tags={a.get('tags', [])}")
    elif step == "organize":
        articles = state.get("articles", [])
        print(f"  ├ articles: {len(articles)} 条")
        for a in articles[:2]:
            print(f"  │  - {a.get('title', '')}")
    elif step == "review":
        print(f"  ├ passed={state.get('review_passed')}, iteration={state.get('iteration')}")
        if state.get("review_feedback"):
            print(f"  └ feedback: {state['review_feedback'][:80]}")
    elif step == "save":
        articles = state.get("articles", [])
        print(f"  ├ saved: {len(articles)} 条")
        tracker = state.get("cost_tracker", {})
        print(f"  └ total_tokens: {tracker.get('total_tokens', 0)}")


if __name__ == "__main__":
    # 编译工作流
    app = build_graph()

    # 初始状态：空列表、未审核、第 1 轮
    initial_state: KBState = {
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 1,
        "cost_tracker": {},
    }

    print("=" * 60)
    print("LangGraph 工作流 开始执行")
    print("=" * 60)

    # 流式执行：每次迭代返回一个节点的输出
    full_state: KBState = dict(initial_state)
    for update in app.stream(initial_state, stream_mode="updates"):
        for node_name, node_output in update.items():
            print(f"\n[{node_name}]")
            full_state.update(node_output)
            print_node_output(node_name, full_state)

    print("\n" + "=" * 60)
    print("执行完成")
