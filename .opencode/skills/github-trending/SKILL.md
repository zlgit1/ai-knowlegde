---
name: github-trending
description: 当需要采集 GitHub 热门开源项目时使用此技能
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
---

## 使用场景

- 用户要求关注 GitHub 热门开源项目动态
- 需要构建 AI/LLM/Agent 领域的技术风向标
- 定期采集 GitHub Trending 数据用于知识库积累

## 执行步骤

1. **搜索热门仓库**：调用 GitHub API `GET https://api.github.com/search/repositories`，按 stars 排序，查询最近一周内创建的项目，例如 `q=created:>YYYY-MM-DD&sort=stars&order=desc&per_page=100`。
2. **提取信息**：从 API 响应中提取每个仓库的 `name`、`html_url`、`stargazers_count`、`language`、`topics`、`description`。
3. **过滤**：仅纳入 AI/LLM/Agent 相关项目（通过 topics 和 description 关键词匹配），**排除** Awesome 列表类项目（如 topics 包含 `awesome-list` 或 name/description 匹配 `awesome`）。
4. **去重**：对同一项目（同名或同 URL）只保留一条记录。
5. **撰写中文摘要**：按 `项目名 + 做什么 + 为什么值得关注` 公式为每个项目撰写一句话摘要。
6. **排序取 Top 15**：按 stars 降序排列，取前 15 个项目。
7. **输出 JSON**：将结果写入 `knowledge/raw/github-trending-YYYY-MM-DD.json`。

## 注意事项

- 日期参数使用今天（采集当日）往前推 7 天。
- 确保 `knowledge/raw/` 目录存在，否则先创建。
- API 请求注意频率限制（未认证 10 次/分钟，建议使用 token）。
- 摘要语言为中文，简明扼要，每条不超过 100 字。

## 输出格式

```json
{
  "source": "github-trending",
  "skill": "github-trending",
  "collected_at": "2026-05-09T12:00:00+08:00",
  "items": [
    {
      "name": "owner/repo",
      "url": "https://github.com/owner/repo",
      "summary": "一句话中文摘要",
      "stars": 1234,
      "language": "Python",
      "topics": ["ai", "llm"]
    }
  ]
}
```
