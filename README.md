# Account Check

本项目只做两件事：

- 从管理后台拉取账单检查结果，保存到 `inputs/`。
- 对已有 input JSON 做简单相似分组，生成 `outputs/` Markdown 报告。

`.env` 保存接口 token，不要打印或提交。

## 目录

```text
inputs/<中文平台>/<中文平台>-<账单类型>-<SOURCE_TYPE>.json
outputs/<中文平台>/<bill_json_stem>.md
fetch_jobs.json
```

## 拉取账单数据

推荐用 `fetch_account_records.py` 按 `fetch_jobs.json` 拉取。

拉取单个 job 或平台：

```bash
python3 fetch_account_records.py dou_shop_account_item
python3 fetch_account_records.py dou
```

拉取全部配置：

```bash
python3 fetch_account_records.py --all
```

可临时覆盖时间范围：

```bash
python3 fetch_account_records.py --all \
  --start-time "2026-05-01 00:00:00" \
  --end-time "2026-05-13 23:59:59"
```

只抓某个库：

```bash
python3 fetch_account_records.py dou --node-id 3
```

执行单个具体 job 时，可以临时覆盖输出路径：

```bash
python3 fetch_account_records.py dou_shop_account_item \
  --start-time "2026-05-01 00:00:00" \
  --end-time "2026-05-13 23:59:59" \
  --output inputs/抖店/抖店-资金流水账单-DOU_SHOP_ACCOUNT_ITEM-202605.json
```

`--output` 只用于单个具体 job；平台别名和 `--all` 会使用默认 inputs 命名规则输出。

分页行为：

- 默认会抓取所有页，不需要额外参数。
- 先按 `pageNumber` 抓完接口返回的商家列表页，也就是合并所有 `data.content[]`。
- 然后检查每个商家的 `pagedRecords.totalPage` / `total`，如果某个商家的账单明细超过 1 页，会用该商家的 `userId` 继续抓取后续 `pagedRecords` 页并合并到同一个商家下。
- `--single-page` 只抓 `--page-number` 指定页，用于调试接口返回，不适合刷新完整 inputs。

## 配置

`fetch_jobs.json` 里维护公共时间范围、分页参数和各平台账单任务：

```json
{
  "defaults": {
    "start_time": "2026-04-23 00:00:00",
    "end_time": "2026-05-07 23:59:59",
    "page_size": 50,
    "page_number": 1
  },
  "jobs": {
    "taobao": {
      "display_name": "淘宝支付宝",
      "platform": "TAOBAO",
      "data_type": "TAOBAO_ACCOUNT_RECORD",
      "source_type": "TAOBAO_ACCOUNT_RECORD",
      "node_ids": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
      "output": "inputs/淘宝/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json"
    }
  }
}
```

平台别名包括 `taobao`、`alibaba`、`pdd`、`kuaishou`、`jingdong`、`dou`、`xhs`、`wxxd`。

## Token

先创建 `.env`：

```bash
cp .env.example .env
```

然后填入：

```env
A6M1N_TOKEN=你的接口 token
A6M1N_BASE_URL=https://a6m1n.topkjs.com
```

`.env` 已加入 `.gitignore`。

## 简单分组

对单个 JSON 生成报告：

```bash
python3 classify_records.py inputs/淘宝/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json \
  --output outputs/淘宝/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.md
```

直接跑一个平台下所有 JSON：

```bash
python3 classify_records.py 淘宝
python3 classify_records.py taobao
python3 classify_records.py inputs/淘宝
```

生成路径示例：

```text
outputs/淘宝/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.md
```

不传 `--output` 且输入是单个 JSON 时，报告输出到 stdout。`--output` 只适用于单个 JSON；跑平台或目录时会自动写入 `outputs/<平台>/<bill_json_stem>.md`。

分组默认使用 `memo`、`bizDesc`、`businessType`、`bizType`、`bizTypeDesc`、`remark`、`feeName`、`accountBillDesc` 等字段，并兼容 `biz_desc`、`business_type` 这类 snake_case 字段。长订单号、长流水号和括号内长数字会归一化为 `*`，例如 `生活费(1234567890123456)` 和 `生活费(2234567890123456)` 会归到同一组。

报告包含：

- 每个分组的行数。
- `inAmount` / `outAmount` 合计。
- 归一化后的分组字段。
- 原始字段样例和样例 ID。

如果只想按指定字段分组，可以传 `--fields`：

```bash
python3 classify_records.py inputs/kuaishou/kuaishou_account_bill_check_result.json \
  --output outputs/kuaishou/kuaishou_account_bill_check_result.md \
  --fields memo,bizDesc,remark,bizTypeDesc
```

## 一键拉取并分组

如果要“拉取 inputs + 生成 outputs”一起跑：

```bash
python3 account_record_pipeline.py --all \
  --start-time "2026-05-01 00:00:00" \
  --end-time "2026-05-13 23:59:59"
```

也可以只跑单个 job 或平台别名：

```bash
python3 account_record_pipeline.py dou_shop_account_item
python3 account_record_pipeline.py dou
```

## 验证

```bash
python3 -m unittest discover tests -v
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q
```
