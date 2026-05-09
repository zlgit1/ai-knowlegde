#!/usr/bin/env python3
"""4-dimension quality scoring for knowledge entry JSON files."""

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


TECH_KEYWORDS = {
    "AI", "Agent", "LLM", "大模型", "深度学习", "机器学习",
    "Transformer", "Attention", "MoE", "量化", "蒸馏",
    "RAG", "向量", "Embedding", "微调", "Fine-tune",
    "推理引擎", "GPU", "CUDA", "Metal", "Blackwell",
    "神经网络", "多模态", "Multimodal",
    "NLP", "CV", "Token", "Context",
    "分布式", "架构", "Pipeline",
    "API", "SDK", "协议", "Protocol", "编排",
    "框架", "Framework", "平台", "生态",
    "对齐", "Alignment", "安全", "隐私",
    "CoT", "Prompt", "工具调用", "Tool Use",
    "开源", "MCP", "VFS", "KV cache",
}


BUZZWORD_CN = [
    "赋能", "抓手", "闭环", "打通", "全链路",
    "底层逻辑", "颗粒度", "对齐", "拉通", "沉淀",
    "强大的", "革命性的",
]

BUZZWORD_EN = [
    "groundbreaking", "revolutionary", "game-changing", "cutting-edge",
    "state-of-the-art", "best-in-class", "next-generation",
    "world-class", "industry-leading", "paradigm-shift",
    "ultra-fast", "hyper-scale",
]

ID_PATTERN = re.compile(r"^https?://")


@dataclass
class DimensionScore:
    name: str
    score: float
    max_score: int
    detail: str = ""


@dataclass
class QualityReport:
    filepath: str
    dimensions: list[DimensionScore] = field(default_factory=list)

    @property
    def total_score(self) -> float:
        return sum(d.score for d in self.dimensions)

    @property
    def grade(self) -> str:
        if self.total_score >= 68:
            return "A"
        if self.total_score >= 51:
            return "B"
        return "C"

    def format_output(self) -> str:
        lines = [f"\n{self.filepath}:"]
        for d in self.dimensions:
            bar = "█" * int(d.score / d.max_score * 10) if d.max_score > 0 else ""
            bar += "░" * (10 - len(bar))
            lines.append(
                f"  {bar} {d.name}: {d.score:5.1f}/{d.max_score:<2}  {d.detail}"
            )
        total_str = f"{self.total_score:.1f}/85"
        lines.append(f"  {'─' * 40}")
        lines.append(f"  TOTAL: {total_str:>8}  [{self.grade}]")
        return "\n".join(lines)


def _get(data: dict, *keys, default=None):
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return default
    return data


def score_summary_quality(data: dict) -> DimensionScore:
    summary = _get(data, "summary", default="")
    if not isinstance(summary, str) or not summary:
        return DimensionScore("摘要质量", 0, 25, "缺少摘要")

    length = len(summary)

    if length >= 50:
        base = 25.0
    elif length >= 20:
        base = 10.0 + (length - 20) * 15.0 / 30.0
    else:
        base = 0.0

    found = [kw for kw in TECH_KEYWORDS if kw.lower() in summary.lower()]
    bonus = min(5.0, len(found) * 1.0)
    score = min(25.0, base + bonus)

    parts = [f"{length}字"]
    if found:
        parts.append(f"关键词+{bonus:.0f}")
    detail = ", ".join(parts)

    return DimensionScore("摘要质量", score, 25, f"({detail})")


def score_technical_depth(data: dict) -> DimensionScore:
    raw = _get(data, "score")
    if raw is None:
        raw = _get(data, "analysis", "score")
    if raw is None:
        return DimensionScore("技术深度", 0, 25, "无score字段")

    if not isinstance(raw, (int, float)):
        return DimensionScore("技术深度", 5, 25, "score类型异常，给基础分")

    val = max(1.0, min(10.0, float(raw)))
    score = val * 2.5
    return DimensionScore("技术深度", score, 25, f"(score={val:.0f}/10)")


def score_format_compliance(data: dict) -> DimensionScore:
    pts = 4
    total = 0
    parts = []

    has_id = bool(_get(data, "id"))
    total += pts if has_id else 0
    parts.append(f"{'id✓' if has_id else 'id✗'}")

    has_title = bool(_get(data, "title"))
    total += pts if has_title else 0
    parts.append(f"{'title✓' if has_title else 'title✗'}")

    url = _get(data, "source_url") or _get(data, "url")
    has_url = bool(isinstance(url, str) and ID_PATTERN.match(url))
    total += pts if has_url else 0
    parts.append(f"{'url✓' if has_url else 'url✗'}")

    status = _get(data, "status")
    has_status = bool(isinstance(status, str) and status)
    total += pts if has_status else 0
    parts.append(f"{'status✓' if has_status else 'status✗'}")

    ts = _get(data, "collected_at") or _get(data, "stored_at")
    has_ts = bool(isinstance(ts, str) and ts)
    total += pts if has_ts else 0
    parts.append(f"{'ts✓' if has_ts else 'ts✗'}")

    return DimensionScore("格式规范", float(total), 20, ", ".join(parts))



def score_buzzword_check(data: dict) -> DimensionScore:
    texts = []
    for key in ("title", "summary"):
        val = _get(data, key)
        if isinstance(val, str):
            texts.append(val)
    combined = " ".join(texts)

    found: list[str] = []
    for bw in BUZZWORD_CN:
        if bw in combined:
            found.append(bw)
    lower = combined.lower()
    for bw in BUZZWORD_EN:
        if bw.lower() in lower:
            found.append(bw)

    if not found:
        return DimensionScore("空洞词检测", 15, 15, "未检出")

    penalty = min(15.0, len(found) * 3.0)
    score = max(0.0, 15.0 - penalty)
    shown = ", ".join(found[:5])
    if len(found) > 5:
        shown += f" ...(+{len(found) - 5})"
    return DimensionScore("空洞词检测", score, 15, f"检出{len(found)}个: {shown}")


def score_file(filepath: Path) -> QualityReport:
    try:
        raw = filepath.read_text(encoding="utf-8")
    except Exception as e:
        report = QualityReport(filepath=str(filepath))
        report.dimensions.append(
            DimensionScore("读取错误", 0, 100, str(e))
        )
        return report

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        report = QualityReport(filepath=str(filepath))
        report.dimensions.append(
            DimensionScore("JSON错误", 0, 100, str(e))
        )
        return report

    if not isinstance(data, dict):
        report = QualityReport(filepath=str(filepath))
        report.dimensions.append(
            DimensionScore("格式错误", 0, 100, "非JSON对象")
        )
        return report

    report = QualityReport(filepath=str(filepath))
    report.dimensions.append(score_summary_quality(data))
    report.dimensions.append(score_technical_depth(data))
    report.dimensions.append(score_format_compliance(data))
    report.dimensions.append(score_buzzword_check(data))
    return report


def print_progress(current: int, total: int, width: int = 40):
    pct = current / total if total > 0 else 1.0
    filled = int(width * pct)
    bar = "█" * filled + "░" * (width - filled)
    print(f"\r  [{bar}] {pct * 100:5.1f}%  ({current}/{total})", end="", file=sys.stderr)
    if current == total:
        print(file=sys.stderr)


def main() -> int:
    files = sys.argv[1:]
    if not files:
        print(f"Usage: python {sys.argv[0]} <json_file> [json_file2 ...]")
        return 1

    targets: list[Path] = []
    for pattern in files:
        matched = list(Path().glob(pattern)) if ("*" in pattern or "?" in pattern) else [Path(pattern)]
        for p in matched:
            if p.is_file():
                targets.append(p)
            else:
                print(f"warning: not a file '{p}'", file=sys.stderr)

    if not targets:
        print("error: no valid files to process", file=sys.stderr)
        return 1

    reports: list[QualityReport] = []
    total = len(targets)

    print(f"Scoring {total} file(s)...", file=sys.stderr)

    for i, p in enumerate(targets, 1):
        reports.append(score_file(p))
        print_progress(i, total)

    has_c = False
    for r in reports:
        print(r.format_output())
        if r.grade == "C":
            has_c = True

    grades = [r.grade for r in reports]
    summary = (
        f"\n{'=' * 48}\n"
        f"Summary: {total} file(s)  "
        f"A:{grades.count('A')}  B:{grades.count('B')}  C:{grades.count('C')}"
    )
    print(summary)

    return 1 if has_c else 0


if __name__ == "__main__":
    sys.exit(main())
