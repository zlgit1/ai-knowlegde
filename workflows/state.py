"""LangGraph 工作流共享状态定义."""

from typing import TypedDict


class KBState(TypedDict):
    """知识工作流的状态，遵循"报告式通信"原则：字段存储结构化摘要而非原始数据。"""

    sources: list[dict]
    """采集到的原始数据摘要列表，每项包含：
       - source (str): 数据来源标识（如 github-trending, hacker-news）
       - url (str): 来源链接
       - title (str): 标题摘要
       - collected_at (str): 采集时间
       - summary (str): 内容摘要（非全文）
    """

    analyses: list[dict]
    """LLM 分析后的结构化结果列表，每项包含：
       - source_id (str): 对应的来源标识
       - score (int): 质量评分（1-10）
       - score_reason (str): 评分理由
       - summary (str): 精炼摘要
       - tags (list[str]): 标签列表
       - highlights (list[str]): 重点提炼（3-5 条）
    """

    articles: list[dict]
    """格式化、去重后的知识条目列表，每项包含：
       - title (str): 文章标题
       - url (str): 原文链接
       - summary (str): 精炼摘要
       - tags (list[str]): 分类标签
       - score (int): 综合评分
       - language (str): 编程语言（如适用）
       - topics (list[str]): 主题分类
       - source (str): 来源标识
    """

    review_feedback: str
    """审核反馈意见，由 Supervisor Agent 生成。
       当审核不通过时记录具体的改进建议，为空字符串表示通过。
    """

    review_passed: bool
    """审核是否通过。
       - True: 质量达标，可进入下一环节或输出
       - False: 需根据 feedback 重新处理
    """

    iteration: int
    """当前审核循环次数（1-based），最多 3 次。
       初始值为 1，每轮审核不通过 +1。
       超过 3 次时强制结束并标记 warning。
    """

    cost_tracker: dict
    """Token 用量追踪摘要，包含：
       - total_prompt_tokens (int): 累计输入 token 数
       - total_completion_tokens (int): 累计输出 token 数
       - total_tokens (int): 累计总 token 数
       - estimated_cost (float): 预估总费用（元）
       - records (list[dict]): 每次调用的明细记录
           每项包含 provider, prompt_tokens, completion_tokens, total_tokens
    """
