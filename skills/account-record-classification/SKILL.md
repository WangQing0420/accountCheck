---
name: account-record-classification
description: 用于在 account_check 项目中对单个账单检查结果 JSON 做相似分组，并生成普通分组报告。
---

# 账单检查结果相似分组

适用目录：`/Users/wangqing/PycharmProjects/account_check`

## 常用命令

```bash
python3 classify_records.py inputs/淘宝（20260503至20260517）/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json \
  --output outputs/淘宝（20260503至20260517）/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.md
```

也可以跑一个平台下所有 JSON：

```bash
python3 classify_records.py 淘宝
python3 classify_records.py taobao
python3 classify_records.py inputs/淘宝（20260503至20260517）
```

不传 `--output` 且输入是单个 JSON 时报告输出到 stdout。`--output` 只适用于单个 JSON；跑平台或目录时会自动写入 `outputs/<平台或带时间范围的平台>/<bill_json_stem>.md`。
平台名和平台别名会兼容带时间范围的 inputs 目录，例如 `inputs/淘宝（...）`。

## 输出格式

`classify_records.py` 只生成普通相似分组报告。

报告包含：

- 输入文件、输入行数、分组数量。
- 每个分组的行数。
- 收入合计、支出合计。
- 归一化后的分组字段。
- 每个分组最多 3 个字段原始样例。
- 每个分组最多 3 个样例 ID。

默认分组字段包括 `memo`、`bizDesc`、`businessType`、`bizType`、`bizTypeDesc`、`remark`、`feeName`、`accountBillDesc` 等，并兼容 `biz_desc`、`business_type` 这类 snake_case 字段。

分组前会把长订单号、长流水号和括号内长数字归一化为 `*`，例如 `生活费(1234567890123456)` 和 `生活费(2234567890123456)` 会归到同一组。

## 规则位置

以 `classify_records.py` 为准：

- `DEFAULT_GROUP_FIELDS`
- `FIELD_ALIASES`
- `classify_rows()`
- `build_group_fields()`
- `normalize_text()`
- `render_group_report()`

## 验证

```bash
python3 -m unittest tests/test_classify_records.py -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_classify_records.py -q
```
