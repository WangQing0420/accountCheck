---
name: account-record-classification
description: 用于在 account_check 项目中对单个账单检查结果 JSON 做相似归类、平台费用候选拆分、按 templates 生成 outputs 报告。
---

# 账单检查结果归类

适用目录：`/Users/wangqing/PycharmProjects/account_check`

## 常用命令

```bash
python3 classify_records.py inputs/taobao/taobao_check_result.json --split
```

输出：

```text
outputs/<platform>/<bill_json_stem>/
  all.md
  classification_required_platform_fee.md
  classification_required_non_platform_fee.md
  no_classification_non_platform_fee.md
```

## 输出格式

`--split` 输出由 `classify_records.py` 决定：

- `classification_required_platform_fee.md`：优先套用 `templates/平台费用检查-<平台>-<账单>-平台费用模板.md`。
- `classification_required_non_platform_fee.md`：优先套用 `账单归类模板`，没有时可用 `资金分析模板`。
- `all.md` 和 `no_classification_non_platform_fee.md`：保持分组报告格式。
- 模板匹配必须有明确平台和账单类型线索；没有可靠模板时回退普通分组报告，避免误套模板。

模板表格行填充约定：

- 输出分两类：
  - 兼容已有规则：如果分组样例命中 Rails seeds 中现有 `AccountRecordType`，复用既有命名。
  - 新增候选：未命中已有规则时，保留人工判断占位符，并在原始记录说明中标记 `新增候选`。
- 兼容已有规则时：
  - `账单归类名称` / `名称`：使用 `AccountRecordType.name`。
  - `平台费用名称`：使用 `expense_type_id` 对应的 `AccountExpenseType.name`。
  - `科目`：使用该 `AccountExpenseType` 的父级科目名称。
  - `原始记录` / `原始记录和业务调研`：标记 `已命中规则: <rule_id>` 和 `expense_type_id=<id>`。
- 新增候选时：
  - `账单归类名称` / `名称`：用分组主要描述字段生成可读候选名称，不直接使用带订单号占位的公共字符串。
  - 候选名称应去掉 `(*)`、`（*）`、`订单号［*]`、`订单号:*`、`运单号:*`、长流水占位、纯动作尾巴等，只保留核心业务语义。
  - `平台费用名称`、`科目`、`费用说明`、`账单来源` 等需要人工判断的列保留占位符。
- `匹配规则`：包含收支方向和归一化匹配字段。
- `原始记录` / `原始记录和业务调研`：包含行数、收入/支出合计、判断原因、样例 ID、字段样例。

## 规则位置

以 `classify_records.py` 为准：

- `NON_DESCRIPTIVE_FIELDS`
- `NON_PLATFORM_FEE_RULES`
- `PLATFORM_TEMPLATE_LABELS`
- `TEMPLATE_BILL_NAME_HINTS`
- `assess_group()`
- `select_template_path()`
- `load_existing_rule_context()`
- `attach_existing_rule_matches()`
- `render_template_group_report()`

已有规则来源：

- `fetch_jobs.json`：按 input path 找到 `platform` 和 `source_type`。
- Rails seeds：默认读取 `/Users/wangqing/workspace/plutus-rails/db/seeds/static/<platform>/account_expense_type.seeds.rb`。
- 可用 `--rails-root` 和 `--fetch-jobs` 覆盖。

## 验证

```bash
python3 -m unittest tests/test_classify_records.py -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_classify_records.py -q
```
