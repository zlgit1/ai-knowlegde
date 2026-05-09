"""Router 路由模式 - 两层意图分类与分发."""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Callable

from pipeline.model_client import get_provider, chat_with_retry

INTENT_GITHUB_SEARCH = "github_search"
INTENT_KNOWLEDGE_QUERY = "knowledge_query"
INTENT_GENERAL_CHAT = "general_chat"

_KEYWORD_RULES: list[tuple[list[str], str]] = [
    ([
        "github", "repo", "仓库", "开源项目", "repository", "star",
        "fork", "pull request", "issue", "代码库",
    ], INTENT_GITHUB_SEARCH),
    ([
        "知识库", "文章", "知识", "knowledge", "article", "之前采集",
        "分析", "总结", "技术内容", "rss", "trending",
    ], INTENT_KNOWLEDGE_QUERY),
]


def _keyword_match(query: str) -> str | None:
    q = query.lower()
    for keywords, intent in _KEYWORD_RULES:
        for kw in keywords:
            if kw in q:
                return intent
    return None


_LLM_CLASSIFY_PROMPT = """\
You are a query classifier. Classify the user's query into one of these intents:
- github_search: user wants to search GitHub repos, find open source projects, or query code repositories
- knowledge_query: user wants to retrieve information from a local knowledge base (articles, tech summaries, collected content)
- general_chat: everything else — casual conversation, general Q&A, creative tasks

Respond with a single word: github_search / knowledge_query / general_chat

Query: {query}
"""


def _llm_classify(query: str) -> str:
    provider = get_provider()
    try:
        response = chat_with_retry(
            provider,
            [
                {"role": "system", "content": "You are a precise query classifier."},
                {"role": "user", "content": _LLM_CLASSIFY_PROMPT.format(query=query)},
            ],
            temperature=0.1,
            max_tokens=20,
        )
        intent = response.content.strip().lower()
        if intent in (INTENT_GITHUB_SEARCH, INTENT_KNOWLEDGE_QUERY, INTENT_GENERAL_CHAT):
            return intent
        return INTENT_GENERAL_CHAT
    finally:
        provider.close()


def _handle_github_search(query: str) -> str:
    encoded_query = urllib.parse.quote(query)
    url = f"https://api.github.com/search/repositories?q={encoded_query}&sort=stars&order=desc&per_page=5"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = data.get("items", [])
    if not items:
        return "未在 GitHub 上找到相关仓库。"
    lines = [f"找到 {data.get('total_count', 0)} 个结果，展示前 {len(items)} 个："]
    for repo in items:
        lines.append(
            f"- {repo['full_name']} ⭐{repo['stargazers_count']}\n"
            f"  {repo.get('description') or '暂无描述'}\n"
            f"  {repo['html_url']}"
        )
    return "\n".join(lines)


def _handle_knowledge_query(query: str) -> str:
    index_path = os.path.join(
        os.path.dirname(__file__), "..", "knowledge", "articles", "index.json"
    )
    articles: list[dict] = []
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        articles = data if isinstance(data, list) else data.get("articles", [])
    else:
        articles_dir = os.path.join(os.path.dirname(__file__), "..", "knowledge", "articles")
        if os.path.isdir(articles_dir):
            for fname in sorted(os.listdir(articles_dir)):
                if not fname.endswith(".json"):
                    continue
                with open(os.path.join(articles_dir, fname), "r", encoding="utf-8") as f:
                    articles.append(json.load(f))

    if not articles:
        return "知识库为空或目录不存在。"

    keywords = [
        w for w in re.split(r"[\s,，。、/\\:：;；()（）\[\]【】{}]+", query)
        if len(w) > 1
    ]
    matched = []
    for art in articles:
        title = art.get("title", "")
        summary = art.get("summary", "")
        tags = art.get("tags", [])
        text = (title + " " + summary + " " + " ".join(tags)).lower()
        if any(kw.lower() in text for kw in keywords):
            matched.append(art)
            if len(matched) >= 5:
                break

    if not matched:
        provider = get_provider()
        try:
            response = chat_with_retry(
                provider,
                [
                    {"role": "system", "content": "你是知识库助手。未找到相关文章，请礼貌告知用户并建议换关键词。"},
                    {"role": "user", "content": query},
                ],
            )
            return response.content
        finally:
            provider.close()

    lines = [f"在知识库中找到 {len(matched)} 篇相关文章："]
    for art in matched:
        lines.append(f"- {art.get('title', '无标题')}")
        if art.get("summary"):
            lines.append(f"  {art['summary'][:120]}")
        if art.get("url"):
            lines.append(f"  \U0001F517 {art['url']}")
    return "\n".join(lines)


def _handle_general_chat(query: str) -> str:
    provider = get_provider()
    try:
        response = chat_with_retry(
            provider,
            [{"role": "user", "content": query}],
        )
        return response.content
    finally:
        provider.close()


_HANDLERS: dict[str, Callable[[str], str]] = {
    INTENT_GITHUB_SEARCH: _handle_github_search,
    INTENT_KNOWLEDGE_QUERY: _handle_knowledge_query,
    INTENT_GENERAL_CHAT: _handle_general_chat,
}


def route(query: str) -> str:
    if not query or not query.strip():
        return "请输入有效的问题。"
    query = query.strip()
    intent = _keyword_match(query) or _llm_classify(query)
    handler = _HANDLERS.get(intent, _handle_general_chat)
    return handler(query)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
        print(f"Q: {q}")
        result = route(q)
        print(f"A: {result}")
    else:
        test_queries = [
            "找一下 n8n 这个开源项目",
            "帮我搜一下 GitHub 上关于 autogpt 的仓库",
            "知识库里有没有关于工作流自动化的文章",
            "之前采集的 n8n 文章给我看看",
            "今天天气怎么样",
            "用 Python 实现一个快排",
        ]
        for q in test_queries:
            print(f"\n{'='*60}")
            print(f"Q: {q}")
            result = route(q)
            print(f"A: {result[:300]}{'...' if len(result) > 300 else ''}")
