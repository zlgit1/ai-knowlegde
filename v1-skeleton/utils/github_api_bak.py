import requests


def get_repo_info(repo_full_name: str, token: str | None = None) -> dict:
    url = f"https://api.github.com/repos/{repo_full_name}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    return {
        "stars": data["stargazers_count"],
        "forks": data["forks_count"],
        "description": data["description"],
    }
