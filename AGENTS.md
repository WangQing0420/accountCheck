# AGENTS.md

项目目录：`/Users/wangqing/PycharmProjects/account_check`

## 目录

- 输入：`inputs/<中文平台>/<中文平台>-<账单类型>-<SOURCE_TYPE>.json`
- 输出：`outputs/<中文平台>/<bill_json_stem>.md`
- 配置：`fetch_jobs.json`
- token：`.env`，不要打印或提交

## 项目内 Skill

- `skills/account-record-fetching/SKILL.md`：拉取账单检查结果
- `skills/account-record-classification/SKILL.md`：相似分组单个检查结果 JSON

匹配场景时先读对应 `SKILL.md`。

## 拉取

```bash
python3 fetch_account_records.py <job_or_platform>
python3 fetch_account_records.py --all
```

默认会抓取所有分页：先按 `data.content` 抓完所有商家列表页，再按每个商家的 `pagedRecords.totalPage` / `total` 继续抓完该商家的账单明细页。`--single-page` 只用于调试单页。

## 分组

```bash
python3 classify_records.py inputs/淘宝/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json --output outputs/淘宝/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.md
python3 classify_records.py 淘宝
python3 classify_records.py taobao
python3 classify_records.py inputs/淘宝
```

传平台名或平台目录时会处理该平台下所有 JSON，并自动生成：

```text
outputs/<中文平台>/<bill_json_stem>.md
```

### outputs 展示格式

- `classify_records.py` 只生成普通相似分组报告。
- 报告包含输入文件、输入行数、分组数量、每组行数、收入/支出合计、归一化字段、字段样例和样例 ID。
- 分组前会把长订单号、长流水号归一化为 `*`。

## 规则

相似分组以 `classify_records.py` 为准：

- `DEFAULT_GROUP_FIELDS`
- `FIELD_ALIASES`
- `classify_rows()`
- `build_group_fields()`
- `normalize_text()`
- `render_group_report()`

## 验证

```bash
python3 -m unittest discover tests -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
```
