import logging

import requests

logger = logging.getLogger(__name__)


def get_repo_info(repo_full_name: str, token: str | None = None) -> dict:
    """从 GitHub API 获取指定仓库的基本信息。

    Args:
        repo_full_name: 仓库全名，格式 "owner/repo"，如 "tensorflow/tensorflow"。
        token: GitHub Personal Access Token，可选。提供后可提高 API 速率限制。

    Returns:
        包含 stars、forks、description 三个字段的字典。

    Raises:
        requests.HTTPError: API 返回非 2xx 状态码时抛出。
        requests.ConnectionError: 网络连接失败时抛出。
        requests.Timeout: 请求超时时抛出。
        KeyError: API 响应缺少预期字段时抛出。
    """
    url = f"https://api.github.com/repos/{repo_full_name}"
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    logger.info("Fetching repo info: %s", repo_full_name)
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    return {
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "description": data["description"],
    }
