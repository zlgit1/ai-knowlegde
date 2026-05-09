# AGENTS.md

## 项目概述

自动化 AI 知识库助手，通过多 Agent 流水线持续从 GitHub Trending / Hacker News 等源头采集 AI/LLM/Agent 领域技术动态，经 AI 分析处理后结构化为标准 JSON 知识条目，并支持 Telegram、飞书等多渠道分发的全自动系统。

## 技术栈

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| Agent 框架 | [OpenCode](https://opencode.ai) + 国产大模型（DeepSeek / Qwen / GLM） |
| 工作流编排 | LangGraph（有状态多步 Agent 协作） |
| 爬虫框架 | OpenClaw（规则化网页采集） |
| 数据存储 | JSON 文件（本地）/ SQLite → PostgreSQL（生产） |

## 编码规范

- **风格**：遵循 PEP 8，使用 `snake_case` 命名变量和函数
- **类型注解**：所有函数参数和返回值必须标注类型
- **文档字符串**：Google 风格 docstring
- **日志**：禁止使用裸 `print()`，统一使用 `logging` 模块
- **导入顺序**：标准库 → 第三方库 → 本地模块（每组间空一行）
- **行长度**：不超过 88 字符（兼容 Black 格式化）

### Docstring 示例

```python
def fetch_trending(language: str, since: str = "daily") -> list[dict]:
    """从 GitHub Trending 抓取指定语言的热门仓库。

    Args:
        language: 编程语言名称，如 "python"、"rust"。
        since: 时间范围，"daily"、"weekly" 或 "monthly"。

    Returns:
        标准化条目列表，每项包含 id、title、source_url 等字段。

    Raises:
        requests.RequestException: HTTP 请求失败时抛出。
    """
```

## 项目结构

```
.
├── .opencode/
│   ├── agents/              # Agent 定义（采集/分析/整理）
│   │   ├── collector.py     # 数据采集 Agent
│   │   ├── analyzer.py      # 内容分析 Agent
│   │   └── organizer.py     # 知识整理 Agent
│   └── skills/              # OpenCode 技能文件
│       ├── github_skill.md  # GitHub Trending 采集技能
│       └── hn_skill.md      # Hacker News 采集技能
├── knowledge/
│   ├── raw/                 # 采集原始数据（未处理）
│   ├── processed/           # AI 分析后的结构化知识条目
│   └── archive/             # 已归档的历史知识
├── utils/
│   ├── github_api.py        # GitHub API 工具函数
│   └── hn_api.py            # Hacker News API 工具函数
├── dispatchers/             # 多渠道分发
│   ├── telegram.py          # Telegram 推送
│   ├── feishu.py            # 飞书推送
│   └── base.py              # 分发器基类
├── AGENTS.md                # 本文件 — Agent 行为规范
├── VISION.md                # 项目愿景与架构
└── requirements.txt         # Python 依赖
```

## 知识条目 JSON 格式

```json
{
  "id": "gh-20260423-llama4",
  "title": "Meta 发布 Llama 4 系列模型",
  "source_url": "https://github.com/meta/llama4",
  "source_type": "github_trending",
  "summary": "Meta 发布了 Llama 4 系列，包含 8B 和 70B 两种规格，采用 MoE 架构...",
  "tags": ["llm", "open-source", "meta", "moa"],
  "category": "model_release",
  "importance": "high",
  "status": "pending",
  "language": "zh",
  "created_at": "2026-04-23T12:00:00+08:00",
  "updated_at": "2026-04-23T12:05:00+08:00",
  "related_ids": []
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 全局唯一 ID，格式 `{source}-{date}-{slug}` |
| `title` | string | 中文标题（AI 自动翻译） |
| `source_url` | string | 原文链接 |
| `source_type` | string | 数据来源类型 |
| `summary` | string | AI 生成的中文摘要 |
| `tags` | array[string] | 标签列表，全小写 |
| `category` | string | 分类：`model_release` / `tool_framework` / `paper` / `opinion` / `ecosystem` |
| `importance` | string | 重要性评级：`low` / `medium` / `high` / `critical` |
| `status` | string | 处理状态：`pending` / `analyzed` / `organized` / `published` / `archived` |
| `language` | string | 内容语言代码 |
| `created_at` | string | ISO 8601 创建时间 |
| `updated_at` | string | ISO 8601 更新时间 |
| `related_ids` | array[string] | 关联知识条目 ID |

## Agent 角色概览

| 角色 | Agent 名称 | 核心职责 | 输入 | 输出 | 关键约束 |
|------|-----------|----------|------|------|----------|
| **采集** | Collector | 定时抓取 GitHub Trending / Hacker News，去重去噪 | RSS / API / 网页 | `knowledge/raw/` 标准化 JSON | 遵守 robots.txt，请求间隔 ≥ 3s，不爬登录态内容 |
| **分析** | Analyzer | 调用 LLM 阅读原文，生成中文摘要，判断技术重要性 | 标准化条目 + 原文内容 | 含 `summary`、`importance`、`category`、`tags` 的完整条目 | 摘要需保留核心技术细节，不泛泛而谈 |
| **整理** | Organizer | 归类打标签，关联已有知识，更新知识图谱 | 分析后的条目 + 历史知识库 | 最终结构化条目写入 `knowledge/processed/` | 确保 `tags` 一致，维护 `related_ids` 关联关系 |

## 红线（绝对禁止的操作）

1. **禁止修改 VISION.md** — 愿景文档由人工维护，Agent 只读
2. **禁止覆盖 knowledge/processed/ 中 status 为 published 的条目** — 已发布数据不可篡改
3. **禁止直接调用 LLM 不经过 Analyzer Agent 写入知识库** — 所有知识必须经过采集 → 分析 → 整理完整流水线
4. **禁止采集需要登录或付费墙的内容** — 仅采集公开可访问的数据源
5. **禁止删除原始数据** — `knowledge/raw/` 中的文件只增不删
6. **禁止在代码或知识条目中暴露 API Key / Token** — 密钥必须通过环境变量传入
7. **禁止在未降级的情况下创建或修改 .opencode/skills/ 中的技能文件** — 技能文件是 Agent 行为核心，修改需人工审核
8. **禁止以高于每分钟 60 次的频率调用同一 API** — 遵循 API 调用频率限制，避免触发反爬
9. **禁止生成空字段或非法 JSON** — 写入 `knowledge/` 的所有 JSON 必须经过 schema 校验
