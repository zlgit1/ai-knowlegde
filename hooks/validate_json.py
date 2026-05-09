#!/usr/bin/env python3
"""Validate knowledge entry JSON files."""

import json
import re
import sys
from pathlib import Path


REQUIRED_FIELDS = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]+\d{8}\-\d{3}$")
URL_PATTERN = re.compile(r"^https?://")


def validate_id(id_value: str) -> str | None:
    if not isinstance(id_value, str):
        return "id must be a string"
    if not re.match(r"^[a-z][a-z0-9-]*$", id_value.split("-")[0]):
        return f"invalid id format '{id_value}', expected {{source}}-{{YYYYMMDD}}-{{NNN}}"
    parts = id_value.rsplit("-", 2)
    if len(parts) != 3:
        return f"invalid id format '{id_value}', expected {{source}}-{{YYYYMMDD}}-{{NNN}}"
    source, date_str, seq = parts
    if not source:
        return f"invalid id format '{id_value}': missing source"
    if not (len(date_str) == 8 and date_str.isdigit()):
        return f"invalid id format '{id_value}': date '{date_str}' must be YYYYMMDD (8 digits)"
    if not (len(seq) == 3 and seq.isdigit()):
        return f"invalid id format '{id_value}': sequence '{seq}' must be 3 digits"
    return None


def validate_file(filepath: Path) -> list[str]:
    errors: list[str] = []

    try:
        raw = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return [f"cannot read file: {e}"]

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [f"invalid JSON: {e}"]

    if not isinstance(data, dict):
        return ["top-level value must be a JSON object"]

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"missing required field: '{field}'")
        elif not isinstance(data[field], expected_type):
            errors.append(
                f"field '{field}' must be {expected_type.__name__}, "
                f"got {type(data[field]).__name__}"
            )

    if "id" in data and isinstance(data["id"], str):
        err = validate_id(data["id"])
        if err:
            errors.append(err)

    if "status" in data and isinstance(data["status"], str):
        if data["status"] not in VALID_STATUSES:
            errors.append(
                f"invalid status '{data['status']}', "
                f"must be one of: {', '.join(sorted(VALID_STATUSES))}"
            )

    if "source_url" in data and isinstance(data["source_url"], str):
        if not URL_PATTERN.match(data["source_url"]):
            errors.append(
                f"invalid source_url '{data['source_url']}', must start with http:// or https://"
            )

    if "summary" in data and isinstance(data["summary"], str):
        if len(data["summary"]) < 20:
            errors.append(
                f"summary too short ({len(data['summary'])} chars), minimum 20"
            )

    if "tags" in data and isinstance(data["tags"], list):
        if len(data["tags"]) < 1:
            errors.append("tags must have at least 1 item")

    if "score" in data:
        score = data["score"]
        if not isinstance(score, (int, float)):
            errors.append(
                f"score must be a number, got {type(score).__name__}"
            )
        elif not (1 <= score <= 10):
            errors.append(f"score must be between 1 and 10, got {score}")

    if "audience" in data:
        audience = data["audience"]
        if not isinstance(audience, str):
            errors.append(
                f"audience must be a string, got {type(audience).__name__}"
            )
        elif audience not in VALID_AUDIENCES:
            errors.append(
                f"invalid audience '{audience}', "
                f"must be one of: {', '.join(sorted(VALID_AUDIENCES))}"
            )

    return errors


def main() -> int:
    files = sys.argv[1:]
    if not files:
        print(f"Usage: python {sys.argv[0]} <json_file> [json_file2 ...]")
        return 1

    all_errors: dict[str, list[str]] = {}
    total_files = 0

    for pattern in files:
        matched = list(Path().glob(pattern)) if ("*" in pattern or "?" in pattern) else [Path(pattern)]
        if not matched:
            print(f"warning: no files matched '{pattern}'", file=sys.stderr)
            continue
        for filepath in matched:
            if not filepath.is_file():
                print(f"warning: not a file '{filepath}'", file=sys.stderr)
                continue
            total_files += 1
            errors = validate_file(filepath)
            if errors:
                all_errors[str(filepath)] = errors

    if not all_errors:
        if total_files > 0:
            print(f"All {total_files} file(s) passed validation.")
        return 0

    total_errors = 0
    for filepath, errors in sorted(all_errors.items()):
        print(f"\n{filepath}:")
        for err in errors:
            total_errors += 1
            print(f"  - {err}")

    print(f"\n{'=' * 40}")
    print(f"Summary: {total_errors} error(s) in {len(all_errors)} of {total_files} file(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
