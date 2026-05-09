# AI 知识库系统

基于多 Agent 协作的 AI 技术知识库——自动采集、智能分析、定时推送。

[![Daily Collect](https://github.com/anomalyco/ai-knowledge/actions/workflows/daily-collect.yml/badge.svg)](https://github.com/anomalyco/ai-knowledge/actions/workflows/daily-collect.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      Agent 层  (LangGraph)                    │
│                                                             │
│  Planner → Collector → Analyzer → Reviewer ─→ Revise → END│
│                 ↑                        ↓                  │
│            Security · sanitize_input    Organizer           │
│            CostGuard · 预算熔断         · filter_output     │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    Pipeline 层 (同步 CLI)                    │
│                                                             │
│  pipeline.py  — GitHub Search / RSS 采集 → LLM 分析 → 归档  │
│  hooks/       — 质量校验 validate_json + check_quality       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                    工程层 (Infrastructure)                    │
│                                                             │
│  tests/       — pytest 全套 · CostGuard · Security · Eval   │
│  .github/     — GitHub Actions 定时采集 (每天 UTC 8:00)     │
│  opencode.json— OpenCode MCP Server 集成                    │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                   分发层 (Delivery)                          │
│                                                             │
│  MCP Server   — 通过 OpenCode 插件对外暴露知识库查询        │
│  RSS Feeds    — Hacker News / arXiv / 公司博客 / 中文社区   │
│  GitHub API   — 搜索 AI 高星仓库                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 快速开始

### 1. 克隆

```bash
git clone https://github.com/anomalyco/ai-knowledge.git
cd ai-knowledge
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少填入 LLM API Key：
#   DEEPSEEK_API_KEY=sk-xxx
#   GITHUB_TOKEN=ghp_xxx            # 可选，提高 GitHub API 限额
#   BUDGET_YUAN=1.0                 # 每日预算上限，默认 ¥1.0
```

### 3. 启动（二选一）

```bash
# 方式 A：Docker（推荐）
docker compose up -d

# 方式 B：本地运行
pip install -r requirements.txt
python pipeline/pipeline.py --sources github,rss --limit 10
```

---

## 目录结构

| 目录/文件 | 说明 | 版本 |
|---|---|---|
| `workflows/` | LangGraph 多 Agent 编排（Planner → Collector → Analyzer → Reviewer → Reviser → Organizer） | v3 |
| `pipeline/` | 同步 Pipeline：采集 → LLM 分析 → 归档 | v1 |
| `tests/` | 测试套件：eval_test(端到端评估)、cost_guard(预算控制)、security(安全防护) | v3 |
| `knowledge/` | 数据目录：articles(归档条目)、raw(原始数据)、pending_review(待审) | v1 |
| `hooks/` | 质量校验钩子：validate_json + check_quality | v1 |
| `mcp_knowledge_server.py` | OpenCode MCP 服务器，提供知识库查询接口 | v2 |
| `.github/workflows/` | GitHub Actions 定时采集（每天 UTC 8:00） | v1 |
| `.opencode/skills/` | OpenCode 技能：GitHub Trending 采集 + 技术总结 | v2 |
| `opencode.json` | OpenCode 插件配置 | v2 |
| `v1-skeleton/` | v1 原型设计文档 | v1 |

---

## 技术栈

| 类别 | 选型 | 用途 |
|---|---|---|
| **AI 编排** | [OpenCode](https://opencode.ai) + [LangGraph](https://langchain-ai.github.io/langgraph/) | Agent 工作流定义与执行 |
| **大模型** | DeepSeek / Qwen / OpenAI (可切换) | 内容分析、摘要生成、质量审核 |
| **部署** | Docker + GitHub Actions (CI/CD) | 容器化运行与定时采集 |
| **分发** | MCP Server (Model Context Protocol) | 通过 OpenCode 插件对外暴露知识库 |
| **安全** | CostGuard (预算熔断) + Security (注入/PII 防护) | 生产级安全防护 |
| **测试** | pytest | 端到端评估 + 单元测试 |

---

## 版本历史

| 阶段 | 核心能力 |
|---|---|
| **v1 采集管线** | GitHub Search + RSS 采集 → LLM 分析 → 质量校验 → JSON 归档 |
| **v2 MCP 集成** | OpenCode MCP Server 接入，GitHub Trending + Hacker News 技能开发，技术文章深度总结 |
| **v3 LangGraph 多 Agent** | Planner/Collector/Analyzer/Reviewer/Reviser/Organizer 多轮协作，CostGuard 预算熔断，Security 注入/PII 防护，端到端评估测试 |

---

## 月度成本估算

以每日 1 次采集、每次 10 条分析估算。

| 项目 | 用量/月 | 费用 (¥) |
|---|---|---|
| **DeepSeek API** (deepseek-chat) | ~30 万 tokens | ¥0.3 |
| **GitHub Actions** | ~30 分钟执行 | ¥0 (免费配额) |
| **服务器** (Docker 部署) | 1 台轻量云服务器 | ¥30 ~ ¥60 |
| **合计** | | **¥30 ~ ¥61/月** |

> 可通过 `BUDGET_YUAN` 环境变量设置每日预算上限，超限自动熔断。

---

## License

[MIT](LICENSE)
