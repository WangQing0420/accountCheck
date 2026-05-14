# Platform Bill Rule Analyzer

本工具用于分析后台账单检查结果 JSON 中的账单明细，对照 Rails seeds 中已有 `AccountRecordType` 规则，输出：

- 已能命中的现有规则。
- 仍未命中的分组。
- 可复制到对应 `account_expense_type.seeds.rb` 的候选规则片段。

## 使用方式

```bash
python3 bill_rule_analyzer.py \
  --platform dou \
  --source-type DOU_INSURANCE_BILL \
  --input taobao_check_result.json \
  --output report.md
```

默认读取 Rails 项目：

```text
/Users/wangqing/workspace/plutus-rails
```

可用 `--rails-root` 覆盖。

## 输入格式

输入文件应为 `account_record_check_result` 接口返回的 JSON，脚本会自动展开：

```text
data.content[].pagedRecords.content[]
```

也就是每个用户分组里的账单明细行。

## 常用 source_type

- `DOU_INSURANCE_BILL`: 抖店保险费明细，常用匹配字段 `insurance_product`
- `DOU_SHOP_ACCOUNT_ITEM`: 抖店资金流水明细，常用匹配字段 `account_bill_desc`
- `JINGDONG_LEDGER_BILL_DETAIL`: 京东商家账单明细，常用匹配字段 `fee_name`、`remark`
- `TAOBAO_ACCOUNT_RECORD`: 淘宝支付宝账单，常用匹配字段 `memo`、`business_type`
- `PDD_MALL_ACCOUNT_RECORD`: 拼多多货款账单，常用匹配字段 `memo`、`business_type`

## 结果说明

候选片段中的 `TODO_ID`、`name: 'TODO'`、`expense_type_id: TODO`、`sort_order: TODO` 需要人工按业务科目确认后再落到对应平台 seeds 文件。工具只根据未归类样本给出匹配条件建议，不替你决定费用科目。

## 校验

```bash
python3 -m unittest tests/test_bill_rule_analyzer.py -v
python3 bill_rule_analyzer.py --help
```

## 单个 JSON 记录相似归类

`classify_records.py` 用于把一个账单检查结果 JSON 内的记录按相似描述归类。它不读取 Rails seeds，也不会修改原始 JSON；适合先观察 `memo`、`bizDesc`、`remark` 等字段里有哪些可合并的账单场景。

```bash
python3 classify_records.py inputs/taobao/taobao_check_result.json --split
```

`--split` 会按平台和账单文件名生成 4 份报告：

- `outputs/taobao/taobao_check_result/all.md`
- `outputs/taobao/taobao_check_result/classification_required_platform_fee.md`
- `outputs/taobao/taobao_check_result/classification_required_non_platform_fee.md`
- `outputs/taobao/taobao_check_result/no_classification_non_platform_fee.md`

默认会使用常见描述字段生成分组，包括 `memo`、`bizDesc`、`businessType`、`bizType`、`bizTypeDesc`、`remark`、`feeName`、`accountBillDesc` 等，并兼容 `biz_desc`、`business_type` 这类 snake_case 字段。分组前会把长订单号、长流水号和括号内长数字归一化为 `*`，例如 `生活费(1234567890123456)` 和 `生活费(2234567890123456)` 会归到同一类。

输出报告包含：

- 每个分组的行数。
- `账单归类` 标记：该分组是否需要做账单归类。
- `平台费用` 标记：该分组是否可能进入平台费用统计。
- `判断原因`：例如默认保留待确认、缺少有效业务描述、货款/结算收入、充值/提现/资金往来等。
- `inAmount` / `outAmount` 合计。
- 归一化后的匹配字段。
- 原始字段样例和样例 ID。

两个标记是分开判断的：有些记录需要账单归类，但不应统计为平台费用，例如货款结算收入、充值提现、资金往来；有些记录如果只剩流水号或订单号，默认会标记为不需要账单归类，也不作为平台费用候选。

如果只想按指定字段归类，可以传 `--fields`：

```bash
python3 classify_records.py inputs/kuaishou/kuaishou_account_bill_check_result.json \
  --split \
  --fields memo,bizDesc,remark,bizTypeDesc
```

如果只需要一份报告，也可以继续使用 `--output`：

```bash
python3 classify_records.py inputs/taobao/taobao_check_result.json \
  --output outputs/taobao/taobao_check_result_all.md
```

## 从管理后台拉取账单检查结果

`account_record_fetcher.py` 可以从管理后台接口直接拉取账单检查结果。接口 token 放在本地 `.env`，脚本会直接把它作为 `Authorization: Bearer ...` 使用。

先创建 `.env`：

```bash
cp .env.example .env
```

然后填入：

```env
A6M1N_TOKEN=你的接口 token
A6M1N_BASE_URL=https://a6m1n.topkjs.com
```

拉取淘宝账单检查结果。默认会从 `--page-number` 开始循环拉取所有分页，并把所有用户分组合并写入同一个 JSON：

```bash
python3 account_record_fetcher.py \
  --platform TAOBAO \
  --data-type TAOBAO_ACCOUNT_RECORD \
  --start-time "2026-04-23 00:00:00" \
  --end-time "2026-05-07 23:59:59" \
  --output ./taobao_check_result.json
```

只拉取某一页用于调试：

```bash
python3 account_record_fetcher.py \
  --platform TAOBAO \
  --data-type TAOBAO_ACCOUNT_RECORD \
  --start-time "2026-04-23 00:00:00" \
  --end-time "2026-05-07 23:59:59" \
  --page-number 2 \
  --single-page \
  --output ./taobao_check_result_page_2.json
```

`.env` 已加入 `.gitignore`，不要提交真实 token。

### token 拉取并写入 inputs 的代码链路

推荐入口是 `fetch_account_records.py`，它把“按配置拉取并保存到 `inputs/`”封装成一个命令：

```text
fetch_account_records.py
  -> fetch_jobs.json
  -> account_record_fetcher.py
  -> .env
  -> /api/accountRecordCheckResult/checkAllUser
  -> inputs/<platform>/<job>_check_result.json
```

各文件职责：

- `fetch_account_records.py`：命令行入口。根据参数判断是执行单个 job、整个平台别名，还是 `--all` 全量执行；读取 job 配置，处理临时覆盖参数，创建输出目录，并把接口响应写入 `inputs/`。
- `fetch_jobs.json`：拉取任务配置。`defaults` 保存公共时间范围和分页参数，`jobs` 保存每种账单的 `platform`、`data_type`、`source_type`、`node_ids` 和 `output`。
- `account_record_fetcher.py`：底层接口客户端。读取 `.env` 里的 `A6M1N_TOKEN` 和 `A6M1N_BASE_URL`，组装 `Authorization: Bearer <token>`、`Platform` 等请求头，构造 `checkAllUser` 请求参数并发起 POST。
- `.env`：本地敏感配置，只保存 token 和后台地址，不提交到仓库。
- `inputs/`：接口原始 JSON 的落盘目录，后续 `bill_rule_analyzer.py` 会读取这些文件做规则分析。

运行时的详细逻辑：

1. 执行 `python3 fetch_account_records.py dou_shop_account_item`。
2. `fetch_account_records.py` 从 `fetch_jobs.json` 找到 `dou_shop_account_item`，合并 `defaults` 和该 job 的配置。
3. 如果命令行传了 `--start-time`、`--end-time`、`--node-id`、`--output` 等参数，会覆盖配置文件中的对应字段。
4. `load_settings()` 从 `.env` 读取 `A6M1N_TOKEN`，生成 `FetchSettings`。
5. `AccountRecordFetcher.fetch_check_all_users()` 按 `pageNumber` 循环调用接口，直到抓完所有分页；如果传了 `--single-page`，则只调用一次 `fetch_check_all_user()`。
6. job 配了多个 `node_ids` 时，`fetch_account_records.py` 会逐个 node 拉取，并把多个响应的 `data.content` 合并到同一个 JSON；合并后的用户分组会补 `nodeId`。
7. `write_output()` 将格式化后的 JSON 写入 `fetch_jobs.json` 里配置的 `output`，通常是 `inputs/<platform>/..._check_result.json`。

`account_record_workflow.py` 是另一条入口：它先复用 `account_record_fetcher.py` 拉取数据，再调用 `bill_rule_analyzer.py` 生成分析报告；只有传 `--raw-output inputs/...json` 时才会把原始接口响应保存下来。

### 一键拉取并分类

如果你希望把“从管理后台拉取账单检查记录 -> 写入 `inputs/` -> 批量生成 `outputs/` 分类报告”放到一个命令里跑，可以直接用：

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

这个入口会先复用 `fetch_account_records.py` 的 job 解析和拉取逻辑，把结果写到 `inputs/<platform>/...json`，再复用 `classify_records.py --split` 生成对应的 `outputs/<platform>/<bill_json_stem>/` 报告。最后它只做汇总和退出码，不替你做最后的归类决策。

## 使用配置文件拉取

常用拉取参数可以维护在 `fetch_jobs.json`，避免每次手写完整命令。公共时间范围和分页参数放在 `defaults`，每个平台或账单类型只维护自己的差异：

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
      "output": "inputs/taobao/taobao_check_result.json"
    }
  }
}
```

执行单个平台。平台别名包括 `taobao`、`alibaba`、`pdd`、`kuaishou`、`jingdong`、`dou`、`xhs`、`wxxd`：

```bash
python3 fetch_account_records.py dou
```

一次性拉取配置里的所有平台和账单类型：

```bash
python3 fetch_account_records.py --all
```

也可以统一覆盖全量拉取的时间范围：

```bash
python3 fetch_account_records.py --all \
  --start-time "2026-05-01 00:00:00" \
  --end-time "2026-05-13 23:59:59"
```

执行单个具体 job 时，使用 `fetch_jobs.json` 里的完整 job 名；如果名字和平台别名重名，命令行会优先按平台执行：

```bash
python3 fetch_account_records.py dou_shop_account_item
```

如果 job 配置了 `node_ids`，会逐个 node 拉取并合并到同一个 JSON；合并后的用户分组会带 `nodeId` 字段。当前配置中，拼多多抓 1-2 库，抖店抓 1-3 库，淘宝抓 1-10 库，其他平台默认只抓 1 库。只抓某一个库可以临时覆盖：

```bash
python3 fetch_account_records.py dou --node-id 3
```

临时覆盖时间或输出路径：

```bash
python3 fetch_account_records.py dou_shop_account_item \
  --start-time "2026-05-01 00:00:00" \
  --end-time "2026-05-13 23:59:59" \
  --output inputs/dou/dou_shop_account_item_check_result_202605.json
```

`--output` 只用于单个具体 job；平台别名和 `--all` 都会使用每个 job 自己配置的输出路径。

## 一键拉取并分析

如果你想一步完成取数和归类分析，直接用 `account_record_workflow.py`。它同样默认循环拉取所有分页：

```bash
python3 account_record_workflow.py \
  --platform TAOBAO \
  --source-type TAOBAO_ACCOUNT_RECORD \
  --data-type TAOBAO_ACCOUNT_RECORD \
  --start-time "2026-04-23 00:00:00" \
  --end-time "2026-05-07 23:59:59" \
  --raw-output ./taobao_check_result.json \
  --report-output ./taobao_report.md
```

`--raw-output` 是可选的；不传的话只输出报告。
