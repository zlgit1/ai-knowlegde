"""Supervisor 监督模式 - Worker 执行 + Supervisor 审核循环."""

import json
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.model_client import get_provider, chat_with_retry

_WORKER_SYSTEM = """\
You are a precise analyst that outputs only valid JSON.
Analyze the task and produce a JSON report with these fields:
- summary: a brief summary of the analysis
- analysis: detailed analysis
- conclusion: the conclusion
- key_findings: a list of key findings (strings)
"""

_WORKER_PROMPT = "Analyze the following task:\n\n{task}"

_SUPERVISOR_SYSTEM = """\
You are a strict quality supervisor. Review the analysis report and score it on:
- accuracy (1-10): correctness of the analysis
- depth (1-10): thoroughness and depth of the analysis
- format (1-10): structural quality and clarity

Output ONLY valid JSON with these fields:
- passed: boolean (whether the report passes quality standards, at least 7 overall)
- score: integer (overall score from 1-10)
- feedback: string (constructive feedback if not passed, empty string if passed)
"""

_SUPERVISOR_PROMPT = """Task:
{task}

Report:
{report}

Review the above report and output your JSON assessment."""

_REDO_SYSTEM = """\
You are an analyst revising your report based on feedback.
Output only valid JSON with the same report structure.
"""

_REDO_PROMPT = """Original task:
{task}

Supervisor feedback:
{feedback}

Please revise and produce an improved JSON report."""


def _extract_json(text: str) -> str:
    if "```" in text:
        parts = text.split("```")
        for i, part in enumerate(parts):
            if i % 2 == 1:
                content = part.strip()
                if content.startswith("json"):
                    content = content[4:].strip()
                return content
    return text.strip()


def _chat(prompt: str, system: str = "") -> tuple[str, dict]:
    provider = get_provider()
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = chat_with_retry(provider, messages, temperature=0.3)
        return response.content, {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    finally:
        provider.close()


def _worker(task: str) -> dict:
    text, _ = _chat(_WORKER_PROMPT.format(task=task), system=_WORKER_SYSTEM)
    return json.loads(_extract_json(text))


def _supervisor(task: str, report: dict) -> dict:
    text, _ = _chat(
        _SUPERVISOR_PROMPT.format(task=task, report=json.dumps(report, ensure_ascii=False)),
        system=_SUPERVISOR_SYSTEM,
    )
    return json.loads(_extract_json(text))


def supervisor(task: str, max_retries: int = 3) -> dict:
    report = _worker(task)

    for attempt in range(max_retries):
        review = _supervisor(task, report)
        score = review.get("score", 0)
        passed = review.get("passed", False)
        feedback = review.get("feedback", "")

        if passed and score >= 7:
            return {
                "output": report,
                "attempts": attempt + 1,
                "final_score": score,
            }

        if attempt < max_retries - 1:
            text, _ = _chat(
                _REDO_PROMPT.format(task=task, feedback=feedback),
                system=_REDO_SYSTEM,
            )
            report = json.loads(_extract_json(text))
        else:
            return {
                "output": report,
                "attempts": attempt + 1,
                "final_score": score,
                "warning": f"Exceeded max retries ({max_retries}), forcing return with score {score}",
            }

    return {
        "output": report,
        "attempts": max_retries,
        "final_score": 0,
        "warning": "Unexpected exit from supervisor loop",
    }


if __name__ == "__main__":
    test_tasks = [
        "请分析 LangGraph 框架的优缺点和适用场景",
        "请分析最新的 ChatGPT 模型在处理多轮对话时的表现和改进点",
    ]
    for task in test_tasks:
        print(f"\n{'='*70}")
        print(f"Task: {task}")
        result = supervisor(task)
        print(f"Attempts: {result['attempts']}")
        print(f"Final Score: {result['final_score']}")
        if "warning" in result:
            print(f"Warning: {result['warning']}")
        output = result["output"]
        print(f"Summary: {output.get('summary', 'N/A')[:120]}...")
        print(f"Conclusion: {output.get('conclusion', 'N/A')[:120]}...")
