import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [MCP] %(levelname)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-knowledge")

ARTICLES_DIR = Path(__file__).resolve().parent / "knowledge" / "articles"

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "knowledge-mcp"
SERVER_VERSION = "1.0.0"


class ArticleStore:
    def __init__(self, articles_dir: Path):
        self.articles: list[dict] = []
        self._load(articles_dir)

    def _load(self, articles_dir: Path) -> None:
        if not articles_dir.is_dir():
            logger.warning("Articles directory not found: %s", articles_dir)
            return
        for fpath in sorted(articles_dir.glob("*.json")):
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    continue
                if "id" not in data or not data["id"]:
                    data["id"] = fpath.stem
                self.articles.append(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Skipping %s: %s", fpath.name, e)
        logger.info("Loaded %d articles from %s", len(self.articles), articles_dir)

    def search(self, keyword: str, limit: int = 5) -> list[dict]:
        kw = keyword.lower()
        results = []
        for art in self.articles:
            score = self._match_score(art, kw)
            if score > 0:
                results.append((score, art))
        results.sort(key=lambda x: (-x[0], x[1].get("title", "")))
        return [self._summarize(a) for _, a in results[:limit]]

    def get_by_id(self, article_id: str) -> Optional[dict]:
        for art in self.articles:
            if art.get("id") == article_id:
                return art
        return None

    def stats(self) -> dict:
        total = len(self.articles)
        source_counter: Counter = Counter()
        tag_counter: Counter = Counter()
        scores = []
        for art in self.articles:
            src = art.get("source") or "unknown"
            source_counter[src] += 1
            tags = art.get("tags")
            if isinstance(tags, list):
                tag_counter.update(str(t) for t in tags if t)
            s = art.get("score")
            if isinstance(s, (int, float)):
                scores.append(s)
        avg_score = round(sum(scores) / len(scores), 1) if scores else 0.0
        return {
            "total_articles": total,
            "source_distribution": dict(source_counter.most_common()),
            "top_tags": [{"tag": t, "count": c} for t, c in tag_counter.most_common(20)],
            "avg_score": avg_score,
        }

    def _match_score(self, art: dict, kw: str) -> int:
        score = 0
        title = art.get("title", "")
        summary = art.get("summary", "")
        tags = art.get("tags")
        if isinstance(tags, list):
            tag_text = " ".join(str(t) for t in tags)
        else:
            tag_text = ""
        if kw in title.lower():
            score += 10
        if kw in summary.lower():
            score += 5
        if kw in tag_text.lower():
            score += 3
        return score

    @staticmethod
    def _summarize(art: dict) -> dict:
        return {
            "id": art.get("id", ""),
            "title": art.get("title", ""),
            "source": art.get("source", ""),
            "summary": art.get("summary", ""),
            "score": art.get("score"),
            "tags": art.get("tags", []),
            "url": art.get("url", ""),
        }


store = ArticleStore(ARTICLES_DIR)


TOOL_DEFINITIONS = [
    {
        "name": "search_articles",
        "description": "Search knowledge articles by keyword in title, summary, and tags",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "Search keyword (case-insensitive)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_article",
        "description": "Get full article content by article ID",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "description": "Article ID (use search_articles to find IDs)",
                },
            },
            "required": ["article_id"],
        },
    },
    {
        "name": "knowledge_stats",
        "description": "Get knowledge base statistics: total articles, source distribution, top tags, average score",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def handle_request(method: str, params: dict, req_id: Any) -> Optional[dict]:
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOL_DEFINITIONS},
        }
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": _call_tool(tool_name, tool_args)}]},
        }
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def _call_tool(name: str, args: dict) -> str:
    if name == "search_articles":
        keyword = args.get("keyword", "")
        limit = int(args.get("limit", 5))
        results = store.search(keyword, limit)
        return json.dumps(results, ensure_ascii=False, indent=2)
    if name == "get_article":
        article_id = args.get("article_id", "")
        article = store.get_by_id(article_id)
        if article is None:
            return json.dumps({"error": f"Article not found: {article_id}"}, ensure_ascii=False)
        return json.dumps(article, ensure_ascii=False, indent=2)
    if name == "knowledge_stats":
        return json.dumps(store.stats(), ensure_ascii=False, indent=2)
    return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)


def serve() -> None:
    logger.info("MCP Knowledge Server starting (PID %d)", __import__("os").getpid())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            logger.error("Invalid JSON: %s", e)
            continue

        method = msg.get("method", "")
        params = msg.get("params", {})
        req_id = msg.get("id")

        is_notification = req_id is None
        if is_notification:
            logger.debug("Notification: %s", method)
            continue

        response = handle_request(method, params, req_id)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
