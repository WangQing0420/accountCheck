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

from bill_rule_analyzer import (
    DEFAULT_RAILS_ROOT,
    AccountExpenseType,
    Rule,
    load_rows,
    load_seed_rules,
    parse_account_expense_types,
)


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

GENERIC_BUSINESS_TYPES = {"other", "其它", "转账", "transfer_06"}

STORE_CONTEXT_RULE = re.compile(
    r"淘宝|天猫|支付宝|阿里|阿里妈妈|菜鸟|京东|拼多多|抖音|快手|微信|小红书|1688|"
    r"商家|店铺|订单|交易|售后|保证金|佣金|服务费|保险|保费|运费险|物流|"
    r"补贴|营销|扣款|费用|技术|软件|红包|消费券|分账|结算|充值|提现|"
    r"付款|收款|赔付|违约金|税费"
)

PERSONAL_FLOW_RULES = [
    re.compile(r"^\d{1,2}\.\d{1,2}(和\d{1,2}\.\d{1,2})?退货$"),
    re.compile(r"^(预约转账|还贷款|修图|ai|jzf|tks|卓梵推广预支)$", re.IGNORECASE),
    re.compile(r"^.+推广预支$"),
    re.compile(r"^.+工厂货款$"),
]

PLATFORM_FEE_RULES = [
    ("平台服务/佣金/扣点", re.compile(r"服务费|佣金|扣点|技术服务|软件服务|平台抽佣|收费")),
    ("营销推广费用", re.compile(r"淘客|联盟|直通车|万相台|超级推荐|钻展|品销宝|消费券.*扣回|礼金.*服务费|营销.*服务费|推广.*服务费|广告.*服务费|广告发布费")),
    ("保险费用", re.compile(r"保险承保|保费收取|运费险|订单险|责任险|保证金险")),
    ("物流/仓储费用", re.compile(r"物流.*费|运费|仓储费|仓租|配送费|装卸费|包装费|耗材费|拦截费|入仓费")),
    ("赔付/违约/税费", re.compile(r"赔付|赔款|违约金|罚金|税费|关税")),
]

NON_PLATFORM_FEE_RULES = [
    ("货款/结算收入", re.compile(r"货款|结算收入|订单结算|交易收款|买家付款")),
    ("退款/退费/返还", re.compile(r"退款|退费|返还|退回")),
    ("充值/提现/资金往来", re.compile(r"充值|提现|转账|生活费|余额转出|余额转入|资金转入|资金转出|账户往来")),
    ("保证金流转", re.compile(r"保证金.*(退回|解冻|释放|转出|充值)")),
    ("贷款/还款", re.compile(r"贷款|还款|网商贷|订单贷|信用贷")),
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

TEMPLATE_ROOT = Path(__file__).resolve().parent / "templates"

PLATFORM_TEMPLATE_LABELS = {
    "1688": "1688",
    "alibaba": "1688",
    "dou": "抖店",
    "douyin": "抖店",
    "doudian": "抖店",
    "jd": "京东",
    "jingdong": "京东",
    "kuaishou": "快手",
    "pdd": "拼多多",
    "pinduoduo": "拼多多",
    "taobao": "淘宝",
    "wechat": "微信小店",
    "weixin": "微信小店",
    "weixinxiaodian": "微信小店",
    "wxxd": "微信小店",
    "xhs": "小红书",
    "xiaohongshu": "小红书",
}

TEMPLATE_BILL_NAME_HINTS = [
    (("insurance", "baoxian"), "保险费明细"),
    (("deposit", "bond"), "保证金"),
    (("manager",), "管家账户明细"),
    (("fundsflow", "funds", "flow", "shopaccountitem", "ordersettlebilldetail"), "资金流水账单"),
    (("alipay",), "支付宝账单"),
    (("ledger",), "商家账单明细"),
    (("smalltransfer",), "小额打款"),
    (("marketing", "activitysettlement"), "营销账单"),
    (("mall",), "货款账单"),
    (("selleraccountrecord", "transaction"), "货款动账流水"),
    (("accountbill",), "资金账单明细"),
]

SPLIT_TEMPLATE_KINDS = {
    "classification_required_platform_fee": ("平台费用",),
    "classification_required_non_platform_fee": ("账单归类", "资金分析"),
}

PLACEHOLDER_FIELD_CANDIDATES = {
    "备注": ["memo", "remark", "remarks", "settlementMemo"],
    "业务类型": ["businessType", "bizType", "bizTypeDesc", "operateType", "typeDesc"],
    "业务描述": ["bizDesc", "accountBillDesc", "transactionDescription", "detail"],
    "费用项": ["costItem", "feeName"],
    "钱包结算备注": ["settlementMemo"],
    "保险产品": ["insuranceProduct"],
    "产品名称": ["insuranceProduct", "feeName", "costItem"],
    "描述": ["detail", "transactionDescription", "bizDesc", "accountBillDesc"],
    "动账类型": ["typeDesc", "operateType", "bizTypeDesc", "businessType"],
    "动账场景": ["businessType", "bizTypeDesc", "operateType", "typeDesc"],
    "交易类型描述": ["typeDesc", "bizTypeDesc", "businessType"],
    "账户类型": ["accountType"],
    "账务类型": ["accountBillDesc", "bizTypeDesc", "businessType"],
    "打款原因": ["reason", "memo", "remark"],
    "打款原因描述": ["reasonDesc", "bizDesc", "detail"],
    "订单编号": ["orderId", "orderNo", "tid"],
    "订单号": ["orderId", "orderNo", "tid"],
    "关联单号": ["relatedOrderNo", "orderId", "orderNo", "tid"],
    "关联订单号": ["relatedOrderNo", "orderId", "orderNo", "tid"],
    "关联子订单号": ["relatedSubOrderNo", "subOrderNo", "oid"],
    "子订单号": ["subOrderNo", "oid"],
    "商户订单号": ["merchantOrderNo", "orderId", "orderNo", "tid"],
    "业务订单号": ["bizOrderNo", "orderId", "orderNo", "tid"],
    "业务订单号（文件）": ["bizOrderNo", "orderId", "orderNo", "tid"],
    "淘宝订单编号（聚合）": ["taobaoOrderNo", "orderId", "orderNo", "tid"],
    "业务单号": ["bizOrderNo", "orderId", "orderNo", "tid"],
}

HUMAN_FIELD_LABELS = {
    "accountBillDesc": "账单描述",
    "bizDesc": "业务描述",
    "bizType": "业务类型",
    "bizTypeDesc": "业务类型描述",
    "businessType": "业务类型",
    "costItem": "费用项",
    "detail": "描述",
    "feeName": "费用名称",
    "insuranceProduct": "保险产品",
    "memo": "备注",
    "operateType": "操作类型",
    "remark": "备注",
    "remarks": "备注",
    "settlementMemo": "结算备注",
    "transactionDescription": "交易描述",
    "typeDesc": "类型描述",
}


@dataclass(frozen=True)
class ExistingRuleMatch:
    rule: Rule
    expense_type: AccountExpenseType | None


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
    existing_rule_match: ExistingRuleMatch | None = None


@dataclass(frozen=True)
class ExistingRuleContext:
    platform: str
    source_type: str
    rules: list[Rule]
    expense_types: dict[int, AccountExpenseType]


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
    if classification_required and looks_like_personal_flow(normalized_fields, joined_text):
        classification_required = False
        reasons.append("个人/非店铺流水")

    platform_fee_candidate = False
    for reason, pattern in NON_PLATFORM_FEE_RULES:
        if pattern.search(joined_text):
            reasons.append(reason)
            break

    if classification_required and not any(reason in reasons for reason, _pattern in NON_PLATFORM_FEE_RULES):
        for reason, pattern in PLATFORM_FEE_RULES:
            if pattern.search(joined_text):
                platform_fee_candidate = True
                reasons.append(reason)
                break

    if platform_fee_candidate and out_amount <= 0:
        platform_fee_candidate = False
        reasons.append("无支出金额")

    if not reasons:
        reasons.append("默认保留待确认")
    return classification_required, platform_fee_candidate, reasons


def looks_like_personal_flow(normalized_fields: dict[str, str], joined_text: str) -> bool:
    business_values = {
        normalized_fields[field]
        for field in NON_DESCRIPTIVE_FIELDS
        if field in normalized_fields
    }
    has_only_generic_business_type = bool(business_values) and business_values <= GENERIC_BUSINESS_TYPES
    has_platform_context = bool(STORE_CONTEXT_RULE.search(joined_text))
    if not has_only_generic_business_type or has_platform_context:
        return False

    memo = normalized_fields.get("memo", "")
    if not memo:
        return False
    if any(pattern.search(memo) for pattern in PERSONAL_FLOW_RULES):
        return True
    if re.fullmatch(r"[A-Za-z]{1,4}", memo):
        return True
    return False


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
    rails_root: Path | None = None,
    fetch_jobs_path: Path | None = None,
) -> dict[str, Path]:
    groups = classify_rows(rows, fields=fields, sample_size=sample_size)
    rule_context = load_existing_rule_context(
        input_path,
        rails_root=rails_root,
        fetch_jobs_path=fetch_jobs_path,
    )
    if rule_context is not None:
        groups = attach_existing_rule_matches(groups, rule_context)
    split = split_groups(groups)
    paths = infer_split_output_paths(input_path, output_root)
    for name, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        report = render_split_report(
            name,
            split[name],
            input_path=input_path,
            source_name=str(input_path),
            input_count=len(rows),
        )
        path.write_text(report, encoding="utf-8")
    return paths


def render_split_report(
    report_name: str,
    groups: list[ClassificationGroup],
    *,
    input_path: Path,
    source_name: str,
    input_count: int,
) -> str:
    template_path = select_template_path(report_name, input_path)
    if template_path is not None:
        return render_template_group_report(
            groups,
            template_path=template_path,
            source_name=source_name,
            input_count=input_count,
        )
    return render_group_report(
        groups,
        source_name=source_name,
        input_count=input_count,
        title=f"记录相似归类报告 - {report_name}",
    )


def select_template_path(report_name: str, input_path: Path) -> Path | None:
    platform_label = infer_platform_template_label(input_path)
    template_kinds = SPLIT_TEMPLATE_KINDS.get(report_name)
    if not platform_label or not template_kinds:
        return None

    for template_kind in template_kinds:
        candidates = sorted(TEMPLATE_ROOT.glob(f"平台费用检查-{platform_label}-*-{template_kind}模板.md"))
        if candidates:
            return choose_best_template(candidates, input_path)
    return None


def infer_platform_template_label(input_path: Path) -> str | None:
    platform = canonical_field_name(input_path.parent.name)
    return PLATFORM_TEMPLATE_LABELS.get(platform)


def choose_best_template(candidates: list[Path], input_path: Path) -> Path | None:
    stem = canonical_field_name(input_path.stem)

    def score(path: Path) -> tuple[int, str]:
        name = canonical_field_name(path.stem)
        value = 0
        for tokens, bill_name in TEMPLATE_BILL_NAME_HINTS:
            if any(token in stem for token in tokens) and bill_name in path.stem:
                value += 30
        if stem and stem in name:
            value += 20
        for token in re.split(r"[_\-\s]+", input_path.stem.lower()):
            if token and token not in {"check", "result"} and token in name:
                value += 5
        if "通用账单" in path.stem:
            value += 3
        return (-value, path.name)

    ranked = sorted(candidates, key=score)
    best = ranked[0]
    best_value = -score(best)[0]
    if best_value <= 0 and len(candidates) > 1:
        return None
    return best


def render_template_group_report(
    groups: list[ClassificationGroup],
    *,
    template_path: Path,
    source_name: str,
    input_count: int,
) -> str:
    lines = template_path.read_text(encoding="utf-8").splitlines()
    row_index = find_template_row_index(lines)
    if row_index is None:
        return render_group_report(
            groups,
            source_name=source_name,
            input_count=input_count,
            title=f"{template_path.stem} - 自动填充",
        )

    template_row = lines[row_index]
    rendered_rows = [render_template_table_row(template_row, group) for group in groups]
    output_lines = lines[:row_index] + rendered_rows + lines[row_index + 1:]
    if not groups:
        output_lines.append("")
        output_lines.append("无可归类记录。")
    output_lines.extend([
        "",
        "<!-- 自动生成信息 -->",
        f"<!-- 输入文件: {source_name} -->",
        f"<!-- 输入行数: {input_count} -->",
        f"<!-- 分组数量: {len(groups)} -->",
    ])
    return "\n".join(output_lines).rstrip()


def find_template_row_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith("|") and re.search(r"\{[^{}]+\}", line):
            return index
    return None


def render_template_table_row(template_row: str, group: ClassificationGroup) -> str:
    return re.sub(
        r"\{([^{}]+)\}",
        lambda match: escape_markdown_cell(resolve_template_placeholder(match.group(1), group)),
        template_row,
    )


def resolve_template_placeholder(name: str, group: ClassificationGroup) -> str:
    if name in {"账单归类名称", "名称"}:
        if group.existing_rule_match is not None:
            return group.existing_rule_match.rule.name
        return build_group_name(group)
    if name == "匹配规则":
        return build_match_rule(group)
    if name in {"原始记录", "原始记录和业务调研"}:
        return build_original_record_summary(group)
    if name in {"订单号提取处", "订单号其它提取处"}:
        return infer_order_extract_source(group)
    if name == "平台费用名称" and group.existing_rule_match is not None and group.existing_rule_match.expense_type is not None:
        return group.existing_rule_match.expense_type.name
    if name == "科目" and group.existing_rule_match is not None and group.existing_rule_match.expense_type is not None:
        return group.existing_rule_match.expense_type.parent_name
    if name in {"平台费用名称", "科目", "费用说明", "账单来源"}:
        return f"{{{name}}}"

    value = lookup_group_value(group, PLACEHOLDER_FIELD_CANDIDATES.get(name, [name]))
    if value:
        return value
    return f"{{{name}}}"


def build_group_name(group: ClassificationGroup) -> str:
    for field in DEFAULT_GROUP_FIELDS:
        if field in group.normalized_fields and field not in NON_DESCRIPTIVE_FIELDS:
            return build_candidate_name(group.normalized_fields[field])
    for value in group.normalized_fields.values():
        return build_candidate_name(value)
    return "未命名归类"


def build_candidate_name(value: str) -> str:
    text = value.strip()
    extracted = extract_named_business_fragment(text)
    if extracted:
        text = extracted

    text = re.sub(r"保险承保[-_－—]*", "", text)
    text = re.sub(r"[（(][^（）()]*\*[^（）()]*[）)]", "", text)
    text = re.sub(r"[-_－—]?(订单号|运单号|业务单号|关联单号)[：:［\[]?\*[\]］]?", "", text)
    text = re.sub(r"[-_－—]?\*", "", text)
    text = re.sub(r"[（(]\s*[）)]", "", text)
    text = re.sub(r"[（(][^（）()]*$", "", text)
    text = re.sub(r"[）)]+$", "", text)
    text = re.sub(r"[，,、；;：:。.\s]+$", "", text)

    suffixes = ("扣款", "支付", "收取", "退回")
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if text.endswith(suffix) and len(text) > len(suffix) + 1:
                text = text[: -len(suffix)]
                changed = True
                text = re.sub(r"[，,、；;：:。.\s]+$", "", text)

    text = re.sub(r"\s+", " ", text).strip()
    return text or value


def extract_named_business_fragment(text: str) -> str | None:
    match = re.search(r"扣款用途[：:]\s*([^，,]+)", text)
    if match:
        return match.group(1)
    return None


def build_match_rule(group: ClassificationGroup) -> str:
    direction = infer_amount_direction(group)
    conditions = [
        f"{HUMAN_FIELD_LABELS.get(field, field)}={value}"
        for field, value in group.normalized_fields.items()
    ]
    if not conditions:
        return direction
    return f"{direction}；" + "；".join(conditions)


def infer_amount_direction(group: ClassificationGroup) -> str:
    has_income = group.in_amount > 0
    has_expense = group.out_amount > 0
    if has_income and has_expense:
        return "收支"
    if has_expense:
        return "支出"
    if has_income:
        return "收入"
    return "无金额"


def build_original_record_summary(group: ClassificationGroup) -> str:
    parts = [
        f"行数: {group.count}",
        f"收入: {format_amount(group.in_amount)}",
        f"支出: {format_amount(group.out_amount)}",
        f"原因: {', '.join(group.assessment_reasons)}",
    ]
    if group.existing_rule_match is not None:
        parts.append(f"已命中规则: {group.existing_rule_match.rule.id}")
        if group.existing_rule_match.rule.expense_type_id is not None:
            parts.append(f"expense_type_id={group.existing_rule_match.rule.expense_type_id}")
    else:
        parts.append("新增候选")
    if group.ids:
        parts.append(f"样例ID: {', '.join(group.ids)}")
    for field, examples in group.examples.items():
        if examples:
            parts.append(f"{HUMAN_FIELD_LABELS.get(field, field)}样例: {' / '.join(examples)}")
    return "；".join(parts)


def infer_order_extract_source(group: ClassificationGroup) -> str:
    order_fields = [
        field
        for field in group.normalized_fields
        if "order" in field.lower() or field.lower() in {"tid", "oid"}
    ]
    if order_fields:
        return "、".join(order_fields)
    return "{订单号提取处}"


def lookup_group_value(group: ClassificationGroup, fields: list[str]) -> str:
    for field in fields:
        value = group.normalized_fields.get(field)
        if value:
            return value
    for field in fields:
        canonical = canonical_field_name(field)
        for group_field, value in group.normalized_fields.items():
            if canonical_field_name(group_field) == canonical and value:
                return value
    return ""


def escape_markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def load_existing_rule_context(
    input_path: Path,
    *,
    rails_root: Path | None,
    fetch_jobs_path: Path | None,
) -> ExistingRuleContext | None:
    job = find_fetch_job_for_input(input_path, fetch_jobs_path or Path("fetch_jobs.json"))
    if job is None:
        return None
    platform = str(job.get("platform", "")).lower()
    source_type = str(job.get("source_type", ""))
    if not platform or not source_type:
        return None

    root = rails_root or DEFAULT_RAILS_ROOT
    seed_path = root / "db" / "seeds" / "static" / platform / "account_expense_type.seeds.rb"
    if not seed_path.exists():
        return None

    content = seed_path.read_text(encoding="utf-8")
    rules = [rule for rule in load_seed_rules(root, platform) if rule.status == 1]
    expense_types = parse_account_expense_types(content)
    return ExistingRuleContext(
        platform=platform,
        source_type=source_type,
        rules=rules,
        expense_types=expense_types,
    )


def find_fetch_job_for_input(input_path: Path, fetch_jobs_path: Path) -> dict[str, Any] | None:
    if not fetch_jobs_path.exists():
        return None
    data = json.loads(fetch_jobs_path.read_text(encoding="utf-8"))
    jobs = data.get("jobs", {}) if isinstance(data, dict) else {}
    if not isinstance(jobs, dict):
        return None

    target = input_path.resolve()
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        output = job.get("output")
        if not output:
            continue
        output_path = Path(str(output))
        candidates = [output_path]
        if not output_path.is_absolute():
            candidates.append((fetch_jobs_path.parent / output_path))
            candidates.append(Path.cwd() / output_path)
        if any(candidate.resolve() == target for candidate in candidates):
            return job
    return None


def attach_existing_rule_matches(
    groups: list[ClassificationGroup],
    rule_context: ExistingRuleContext,
) -> list[ClassificationGroup]:
    return [
        ClassificationGroup(
            count=group.count,
            normalized_fields=group.normalized_fields,
            examples=group.examples,
            ids=group.ids,
            in_amount=group.in_amount,
            out_amount=group.out_amount,
            classification_required=group.classification_required,
            platform_fee_candidate=group.platform_fee_candidate,
            assessment_reasons=group.assessment_reasons,
            existing_rule_match=find_existing_rule_match(group, rule_context),
        )
        for group in groups
    ]


def find_existing_rule_match(
    group: ClassificationGroup,
    rule_context: ExistingRuleContext,
) -> ExistingRuleMatch | None:
    representative_row = build_representative_row(group)
    matches = [
        rule
        for rule in rule_context.rules
        if rule.matches(representative_row, rule_context.source_type)
    ]
    if not matches:
        return None
    rule = sorted(matches, key=lambda item: (item.sort_order, item.id))[0]
    expense_type = rule_context.expense_types.get(rule.expense_type_id) if rule.expense_type_id is not None else None
    return ExistingRuleMatch(rule=rule, expense_type=expense_type)


def build_representative_row(group: ClassificationGroup) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for field, value in group.normalized_fields.items():
        add_row_field_aliases(row, field, value)
    for field, examples in group.examples.items():
        if examples:
            add_row_field_aliases(row, field, examples[0])
    row["amount_in"] = group.in_amount > 0
    row["in_amount"] = format_amount(group.in_amount)
    row["out_amount"] = format_amount(group.out_amount)
    return row


def add_row_field_aliases(row: dict[str, Any], field: str, value: Any) -> None:
    row[field] = value
    snake = camel_to_snake(field)
    row[snake] = value
    for canonical, aliases in FIELD_ALIASES.items():
        if field == canonical or field in aliases or snake in aliases:
            for alias in aliases:
                row[alias] = value


def camel_to_snake(value: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


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
    parser.add_argument("--rails-root", type=Path, help="Path to plutus-rails for existing rule naming. Defaults to the analyzer default.")
    parser.add_argument("--fetch-jobs", type=Path, default=Path("fetch_jobs.json"), help="fetch_jobs.json path for source_type lookup. Default: fetch_jobs.json.")
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
            rails_root=args.rails_root,
            fetch_jobs_path=args.fetch_jobs,
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
