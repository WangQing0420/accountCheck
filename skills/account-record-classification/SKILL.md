---
name: account-record-classification
description: 用于在 account_check 项目中对单个账单检查结果 JSON 做相似归类、平台费用候选拆分，并生成 outputs 报告。
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

## 规则位置

以 `classify_records.py` 为准：

- `NON_DESCRIPTIVE_FIELDS`
- `NON_PLATFORM_FEE_RULES`
- `assess_group()`

## 验证

```bash
python3 -m unittest tests/test_classify_records.py -v
```
