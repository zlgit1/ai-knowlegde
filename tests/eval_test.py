"""AI 知识库评估测试

测试级别：
  1. test_eval_cases_structure     — 本地验证 EVAL_CASES 结构（不调 LLM）
  2. test_analyze_positive         — 正面案例分析验证（参数化：2 个正面用例）
  3. test_analyze_negative         — 负面案例低分验证
  4. test_boundary_does_not_crash  — 边界输入不崩溃
  5. test_llm_as_judge (slow)      — LLM 对分析结果质量打分
"""

import json
import re

import pytest

from pipeline.model_client import chat

ANALYSIS_PROMPT = """You are an AI knowledge analyst working in Chinese. Analyze the following article and return ONLY valid JSON (no markdown, no code fences):

{{
  "summary": "2-3 sentence Chinese summary",
  "highlights": ["key point 1", "key point 2", "key point 3"],
  "score": <integer 1-10>,
  "score_reason": "1-2 sentence explanation of the score in Chinese",
  "tags": ["tag1", "tag2", "tag3"]
}}

Article description: {description}"""

JUDGE_PROMPT = """You are an evaluation judge. Rate the quality of the following AI knowledge analysis result on a scale of 1-10.

Criteria:
- Summary: clear, informative, captures key points
- Tags: relevant to the article content
- Score: appropriate based on the content quality
- Highlights: useful and specific

Return ONLY a single integer between 1 and 10. No other text.

Analysis result:
{analysis}"""

EVAL_CASES = [
    {
        "name": "positive_tech_project",
        "description": "技术项目分析",
        "input": (
            "GPT-4 is a large multimodal model developed by OpenAI. "
            "It accepts image and text inputs and produces text outputs. "
            "GPT-4 exhibits human-level performance on various professional and academic benchmarks, "
            "including passing a simulated bar exam with a score around the top 10% of test takers. "
            "It has been deployed in ChatGPT Plus and is available via API. "
            "The model shows significant improvements over GPT-3.5 in reasoning, factuality, "
            "and safety alignment."
        ),
        "expected": lambda r: (
            isinstance(r.get("summary"), str) and len(r["summary"]) >= 10
            and isinstance(r.get("tags"), list) and len(r["tags"]) >= 1
            and isinstance(r.get("highlights"), list) and len(r["highlights"]) >= 1
            and isinstance(r.get("score"), (int, float)) and 1 <= r["score"] <= 10
        ),
    },
    {
        "name": "negative_irrelevant",
        "description": "无关内容",
        "input": (
            "Hhsjjska lalala xyzabc this is completely nonsensical content "
            "with no meaningful structure or information whatsoever. "
            "Blah blah blah random words that do not form any coherent article "
            "or convey any useful knowledge about anything. "
            "Just pure noise and gibberish filler text with no value."
        ),
        "expected": lambda r: (
            isinstance(r.get("score"), (int, float)) and r["score"] <= 4
        ),
    },
    {
        "name": "boundary_short_input",
        "description": "极短输入",
        "input": "AI",
        "expected": lambda r: isinstance(r, dict),
    },
    {
        "name": "positive_english_tech",
        "description": "英文技术内容",
        "input": (
            "We introduce a new neural network architecture called Mixture of Transformers "
            "that combines sparse mixture-of-experts with standard transformer layers. "
            "The model achieves state-of-the-art results on language modeling benchmarks "
            "while using 40% fewer FLOPs per token compared to dense models of equivalent size. "
            "Key innovations include a novel routing mechanism that balances expert utilization "
            "and a hierarchical attention scheme for long-context processing."
        ),
        "expected": lambda r: (
            isinstance(r.get("summary"), str) and len(r["summary"]) >= 10
            and isinstance(r.get("tags"), list) and len(r["tags"]) >= 1
            and isinstance(r.get("highlights"), list) and len(r["highlights"]) >= 1
            and isinstance(r.get("score"), (int, float)) and 1 <= r["score"] <= 10
        ),
    },
]


def _parse_llm_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


def _analyze(description: str) -> dict:
    prompt = ANALYSIS_PROMPT.format(description=description[:1000])
    resp = chat(prompt)
    return _parse_llm_json(resp["content"])


# ---------------------------------------------------------------------------
# 1. 本地结构验证（不调用 LLM）
# ---------------------------------------------------------------------------

def test_eval_cases_structure(capsys):
    print("=== 本地验证（不消耗 token）===")
    for case in EVAL_CASES:
        assert "name" in case, "每个 case 必须有 name"
        assert "input" in case, "每个 case 必须有 input"
        assert callable(case.get("expected")), "每个 case 的 expected 必须是可调用函数"
        desc = case.get("description", case["name"])
        print(f"  - {desc}")
    print(f"[OK] EVAL_CASES 结构验证通过，共 {len(EVAL_CASES)} 个用例")


# ---------------------------------------------------------------------------
# 2. 正面案例分析验证
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", [
    c for c in EVAL_CASES if c["name"] in ("positive_tech_project", "positive_english_tech")
], ids=lambda c: c["name"])
def test_analyze_positive(case):
    result = _analyze(case["input"])
    assert case["expected"](result), (
        f"[{case['name']}] 正面案例验证失败: {json.dumps(result, ensure_ascii=False)}"
    )


# ---------------------------------------------------------------------------
# 3. 负面案例低分验证
# ---------------------------------------------------------------------------

def test_analyze_negative():
    case = next(c for c in EVAL_CASES if c["name"] == "negative_irrelevant")
    result = _analyze(case["input"])
    assert case["expected"](result), (
        f"负面案例应得低分(<=4)，实际: {result.get('score')}"
    )


# ---------------------------------------------------------------------------
# 4. 边界输入不崩溃
# ---------------------------------------------------------------------------

def test_boundary_does_not_crash():
    case = next(c for c in EVAL_CASES if c["name"] == "boundary_short_input")
    result = _analyze(case["input"])
    assert case["expected"](result), f"边界案例返回非法数据: {result}"


# ---------------------------------------------------------------------------
# 5. LLM-as-Judge（慢速，可跳过）
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_llm_as_judge():
    case = next(c for c in EVAL_CASES if c["name"] == "positive_tech_project")
    analysis = _analyze(case["input"])
    analysis_str = json.dumps(analysis, ensure_ascii=False, indent=2)
    judge_prompt = JUDGE_PROMPT.format(analysis=analysis_str)
    resp = chat(judge_prompt)
    score = int(resp["content"].strip())
    assert 1 <= score <= 10, f"打分超出范围: {score}"
    assert score >= 5, f"LLM 评分过低: {score}/10"
