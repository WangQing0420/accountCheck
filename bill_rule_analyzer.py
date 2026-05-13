#!/usr/bin/env python3
"""Analyze unmatched platform bill rows against Rails account type seed rules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_RAILS_ROOT = Path("/Users/wangqing/workspace/plutus-rails")


SOURCE_TYPE_ALIASES = {
    # Rails 种子文件中允许一条逻辑规则同时覆盖多个来源表。
    "all": {"TAOBAO_ACCOUNT_RECORD", "TB_WHALE_ACCOUNT_RECORD"},
}


SOURCE_MATCH_FIELDS = {
    # 未命中规则的账单会按这些字段生成稳定分组；字段应贴近各来源表
    # 实际用于归类的字段，方便直接生成可补充到 seeds 的候选片段。
    "TAOBAO_ACCOUNT_RECORD": ["memo", "business_type", "in_amount", "type", "merchant_order_no", "biz_desc", "biz_main_order_no"],
    "TB_WHALE_ACCOUNT_RECORD": ["memo", "business_type", "in_amount", "biz_desc"],
    "TAOBAO_HAIWAI_ACCOUNT_RECORD": ["memo", "remarks", "partner_transaction_id", "type"],
    "TB_ALIPAY_SMALL_TRANSFER_ACCOUNT_RECORD": ["biz_desc", "biz_main_order_no", "memo"],
    "PDD_MARKETING_ACCOUNT_RECORD": ["memo", "business_type", "in_amount"],
    "PDD_MALL_ACCOUNT_RECORD": ["memo", "business_type", "in_amount", "biz_desc"],
    "PDD_MARKETING_ACTIVITY_SETTLEMENT_DETAIL": ["memo", "settlement_method", "activity_type", "account_type"],
    "DOU_ORDER_SETTLE_BILL_DETAIL": ["memo"],
    "DOU_SHOP_ACCOUNT_ITEM": ["account_bill_desc", "in_amount", "memo", "real_amount"],
    "DOU_DEPOSIT_BILL": ["memo", "in_amount", "real_amount", "operate_type"],
    "DOU_MANAGER_ACCOUNT_DETAIL": ["remark"],
    "DOU_INSURANCE_BILL": ["insurance_product"],
    "KUAISHOU_ORDER_FLOW_DETAIL": ["memo"],
    "KUAISHOU_DEPOSIT_BILL": ["memo", "operate_type", "transaction_description"],
    "KUAISHOU_ACCOUNT_BILL": ["memo", "biz_type", "biz_desc", "remark", "in_amount"],
    "JINGDONG_LEDGER_BILL_DETAIL": ["fee_name", "remark", "cost_item", "settlement_memo"],
    "JINGDONG_INSURANCE_BILL": ["duty"],
    "JINGDONG_CPS_BILL_DETAIL": ["memo"],
    "JINGDONG_CPS_BILL_BACK_DETAIL": ["memo"],
    "JINGDONG_AFTERSALE_MICROTRANSFER_DETAIL": ["reason", "reason_name"],
    "ALIBABA_ALIPAY_ACCOUNT_RECORD": ["memo", "biz_type", "biz_desc", "in_amount"],
    "XHS_SELLER_ACCOUNT_RECORD": ["remark", "type_desc", "business_no"],
    "XHS_TRANSACTION": ["memo"],
    "WXXD_FUNDS_FLOW_DETAIL": ["memo", "detail", "business_type", "flow_id"],
    "WXXD_DEPOSIT_BILL": ["memo", "detail", "business_type", "bill_no"],
}


@dataclass
class Rule:
    id: int
    name: str
    match_rule: dict[str, Any]
    extract_rule: dict[str, Any]
    expense_type_id: int | None
    source_type: str
    sort_order: int
    status: int = 1

    def source_type_matches(self, source_type: str) -> bool:
        if self.source_type == source_type:
            return True
        return source_type in SOURCE_TYPE_ALIASES.get(self.source_type, set())

    def matches(self, row: dict[str, Any], source_type: str) -> bool:
        if not self.source_type_matches(source_type):
            return False
        if not self.match_rule:
            return False

        normalized = normalize_row(row)
        for key, pattern in self.match_rule.items():
            value = normalized.get(key.upper())
            if value is None:
                return False
            # 部分 seed 规则使用布尔值，而导出数据通常是字符串；
            # 这里统一转换后比较，避免 "true"/"false" 无法命中。
            if isinstance(pattern, bool):
                if parse_bool(value) is not pattern:
                    return False
                continue
            # match_rule 中的值按正则处理；如果历史 seed 中存在非法正则，
            # regex_search 会退化为精确匹配，避免整次分析失败。
            if not regex_search(str(pattern), str(value)):
                return False
        return True


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {str(key).strip().upper(): value for key, value in row.items()}


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def regex_search(pattern: str, value: str) -> bool:
    try:
        return re.fullmatch(pattern, value) is not None
    except re.error:
        return pattern == value


def parse_account_record_rules(content: str, platform: str) -> list[Rule]:
    body = extract_account_record_hash_body(content)
    entries = parse_top_level_entries(body)
    return [rule_from_entry(rule_id, params, platform) for rule_id, params in entries]


def extract_account_record_hash_body(content: str) -> str:
    # 大多数平台会先赋值 account_record_types；Alibaba seeds 则把 hash
    # 直接写在 AccountRecordType.transaction 代码块里。
    variable_match = re.search(r"^\s*account_record_types\s*=", content, re.M)
    if variable_match:
        brace_start = content.find("{", variable_match.end())
        if brace_start == -1:
            raise ValueError("account_record_types hash body not found")
        brace_end = find_matching(content, brace_start, "{", "}")
        return content[brace_start + 1 : brace_end]

    marker = "AccountRecordType.transaction"
    start = content.find(marker)
    if start == -1:
        raise ValueError("AccountRecordType.transaction block not found")

    brace_start = content.find("{", start)
    if brace_start == -1:
        raise ValueError("AccountRecordType hash body not found")

    brace_end = find_matching(content, brace_start, "{", "}")
    return content[brace_start + 1 : brace_end]


def find_matching(text: str, start: int, opener: str, closer: str) -> int:
    # 遍历嵌套的 Ruby 字面量，同时忽略字符串内部的括号。
    depth = 0
    quote: str | None = None
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index
    raise ValueError(f"Unclosed {opener}")


def parse_top_level_entries(body: str) -> list[tuple[int, dict[str, Any]]]:
    entries: list[tuple[int, dict[str, Any]]] = []
    parser = RubyLiteralParser(body)
    while True:
        parser.skip_ws_and_comments()
        if parser.eof():
            return entries
        if parser.peek() == ",":
            parser.index += 1
            continue
        rule_id = parser.parse_int()
        parser.skip_ws_and_comments()
        parser.expect("=>")
        parser.skip_ws_and_comments()
        params = parser.parse_hash()
        entries.append((rule_id, params))
        parser.skip_ws_and_comments()
        if not parser.eof() and parser.peek() == ",":
            parser.index += 1


def rule_from_entry(rule_id: int, params: dict[str, Any], platform: str) -> Rule:
    source_type = params.get("source_type")
    if source_type is None and platform == "alibaba":
        source_type = "ALIBABA_ALIPAY_ACCOUNT_RECORD"
    return Rule(
        id=rule_id,
        name=str(params.get("name", "")),
        match_rule=uppercase_nested(params.get("match_rule") or {}),
        extract_rule=uppercase_nested(params.get("extract_rule") or {}),
        expense_type_id=params.get("expense_type_id"),
        source_type=str(source_type or "UNKNOWN"),
        sort_order=int(params.get("sort_order") or 999999),
        status=int(params.get("status") if params.get("status") is not None else 1),
    )


def uppercase_nested(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key).upper(): uppercase_nested(inner) for key, inner in value.items()}
    return value


class RubyLiteralParser:
    """解析 account seed 文件中用到的 Ruby 字面量子集。"""

    def __init__(self, text: str):
        self.text = text
        self.index = 0

    def eof(self) -> bool:
        return self.index >= len(self.text)

    def peek(self) -> str:
        return self.text[self.index]

    def skip_ws_and_comments(self) -> None:
        while not self.eof():
            if self.text[self.index].isspace():
                self.index += 1
                continue
            if self.text[self.index] == "#":
                while not self.eof() and self.text[self.index] != "\n":
                    self.index += 1
                continue
            break

    def expect(self, token: str) -> None:
        if not self.text.startswith(token, self.index):
            raise ValueError(f"Expected {token!r} at {self.index}")
        self.index += len(token)

    def parse_value(self) -> Any:
        self.skip_ws_and_comments()
        if self.text.startswith("{", self.index):
            return self.parse_hash()
        if self.text.startswith("'", self.index) or self.text.startswith('"', self.index):
            return self.parse_string()
        if self.text.startswith(":", self.index):
            return self.parse_symbol()
        if self.text.startswith("nil", self.index):
            self.index += 3
            return None
        if self.text.startswith("true", self.index):
            self.index += 4
            return True
        if self.text.startswith("false", self.index):
            self.index += 5
            return False
        return self.parse_int()

    def parse_hash(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        self.expect("{")
        while True:
            self.skip_ws_and_comments()
            if self.peek() == "}":
                self.index += 1
                return result
            key = self.parse_key()
            self.skip_ws_and_comments()
            if self.text.startswith("=>", self.index):
                self.index += 2
            else:
                self.expect(":")
            value = self.parse_value()
            result[str(key)] = value
            self.skip_ws_and_comments()
            if self.peek() == ",":
                self.index += 1

    def parse_key(self) -> str:
        self.skip_ws_and_comments()
        if self.peek() in {"'", '"'}:
            return self.parse_string()
        if self.peek() == ":":
            return self.parse_symbol()
        start = self.index
        while not self.eof() and re.match(r"[\w?]", self.peek()):
            self.index += 1
        if start == self.index:
            raise ValueError(f"Expected hash key at {self.index}")
        return self.text[start:self.index]

    def parse_symbol(self) -> str:
        self.expect(":")
        start = self.index
        while not self.eof() and re.match(r"[\w?]", self.peek()):
            self.index += 1
        return self.text[start:self.index]

    def parse_int(self) -> int:
        start = self.index
        if not self.eof() and self.peek() == "-":
            self.index += 1
        while not self.eof() and self.peek().isdigit():
            self.index += 1
        if start == self.index or self.text[start:self.index] == "-":
            raise ValueError(f"Expected integer at {self.index}")
        return int(self.text[start:self.index])

    def parse_string(self) -> str:
        quote = self.peek()
        self.index += 1
        chars: list[str] = []
        escape = False
        while not self.eof():
            char = self.peek()
            self.index += 1
            if escape:
                chars.append("\\" + char if char not in {quote, "\\"} else char)
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                return "".join(chars)
            else:
                chars.append(char)
        raise ValueError("Unclosed string")


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


def render_report(rows: list[dict[str, Any]], rules: list[Rule], platform: str, source_type: str, include_inactive: bool = False) -> str:
    usable_rules = [rule for rule in rules if include_inactive or rule.status == 1]
    matched: list[tuple[dict[str, Any], Rule]] = []
    unmatched: list[dict[str, Any]] = []
    for row in rows:
        row_matches = [rule for rule in usable_rules if rule.matches(row, source_type)]
        if row_matches:
            # Rails 会优先应用 sort_order 更小的规则；id 用于保证同优先级时输出稳定。
            matched.append((row, sorted(row_matches, key=lambda rule: (rule.sort_order, rule.id))[0]))
        else:
            unmatched.append(row)

    lines = [
        f"# 账单归类分析报告",
        "",
        f"- 平台: `{platform}`",
        f"- 账单来源: `{source_type}`",
        f"- 输入行数: `{len(rows)}`",
        f"- 已命中现有规则: `{len(matched)}`",
        f"- 未命中规则: `{len(unmatched)}`",
        "",
    ]

    if matched:
        lines.extend(["## 已命中现有规则", ""])
        counts = Counter(rule.id for _, rule in matched)
        rule_by_id = {rule.id: rule for _, rule in matched}
        for rule_id, count in counts.most_common():
            rule = rule_by_id[rule_id]
            lines.append(f"- `{count}` 行 -> `{rule.id}` {rule.name} / expense_type_id=`{rule.expense_type_id}`")
        lines.append("")

    lines.extend(["## 未归类分组", ""])
    if not unmatched:
        lines.append("无。")
        return "\n".join(lines)

    for index, (signature, group_rows) in enumerate(group_unmatched_rows(unmatched, source_type).items(), start=1):
        lines.append(f"### 分组 {index}: {len(group_rows)} 行")
        for key, value in signature:
            lines.append(f"- {key}: `{value}`")
        lines.append("")
        lines.append("候选 seeds 片段：")
        lines.append("")
        lines.append("```ruby")
        lines.append(render_seed_snippet(signature, source_type))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def group_unmatched_rows(rows: list[dict[str, Any]], source_type: str) -> dict[tuple[tuple[str, str], ...], list[dict[str, Any]]]:
    fields = SOURCE_MATCH_FIELDS.get(source_type, [])
    groups: dict[tuple[tuple[str, str], ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        normalized = normalize_row(row)
        pairs = []
        for field in fields:
            value = normalized.get(field.upper())
            if value not in {None, ""}:
                pairs.append((field, str(value)))
        if not pairs:
            # 未配置字段的来源也要分组，退化为取前几个非空导出字段作为签名。
            pairs = sorted((str(key), str(value)) for key, value in row.items() if value not in {None, ""})[:4]
        groups[tuple(pairs)].append(row)
    return dict(groups)


def render_seed_snippet(signature: tuple[tuple[str, str], ...], source_type: str) -> str:
    match_parts = ", ".join(f"{field}: '{escape_ruby_single_quote(regex_escape_literal(value))}'" for field, value in signature)
    return (
        "TODO_ID => { "
        "name: 'TODO', "
        f"match_rule: {{ {match_parts} }}, "
        "expense_type_id: TODO, "
        f"source_type: :{source_type}, "
        "sort_order: TODO "
        "},"
    )


def regex_escape_literal(value: str) -> str:
    return re.escape(value).replace("\\ ", " ")


def escape_ruby_single_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def load_seed_rules(rails_root: Path, platform: str) -> list[Rule]:
    seed_path = rails_root / "db" / "seeds" / "static" / platform / "account_expense_type.seeds.rb"
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_path}")
    return parse_account_record_rules(seed_path.read_text(encoding="utf-8"), platform=platform)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze unmatched platform bill rows against account_expense_type seeds.")
    parser.add_argument("--platform", required=True, help="Platform directory under db/seeds/static, e.g. dou, taobao, pdd.")
    parser.add_argument("--source-type", required=True, help="Account source type, e.g. DOU_INSURANCE_BILL.")
    parser.add_argument("--input", required=True, type=Path, help="JSON file exported from account record check-result API.")
    parser.add_argument("--rails-root", type=Path, default=DEFAULT_RAILS_ROOT, help="Path to plutus-rails.")
    parser.add_argument("--include-inactive", action="store_true", help="Also match status=0/-1 seed rules.")
    parser.add_argument("--output", type=Path, help="Write Markdown report to this file.")
    args = parser.parse_args(argv)

    rows = load_rows(args.input)
    rules = load_seed_rules(args.rails_root, args.platform)
    report = render_report(rows, rules, args.platform, args.source_type, include_inactive=args.include_inactive)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
