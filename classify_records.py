#!/usr/bin/env python3
"""Group similar account-check records by normalized descriptive fields."""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from bill_rule_analyzer import load_rows


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

NON_DESCRIPTIVE_FIELDS = {"businessType", "bizType", "bizTypeDesc", "operateType"}

NON_PLATFORM_FEE_RULES = [
    ("货款/结算收入", re.compile(r"货款|结算收入|订单结算|交易收款|买家付款")),
    ("充值/提现/资金往来", re.compile(r"充值|提现|生活费|余额转出|余额转入|资金转入|资金转出")),
    ("保证金流转", re.compile(r"保证金.*(退回|解冻|释放|转出)|保证金充值")),
]

SPLIT_REPORTS = {
    "all": None,
    "classification_required_platform_fee": (True, True),
    "classification_required_non_platform_fee": (True, False),
    "no_classification_non_platform_fee": (False, False),
}

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


@dataclass(frozen=True)
class ClassificationGroup:
    count: int
    normalized_fields: dict[str, str]
    examples: dict[str, list[str]]
    ids: list[str]
    in_amount: Decimal
    out_amount: Decimal
    classification_required: bool
    platform_fee_candidate: bool
    assessment_reasons: list[str]


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
                examples={field: [] for field in normalized_fields},
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
            if raw_value not in {None, ""}:
                text = str(raw_value)
                if text not in group.examples[field] and len(group.examples[field]) < sample_size:
                    group.examples[field].append(text)

    result = [
        build_classification_group(group)
        for group in groups.values()
    ]
    return sorted(result, key=lambda group: (-group.count, tuple(group.normalized_fields.items())))


def build_classification_group(group: _MutableGroup) -> ClassificationGroup:
    classification_required, platform_fee_candidate, reasons = assess_group(
        group.normalized_fields,
        group.in_amount,
        group.out_amount,
    )
    return ClassificationGroup(
        count=len(group.rows),
        normalized_fields=group.normalized_fields,
        examples={field: values for field, values in group.examples.items() if values},
        ids=group.ids,
        in_amount=group.in_amount,
        out_amount=group.out_amount,
        classification_required=classification_required,
        platform_fee_candidate=platform_fee_candidate,
        assessment_reasons=reasons,
    )


def assess_group(normalized_fields: dict[str, str], in_amount: Decimal, out_amount: Decimal) -> tuple[bool, bool, list[str]]:
    reasons: list[str] = []
    meaningful_fields = [field for field in normalized_fields if field not in NON_DESCRIPTIVE_FIELDS]
    classification_required = bool(meaningful_fields)
    if not classification_required:
        reasons.append("缺少有效业务描述")

    joined_text = " ".join(normalized_fields.values())
    platform_fee_candidate = classification_required
    for reason, pattern in NON_PLATFORM_FEE_RULES:
        if pattern.search(joined_text):
            platform_fee_candidate = False
            reasons.append(reason)
            break

    if platform_fee_candidate and out_amount <= 0:
        platform_fee_candidate = False
        reasons.append("无支出金额")

    if not reasons:
        reasons.append("默认保留待确认")
    return classification_required, platform_fee_candidate, reasons


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
    title: str = "记录相似归类报告",
) -> str:
    lines = [
        f"# {title}",
        "",
        f"- 输入文件: `{source_name}`",
        f"- 输入行数: `{input_count}`",
        f"- 分组数量: `{len(groups)}`",
        "",
        "## 归类分组",
        "",
    ]
    if not groups:
        lines.append("无可归类记录。")
        return "\n".join(lines)

    for index, group in enumerate(groups, start=1):
        lines.append(f"### 分组 {index}: {group.count} 行")
        lines.append(f"- 账单归类: `{format_bool(group.classification_required)}`")
        lines.append(f"- 平台费用: `{format_bool(group.platform_fee_candidate, yes='候选', no='否')}`")
        lines.append(f"- 判断原因: `{', '.join(group.assessment_reasons)}`")
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


def split_groups(groups: list[ClassificationGroup]) -> dict[str, list[ClassificationGroup]]:
    result: dict[str, list[ClassificationGroup]] = {}
    for name, marker in SPLIT_REPORTS.items():
        if marker is None:
            result[name] = groups
            continue
        classification_required, platform_fee_candidate = marker
        result[name] = [
            group
            for group in groups
            if group.classification_required is classification_required
            and group.platform_fee_candidate is platform_fee_candidate
        ]
    return result


def infer_split_output_paths(input_path: Path, output_root: Path) -> dict[str, Path]:
    platform = input_path.parent.name if input_path.parent.name else "unknown"
    base_name = input_path.stem
    return {
        name: output_root / platform / base_name / f"{name}.md"
        for name in SPLIT_REPORTS
    }


def write_split_reports(
    rows: list[dict[str, Any]],
    *,
    input_path: Path,
    output_root: Path,
    fields: Iterable[str] | None = None,
    sample_size: int = 3,
) -> dict[str, Path]:
    groups = classify_rows(rows, fields=fields, sample_size=sample_size)
    split = split_groups(groups)
    paths = infer_split_output_paths(input_path, output_root)
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        report = render_group_report(
            split[name],
            source_name=str(input_path),
            input_count=len(rows),
            title=f"记录相似归类报告 - {name}",
        )
        path.write_text(report, encoding="utf-8")
    return paths


def format_amount(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal("1")))
    return format(normalized, "f")


def format_bool(value: bool, *, yes: str = "需要", no: str = "不需要") -> str:
    return yes if value else no


def format_examples(values: list[str]) -> str:
    return " / ".join(f"`{value}`" for value in values)


def parse_fields(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [field.strip() for field in value.split(",") if field.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Group similar records in one account-check JSON file.")
    parser.add_argument("input_path", nargs="?", type=Path, help="JSON file from account record check-result API.")
    parser.add_argument("--input", dest="input_option", type=Path, help="JSON file from account record check-result API.")
    parser.add_argument("--output", type=Path, help="Write Markdown report to this path. Defaults to stdout.")
    parser.add_argument("--output-root", type=Path, default=Path("outputs"), help="Root directory for --split reports. Default: outputs.")
    parser.add_argument("--split", action="store_true", help="Write separate reports by classification/platform-fee markers.")
    parser.add_argument("--fields", help="Comma-separated fields to use for grouping. Defaults to common descriptive fields.")
    parser.add_argument("--sample-size", type=int, default=3, help="Number of raw examples to keep per group. Default: 3.")
    args = parser.parse_args(argv)
    args.input = args.input_path or args.input_option
    if args.input is None:
        parser.error("provide an input JSON path")
    if args.split and args.output:
        parser.error("--output cannot be used with --split; use --output-root")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = load_rows(args.input)
    fields = parse_fields(args.fields)
    if args.split:
        paths = write_split_reports(
            rows,
            input_path=args.input,
            output_root=args.output_root,
            fields=fields,
            sample_size=args.sample_size,
        )
        for name, path in paths.items():
            print(f"{name}: {path}")
        return 0

    report = render_report(
        rows,
        source_name=str(args.input),
        fields=fields,
        sample_size=args.sample_size,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
