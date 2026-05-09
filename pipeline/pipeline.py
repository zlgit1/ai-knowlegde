import argparse
import html
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from hashlib import md5
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from model_client import create_provider, chat_with_retry

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "knowledge" / "raw"
ARTICLES_DIR = PROJECT_ROOT / "knowledge" / "articles"

GITHUB_API_URL = "https://api.github.com/search/repositories"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "ai-knowledge-pipeline/1.0",
}

RSS_FEEDS = [
    "https://hnrss.org/frontpage",
    "http://export.arxiv.org/rss/cs.AI",
]

ANALYSIS_PROMPT = """You are an AI knowledge analyst working in Chinese. Analyze the following article and return ONLY valid JSON (no markdown, no code fences):

{{
  "summary": "2-3 sentence Chinese summary",
  "highlights": ["key point 1", "key point 2", "key point 3"],
  "score": <integer 1-10>,
  "score_reason": "1-2 sentence explanation of the score in Chinese",
  "tags": ["tag1", "tag2", "tag3"]
}}

Article title: {title}
Description: {description}
"""


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s")
    logger.debug("Verbose logging enabled")


def ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug("Ensured directories: %s, %s", RAW_DIR, ARTICLES_DIR)


def _generate_id(url: str) -> str:
    return md5(url.encode("utf-8")).hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Step 1: Collect
# ---------------------------------------------------------------------------

def collect_from_github(limit: int, dry_run: bool = False) -> list[dict]:
    logger.info("Collecting up to %d items from GitHub Search API", limit)
    if dry_run:
        logger.info("[DRY-RUN] Would fetch GitHub Search API")
        return []

    token = os.environ.get("GITHUB_TOKEN")
    headers = dict(GITHUB_HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    query = "topic:ai OR topic:machine-learning OR topic:llm"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, 100)}

    try:
        with httpx.Client(headers=headers, timeout=30.0) as client:
            resp = client.get(GITHUB_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as e:
        logger.error("GitHub API request failed: %s", e)
        return []

    items = data.get("items", [])
    results = []
    for repo in items[:limit]:
        item = {
            "id": _generate_id(repo["html_url"]),
            "source": "github-search",
            "title": repo["full_name"],
            "url": repo["html_url"],
            "description": repo.get("description") or "",
            "popularity": repo.get("stargazers_count", 0),
            "language": repo.get("language"),
            "topics": repo.get("topics", []),
            "collected_at": _now_iso(),
        }
        results.append(item)

    logger.info("Collected %d items from GitHub", len(results))
    return results


def collect_from_rss(limit: int, dry_run: bool = False) -> list[dict]:
    logger.info("Collecting up to %d items from %d RSS feeds", limit, len(RSS_FEEDS))
    if dry_run:
        logger.info("[DRY-RUN] Would fetch RSS feeds: %s", RSS_FEEDS)
        return []

    results = []
    for feed_url in RSS_FEEDS:
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(feed_url)
                resp.raise_for_status()
                items = _parse_rss_items(resp.text, feed_url)
                for item in items[:limit]:
                    item["id"] = _generate_id(item["url"])
                    item["source"] = "rss"
                    item["collected_at"] = _now_iso()
                    results.append(item)
                logger.info("Collected %d items from %s", len(items), feed_url)
        except httpx.HTTPError as e:
            logger.error("Failed to fetch RSS feed %s: %s", feed_url, e)

    return results


def _parse_rss_items(xml_content: str, feed_url: str) -> list[dict]:
    items = []
    for match in re.finditer(r"<item>(.*?)</item>", xml_content, re.DOTALL | re.IGNORECASE):
        item_xml = match.group(1)
        title = _extract_rss_field(item_xml, "title")
        link = _extract_rss_field(item_xml, "link")
        desc = _extract_rss_field(item_xml, "description")
        pub_date = _extract_rss_field(item_xml, "pubDate")
        items.append({
            "title": html.unescape(title).strip() if title else "",
            "url": html.unescape(link).strip() if link else "",
            "description": html.unescape(desc).strip() if desc else "",
            "published_at": pub_date.strip() if pub_date else "",
            "feed_url": feed_url,
            "popularity": 0,
            "language": None,
            "topics": [],
        })
    return items


def _extract_rss_field(xml: str, field: str) -> Optional[str]:
    match = re.search(rf"<{field}[^>]*>(.*?)</{field}>", xml, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def save_raw_items(items: list[dict], dry_run: bool = False) -> None:
    if dry_run:
        for item in items:
            logger.info("[DRY-RUN] Would save raw item: %s", item["url"])
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for item in items:
        fname = f"raw_{item['source']}_{timestamp}_{item['id']}.json"
        fpath = RAW_DIR / fname
        try:
            fpath.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug("Saved raw item: %s", fname)
        except OSError as e:
            logger.error("Failed to save raw item %s: %s", fname, e)


# ---------------------------------------------------------------------------
# Step 2: Analyze
# ---------------------------------------------------------------------------

def analyze_items(raw_items: list[dict], dry_run: bool = False) -> list[dict]:
    if not raw_items:
        logger.warning("No raw items to analyze")
        return []

    logger.info("Analyzing %d items with LLM", len(raw_items))

    if dry_run:
        logger.info("[DRY-RUN] Would analyze items with LLM")
        return _make_dummy_articles(raw_items)

    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        logger.error("No LLM API key found (set LLM_API_KEY or DEEPSEEK_API_KEY)")
        return _make_dummy_articles(raw_items)

    provider = create_provider()
    try:
        articles = []
        for idx, raw in enumerate(raw_items):
            logger.info("Analyzing [%d/%d]: %s", idx + 1, len(raw_items), raw["title"])
            try:
                article = _analyze_single(raw, provider)
                articles.append(article)
            except Exception as e:
                logger.error("Analysis failed for %s: %s", raw["title"], e)
                articles.append(_make_dummy_article(raw))
        return articles
    finally:
        provider.close()


def _analyze_single(raw: dict, provider) -> dict:
    prompt = ANALYSIS_PROMPT.format(
        title=raw["title"],
        description=(raw.get("description") or "")[:1000],
    )
    response = chat_with_retry(
        provider,
        [{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1024,
    )
    analysis = _parse_llm_json(response.content)

    return {
        "title": raw["title"],
        "url": raw["url"],
        "source": raw["source"],
        "popularity": raw.get("popularity", 0),
        "summary": analysis.get("summary", raw.get("description", "")),
        "highlights": analysis.get("highlights", []),
        "score": analysis.get("score", 5),
        "score_reason": analysis.get("score_reason", ""),
        "tags": analysis.get("tags", []),
        "language": raw.get("language"),
        "topics": raw.get("topics", []),
        "published_at": raw.get("published_at", ""),
        "collected_at": raw.get("collected_at", _now_iso()),
        "stored_at": _now_iso(),
    }


def _parse_llm_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON, trying fallback")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        logger.error("Could not extract JSON from LLM response: %.200s", text)
        return {}


def _make_dummy_articles(raw_items: list[dict]) -> list[dict]:
    return [_make_dummy_article(item) for item in raw_items]


def _make_dummy_article(raw: dict) -> dict:
    return {
        "title": raw["title"],
        "url": raw["url"],
        "source": raw["source"],
        "popularity": raw.get("popularity", 0),
        "summary": raw.get("description", ""),
        "highlights": [],
        "score": 5,
        "score_reason": "No LLM analysis available",
        "tags": raw.get("topics", [])[:5],
        "language": raw.get("language"),
        "topics": raw.get("topics", []),
        "published_at": raw.get("published_at", ""),
        "collected_at": raw.get("collected_at", _now_iso()),
        "stored_at": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Step 3: Organize
# ---------------------------------------------------------------------------

def organize_articles(articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    logger.info("Organizing %d articles (dedup + validation)", len(articles))

    seen_urls: set[str] = set()
    deduped = []
    for article in articles:
        url = article.get("url", "")
        if not url or url in seen_urls:
            logger.debug("Skipping duplicate: %s", article.get("title"))
            continue
        seen_urls.add(url)
        deduped.append(article)

    validated = []
    for article in deduped:
        if _validate_article(article):
            validated.append(_standardize(article))
        else:
            logger.warning("Skipping invalid article: %s", article.get("title"))

    logger.info("After organization: %d articles (removed %d duplicates, %d invalid)",
                len(validated), len(articles) - len(deduped), len(deduped) - len(validated))
    return validated


def _validate_article(article: dict) -> bool:
    required = ["title", "url", "source"]
    for field in required:
        if not article.get(field):
            logger.debug("Missing required field '%s' in article", field)
            return False
    score = article.get("score")
    if score is not None and not isinstance(score, (int, float)):
        logger.debug("Invalid score type: %s", type(score).__name__)
        return False
    return True


def _standardize(article: dict) -> dict:
    score = article.get("score", 5)
    if score is not None:
        article["score"] = max(1, min(10, int(round(score))))

    if isinstance(article.get("tags"), list):
        article["tags"] = [str(t).strip() for t in article["tags"] if t]
        seen = set()
        unique_tags = []
        for t in article["tags"]:
            if t.lower() not in seen:
                seen.add(t.lower())
                unique_tags.append(t)
        article["tags"] = unique_tags

    article["popularity"] = article.get("popularity") or 0
    return article


# ---------------------------------------------------------------------------
# Step 4: Save
# ---------------------------------------------------------------------------

def save_articles(articles: list[dict], dry_run: bool = False) -> list[Path]:
    if not articles:
        logger.warning("No articles to save")
        return []

    logger.info("Saving %d articles to %s", len(articles), ARTICLES_DIR)
    saved = []

    for article in articles:
        date_str = _today_str()
        source = article.get("source", "unknown")
        fname = f"{date_str}-{source}-{article.get('title', 'untitled')[:40]}"
        fname = re.sub(r"[^\w\-]", "_", fname)
        fname = fname.strip("_").lower()
        fname += ".json"
        fpath = ARTICLES_DIR / fname

        if dry_run:
            logger.info("[DRY-RUN] Would save: %s", fname)
            saved.append(fpath)
            continue

        try:
            fpath.write_text(json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info("Saved article: %s", fname)
            saved.append(fpath)
        except OSError as e:
            logger.error("Failed to save article %s: %s", fname, e)

    return saved


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------

COLLECTORS = {
    "github": collect_from_github,
    "rss": collect_from_rss,
}


def run_pipeline(sources: list[str], limit: int, dry_run: bool, verbose: bool) -> int:
    setup_logging(verbose)
    ensure_dirs()

    logger.info("Starting pipeline: sources=%s, limit=%d, dry_run=%s",
                sources, limit, dry_run)

    all_raw = []
    for source in sources:
        collector = COLLECTORS.get(source)
        if not collector:
            logger.error("Unknown source: %s", source)
            continue
        items = collector(limit, dry_run=dry_run)
        all_raw.extend(items)

    if not all_raw:
        logger.warning("No data collected from any source")
        return 1

    logger.info("Step 1 complete: %d raw items collected", len(all_raw))
    save_raw_items(all_raw, dry_run=dry_run)

    logger.info("Step 2: Analyzing items with LLM...")
    articles = analyze_items(all_raw, dry_run=dry_run)

    logger.info("Step 3: Organizing articles...")
    articles = organize_articles(articles)

    logger.info("Step 4: Saving articles...")
    saved = save_articles(articles, dry_run=dry_run)
    effective = 0 if dry_run else len(saved)

    logger.info("Pipeline complete: %d articles saved", effective)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI Knowledge Base Pipeline - Collect, Analyze, Organize, Save",
    )
    parser.add_argument(
        "--sources",
        default="github,rss",
        help="Comma-separated list of sources (github, rss). Default: github,rss",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Max items to collect per source. Default: 20",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log all actions without writing files or making API calls",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not sources:
        logger.error("No sources specified")
        return
    exit_code = run_pipeline(sources, args.limit, args.dry_run, args.verbose)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
