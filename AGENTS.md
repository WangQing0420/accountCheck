# AGENTS.md

项目目录：`/Users/wangqing/PycharmProjects/account_check`

## 目录

- 输入：`inputs/<platform>/`
- 输出：`outputs/<platform>/<bill_json_stem>/`
- 配置：`fetch_jobs.json`
- token：`.env`，不要打印或提交

## 项目内 Skill

- `skills/account-record-fetching/SKILL.md`：拉取账单检查结果
- `skills/account-record-classification/SKILL.md`：归类单个检查结果 JSON

匹配场景时先读对应 `SKILL.md`。

## 拉取

```bash
python3 fetch_account_records.py <job_or_platform>
python3 fetch_account_records.py --all
```

## 归类

```bash
python3 classify_records.py inputs/taobao/taobao_check_result.json --split
```

生成：

```text
outputs/<platform>/<bill_json_stem>/
  all.md
  classification_required_platform_fee.md
  classification_required_non_platform_fee.md
  no_classification_non_platform_fee.md
```

### outputs 展示格式

生成 `outputs` 时按 `templates/` 的模板展示检查结果：

- `classification_required_platform_fee.md`：能匹配时套用对应平台/账单的 `平台费用模板`。
- `classification_required_non_platform_fee.md`：能匹配时套用对应平台/账单的 `账单归类模板`；没有账单归类模板时可用 `资金分析模板`。
- `all.md`、`no_classification_non_platform_fee.md`：继续使用普通分组报告。
- 只有在平台和账单类型都有明确线索时才套模板；无法可靠匹配模板时回退普通分组报告，不能猜测套错模板。
- 输出分两类：
  - 兼容已有规则：分组样例命中 Rails seeds 中已有 `AccountRecordType` 时，复用 `AccountRecordType.name` 作为账单归类名称；通过 `expense_type_id` 关联 `AccountExpenseType.name` 作为平台费用名称，并使用其父级名称作为科目。
  - 新增候选：未命中已有规则时，账单归类名称要生成成可读名称，不能直接使用带 `(*)`、`（*）`、`订单号［*]`、`订单号:*`、`运单号:*` 等占位的公共字符串；`平台费用名称`、`科目`、`费用说明`、`账单来源` 等人工判断字段保留占位符，并在原始记录说明中标记 `新增候选`。
- `原始记录` / `原始记录和业务调研` 应包含行数、收入/支出合计、判断原因、样例 ID 和字段样例；命中已有规则时还要包含 `已命中规则: <rule_id>` 和 `expense_type_id=<id>`。
- 已有规则来源于 `fetch_jobs.json` 反推的 `platform/source_type` 和 Rails seeds；默认 Rails 根目录是 `/Users/wangqing/workspace/plutus-rails`，需要时用 `--rails-root` 覆盖。

## 规则

归类和平台费用判断以 `classify_records.py` 为准：

- `NON_DESCRIPTIVE_FIELDS`
- `NON_PLATFORM_FEE_RULES`
- `PLATFORM_TEMPLATE_LABELS`
- `TEMPLATE_BILL_NAME_HINTS`
- `assess_group()`
- `select_template_path()`
- `load_existing_rule_context()`
- `attach_existing_rule_matches()`
- `render_template_group_report()`

## 验证

```bash
python3 -m unittest discover tests -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
```
