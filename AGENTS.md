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

## 规则

归类和平台费用判断以 `classify_records.py` 为准：

- `NON_DESCRIPTIVE_FIELDS`
- `NON_PLATFORM_FEE_RULES`
- `assess_group()`

## 验证

```bash
python3 -m unittest discover tests -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
```
