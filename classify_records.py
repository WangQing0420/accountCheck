#!/usr/bin/env python3
"""Group similar account-check records by normalized descriptive fields."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from fetch_account_records import PLATFORM_OUTPUT_LABELS, platform_for_alias


DEFAULT_GROUP_FIELDS = [
    "memo",
    "bizDesc",
    "businessType",
    "bizType",
    "bizTypeDesc",
    "remark",
    "remarks",
    "feeName",
    "accountBillDesc",
    "typeDesc",
    "settlementMemo",
    "costItem",
    "detail",
    "transactionDescription",
    "operateType",
    "insuranceProduct",
]

FIELD_ALIASES = {
    "accountBillDesc": ["accountBillDesc", "account_bill_desc"],
    "bizDesc": ["bizDesc", "biz_desc"],
    "bizType": ["bizType", "biz_type"],
    "bizTypeDesc": ["bizTypeDesc", "biz_type_desc"],
    "businessType": ["businessType", "business_type"],
    "costItem": ["costItem", "cost_item"],
    "feeName": ["feeName", "fee_name"],
    "inAmount": ["inAmount", "in_amount"],
    "insuranceProduct": ["insuranceProduct", "insurance_product"],
    "operateType": ["operateType", "operate_type"],
    "outAmount": ["outAmount", "out_amount"],
    "settlementMemo": ["settlementMemo", "settlement_memo"],
    "transactionDescription": ["transactionDescription", "transaction_description"],
    "typeDesc": ["typeDesc", "type_desc"],
}


def load_rows(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return load_check_result_rows(data)


def load_check_result_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object or array")

    result: list[dict[str, Any]] = []
    outer = data.get("data", data)
    if isinstance(outer, dict):
        content = outer.get("content", [])
        if isinstance(content, list):
            for user_block in content:
                if not isinstance(user_block, dict):
                    continue
                paged_records = user_block.get("pagedRecords", {})
                if not isinstance(paged_records, dict):
                    continue
                rows = paged_records.get("content", [])
                if isinstance(rows, list):
                    result.extend([row for row in rows if isinstance(row, dict)])
    return result


@dataclass(frozen=True)
class ClassificationGroup:
    count: int
    normalized_fields: dict[str, str]
    examples: dict[str, list[str]]
    ids: list[str]
    in_amount: Decimal
    out_amount: Decimal


@dataclass
class _MutableGroup:
    normalized_fields: dict[str, str]
    rows: list[dict[str, Any]]
    examples: dict[str, list[str]]
    ids: list[str]
    in_amount: Decimal = Decimal("0")
    out_amount: Decimal = Decimal("0")


def classify_rows(
    rows: list[dict[str, Any]],
    *,
    fields: Iterable[str] | None = None,
    sample_size: int = 3,
) -> list[ClassificationGroup]:
    group_fields = list(fields or DEFAULT_GROUP_FIELDS)
    groups: dict[tuple[tuple[str, str], ...], _MutableGroup] = {}

    for row in rows:
        normalized_fields, raw_examples = build_group_fields(row, group_fields)
        signature = tuple(normalized_fields.items())
        if signature not in groups:
            groups[signature] = _MutableGroup(
                normalized_fields=normalized_fields,
                rows=[],
                examples=defaultdict(list),
                ids=[],
            )

        group = groups[signature]
        group.rows.append(row)
        group.in_amount += parse_amount(get_field_value(row, "inAmount"))
        group.out_amount += parse_amount(get_field_value(row, "outAmount"))

        row_id = get_field_value(row, "id")
        if row_id not in {None, ""} and len(group.ids) < sample_size:
            group.ids.append(str(row_id))

        for field, raw_value in raw_examples.items():
            if raw_value in {None, ""}:
                continue
            text = str(raw_value)
            if text not in group.examples[field] and len(group.examples[field]) < sample_size:
                group.examples[field].append(text)

    result = [
        ClassificationGroup(
            count=len(group.rows),
            normalized_fields=group.normalized_fields,
            examples={field: values for field, values in group.examples.items() if values},
            ids=group.ids,
            in_amount=group.in_amount,
            out_amount=group.out_amount,
        )
        for group in groups.values()
    ]
    return sorted(result, key=lambda group: (-group.count, tuple(group.normalized_fields.items())))


def build_group_fields(row: dict[str, Any], fields: list[str]) -> tuple[dict[str, str], dict[str, Any]]:
    normalized: dict[str, str] = {}
    raw_examples: dict[str, Any] = {}
    for field in fields:
        value = get_field_value(row, field)
        if value in {None, ""}:
            continue
        normalized_value = normalize_text(str(value))
        if normalized_value and normalized_value != "*":
            normalized[field] = normalized_value
            raw_examples[field] = value

    if normalized:
        return normalized, raw_examples

    fallback_pairs = sorted((str(key), value) for key, value in row.items() if value not in {None, ""})[:4]
    if not fallback_pairs:
        return {"record": "EMPTY"}, {}
    for key, value in fallback_pairs:
        normalized[key] = normalize_text(str(value))
        raw_examples[key] = value
    return normalized, raw_examples


def normalize_text(value: str) -> str:
    text = re.sub(r"\s+", " ", value.strip())
    text = re.sub(r"[A-Za-z]*\d{8,}[A-Za-z0-9_-]*", "*", text)
    text = re.sub(r"([（(])\s*\*\s*([）)])", r"\1*\2", text)
    text = re.sub(r"\*+", "*", text)
    return text


def get_field_value(row: dict[str, Any], field: str) -> Any:
    aliases = FIELD_ALIASES.get(field, [field])
    lookup = {canonical_field_name(key): value for key, value in row.items()}
    for alias in aliases:
        value = lookup.get(canonical_field_name(alias))
        if value is not None:
            return value
    return None


def canonical_field_name(name: str) -> str:
    return re.sub(r"[_\-\s]", "", name).lower()


def parse_amount(value: Any) -> Decimal:
    if value in {None, ""}:
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def render_report(
    rows: list[dict[str, Any]],
    *,
    source_name: str,
    fields: Iterable[str] | None = None,
    sample_size: int = 3,
) -> str:
    groups = classify_rows(rows, fields=fields, sample_size=sample_size)
    return render_group_report(groups, source_name=source_name, input_count=len(rows))


def render_group_report(
    groups: list[ClassificationGroup],
    *,
    source_name: str,
    input_count: int,
    title: str = "记录相似分组报告",
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- 输入文件: `{source_name}`",
        f"- 输入行数: `{input_count}`",
        f"- 分组数量: `{len(groups)}`",
        "",
        "## 分组",
        "",
    ]
    if not groups:
        lines.append("无可分组记录。")
        return "\n".join(lines)

    for index, group in enumerate(groups, start=1):
        lines.append(f"### 分组 {index}: {group.count} 行")
        lines.append(f"- 收入合计: `{format_amount(group.in_amount)}`")
        lines.append(f"- 支出合计: `{format_amount(group.out_amount)}`")
        for field, value in group.normalized_fields.items():
            lines.append(f"- {field}: `{value}`")
        for field, examples in group.examples.items():
            lines.append(f"- {field} 样例: {format_examples(examples)}")
        if group.ids:
            lines.append(f"- 样例 ID: `{', '.join(group.ids)}`")
        lines.append("")
    return "\n".join(lines).rstrip()


def format_amount(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def format_examples(values: list[str]) -> str:
    return " / ".join(f"`{value}`" for value in values)


def parse_fields(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [field.strip() for field in value.split(",") if field.strip()]


def infer_report_output_path(input_path: Path, output_root: Path) -> Path:
    platform = input_path.parent.name if input_path.parent.name else "unknown"
    return output_root / platform / f"{input_path.stem}.md"


def resolve_input_paths(target: Path, input_root: Path = Path("inputs")) -> list[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(path for path in target.glob("*.json") if path.is_file())
    if target.suffix == ".json":
        raise FileNotFoundError(f"Input JSON not found: {target}")

    platform_dir = input_root / resolve_platform_directory_name(str(target))
    if not platform_dir.is_dir():
        available = ", ".join(path.name for path in sorted(input_root.iterdir()) if path.is_dir()) if input_root.is_dir() else ""
        suffix = f" Available platforms: {available}" if available else ""
        raise FileNotFoundError(f"Input platform directory not found: {platform_dir}.{suffix}")
    return sorted(path for path in platform_dir.glob("*.json") if path.is_file())


def resolve_platform_directory_name(value: str) -> str:
    platform = platform_for_alias(value)
    if platform is not None:
        return PLATFORM_OUTPUT_LABELS.get(platform, value)
    return value


def write_report(input_path: Path, output_path: Path, *, fields: Iterable[str] | None, sample_size: int) -> Path:
    rows = load_rows(input_path)
    report = render_report(
        rows,
        source_name=str(input_path),
        fields=fields,
        sample_size=sample_size,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return output_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Group similar records in account-check JSON files.")
    parser.add_argument("input_path", nargs="?", type=Path, help="JSON file, input directory, or platform name/alias.")
    parser.add_argument("--input", dest="input_option", type=Path, help="JSON file, input directory, or platform name/alias.")
    parser.add_argument("--input-root", type=Path, default=Path("inputs"), help="Root directory for platform names. Default: inputs.")
    parser.add_argument("--output", type=Path, help="Write Markdown report to this path. Only valid for one input JSON.")
    parser.add_argument("--output-root", type=Path, default=Path("outputs"), help="Root directory for platform reports. Default: outputs.")
    parser.add_argument("--fields", help="Comma-separated fields to use for grouping. Defaults to common descriptive fields.")
    parser.add_argument("--sample-size", type=int, default=3, help="Number of raw examples to keep per group. Default: 3.")
    args = parser.parse_args(argv)
    args.input = args.input_path or args.input_option
    if args.input is None:
        parser.error("provide an input JSON path")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    fields = parse_fields(args.fields)
    input_paths = resolve_input_paths(args.input, args.input_root)
    batch_target = len(input_paths) > 1 or args.input.is_dir() or args.input.suffix != ".json"
    if batch_target and args.output:
        raise SystemExit("--output can only be used when processing one input JSON")
    if not input_paths:
        raise FileNotFoundError(f"No JSON files found for input: {args.input}")
    if batch_target:
        for input_path in input_paths:
            output_path = infer_report_output_path(input_path, args.output_root)
            write_report(input_path, output_path, fields=fields, sample_size=args.sample_size)
            print(f"{input_path}: {output_path}")
        return 0

    input_path = input_paths[0]
    if args.output:
        write_report(input_path, args.output, fields=fields, sample_size=args.sample_size)
        return 0

    rows = load_rows(input_path)
    report = render_report(
        rows,
        source_name=str(input_path),
        fields=fields,
        sample_size=args.sample_size,
    )
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
