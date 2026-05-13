# 账单归类规则分析工具交接文档

## 背景

本项目用于分析管理后台账单检查结果 JSON 中的账单明细，对照 Rails seeds 中已有 `AccountRecordType` 规则，输出：

- 已能命中的现有规则。
- 仍未命中的分组。
- 可复制到对应 `account_expense_type.seeds.rb` 的候选规则片段。

Rails seeds 默认读取：

```text
/Users/wangqing/workspace/plutus-rails/db/seeds/static/<platform>/account_expense_type.seeds.rb
```

## 当前目录约定

输入文件放在本项目内：

```text
/Users/wangqing/PycharmProjects/account_check/inputs/<platform>/
```

已创建的平台目录：

```text
inputs/alibaba
inputs/dou
inputs/jingdong
inputs/kuaishou
inputs/pdd
inputs/taobao
inputs/wxxd
inputs/xhs
```

当前淘宝样例文件已移动到：

```text
inputs/taobao/taobao_check_result.json
```

## 已完成

### 1. 规则分析脚本

文件：

```text
bill_rule_analyzer.py
```

能力：

- 解析 Rails 平台 seeds 文件中的 `AccountRecordType` 规则。
- 支持大多数平台的 transaction hash 写法。
- 支持淘宝 `account_record_types = { ... }` 变量式写法。
- 按 Rails 逻辑模拟 `match_rule`、`extract_rule` key 大写、`source_type` 过滤和 `sort_order` 优先级。
- 使用正则完整匹配，避免短词误命中长内容。
- 读取后台 `account_record_check_result` 接口返回的 JSON，并自动展开：

```text
data.content[].pagedRecords.content[]
```

### 2. 后台接口拉取脚本

文件：

```text
account_record_fetcher.py
```

能力：

- 从管理后台接口 `/api/accountRecordCheckResult/checkAllUser` 拉取账单检查结果。
- `.env` 直接提供 token，不再使用账号密码登录。
- 默认从 `--page-number` 开始循环拉取所有分页。
- 合并每页响应中的 `data.content`，输出一个完整 JSON。
- `--single-page` 可只拉取指定页用于调试。

`.env` 格式：

```env
A6M1N_TOKEN=你的接口 token
A6M1N_BASE_URL=https://a6m1n.topkjs.com
```

### 3. 一键拉取并分析

文件：

```text
account_record_workflow.py
```

能力：

- 先调用 `account_record_fetcher.py` 拉取后台账单检查结果。
- 默认循环拉取所有分页。
- 再调用分析逻辑生成 Markdown 报告。
- 可选 `--raw-output` 保存原始 JSON。
- 可选 `--report-output` 保存分析报告。

### 4. 配置化拉取入口

文件：

```text
fetch_account_records.py
fetch_jobs.json
```

能力：

- 把常用拉取参数维护在 `fetch_jobs.json`。
- `start_time`、`end_time`、`page_size`、`page_number` 等公共参数放在 `defaults`，不用每个 job 重复修改。
- job 可配置 `node_ids`，脚本会逐个 node 拉取并合并；合并后的用户分组会带 `nodeId` 字段。
- 用任务名执行拉取，例如 `python3 fetch_account_records.py taobao`。
- 支持临时覆盖 `--start-time`、`--end-time`、`--output`、`--page-size` 等参数。
- 支持临时覆盖 `--node-id`，只抓指定单库。
- 默认仍然拉取所有分页；加 `--single-page` 时只拉指定页。

## 当前使用方式

### 只分析已有 JSON

```bash
python3 bill_rule_analyzer.py \
  --platform taobao \
  --source-type TAOBAO_ACCOUNT_RECORD \
  --input inputs/taobao/taobao_check_result.json \
  --output outputs/taobao_report.md
```

`--rails-root` 可覆盖默认 Rails 项目路径：

```bash
--rails-root /path/to/plutus-rails
```

### 从后台拉取完整 JSON

推荐使用配置化入口：

```bash
python3 fetch_account_records.py taobao
```

淘宝四个 job 当前配置了 `node_ids: [1..10]`，所以默认会抓 1-10 库并合并。只抓库三：

```bash
python3 fetch_account_records.py taobao --node-id 3
```

临时覆盖时间：

```bash
python3 fetch_account_records.py taobao \
  --start-time "2026-05-01 00:00:00" \
  --end-time "2026-05-13 23:59:59"
```

底层完整命令仍可直接执行：

```bash
python3 account_record_fetcher.py \
  --platform TAOBAO \
  --data-type TAOBAO_ACCOUNT_RECORD \
  --start-time "2026-04-23 00:00:00" \
  --end-time "2026-05-07 23:59:59" \
  --output inputs/taobao/taobao_check_result.json
```

只拉单页调试：

```bash
python3 account_record_fetcher.py \
  --platform TAOBAO \
  --data-type TAOBAO_ACCOUNT_RECORD \
  --start-time "2026-04-23 00:00:00" \
  --end-time "2026-05-07 23:59:59" \
  --page-number 2 \
  --single-page \
  --output inputs/taobao/taobao_check_result_page_2.json
```

### 一键拉取并分析

```bash
python3 account_record_workflow.py \
  --platform TAOBAO \
  --source-type TAOBAO_ACCOUNT_RECORD \
  --data-type TAOBAO_ACCOUNT_RECORD \
  --start-time "2026-04-23 00:00:00" \
  --end-time "2026-05-07 23:59:59" \
  --raw-output inputs/taobao/taobao_check_result.json \
  --report-output outputs/taobao_report.md
```

## 常用 source_type

| 平台 | source_type | 常用匹配字段 |
| --- | --- | --- |
| taobao | `TAOBAO_ACCOUNT_RECORD` | `memo`, `business_type`, `in_amount`, `type`, `merchant_order_no`, `biz_desc`, `biz_main_order_no` |
| taobao | `TB_WHALE_ACCOUNT_RECORD` | `memo`, `business_type`, `in_amount`, `biz_desc` |
| pdd | `PDD_MALL_ACCOUNT_RECORD` | `memo`, `business_type`, `in_amount`, `biz_desc` |
| pdd | `PDD_MARKETING_ACCOUNT_RECORD` | `memo`, `business_type`, `in_amount` |
| dou | `DOU_SHOP_ACCOUNT_ITEM` | `account_bill_desc`, `in_amount`, `memo`, `real_amount` |
| dou | `DOU_INSURANCE_BILL` | `insurance_product` |
| dou | `DOU_DEPOSIT_BILL` | `memo`, `in_amount`, `real_amount`, `operate_type` |
| jingdong | `JINGDONG_LEDGER_BILL_DETAIL` | `fee_name`, `remark`, `cost_item`, `settlement_memo` |
| jingdong | `JINGDONG_INSURANCE_BILL` | `duty` |
| kuaishou | `KUAISHOU_ACCOUNT_BILL` | `memo`, `biz_type`, `biz_desc`, `remark`, `in_amount` |
| alibaba | `ALIBABA_ALIPAY_ACCOUNT_RECORD` | `memo`, `biz_type`, `biz_desc`, `in_amount` |
| xhs | `XHS_SELLER_ACCOUNT_RECORD` | `remark`, `type_desc`, `business_no` |
| wxxd | `WXXD_FUNDS_FLOW_DETAIL` | `memo`, `detail`, `business_type`, `flow_id` |
| wxxd | `WXXD_DEPOSIT_BILL` | `memo`, `detail`, `business_type`, `bill_no` |

## 已验证

最近一次验证命令：

```bash
python3 -m unittest tests/test_account_record_fetcher.py tests/test_account_record_workflow.py tests/test_bill_rule_analyzer.py -v
```

结果：

```text
Ran 12 tests in 0.004s
OK
```

CLI help 也已验证：

```bash
python3 fetch_account_records.py --help
python3 account_record_fetcher.py --help
python3 account_record_workflow.py --help
python3 bill_rule_analyzer.py --help
```

## 注意事项

- `.env` 已加入 `.gitignore`，不要提交真实 token。
- token 过期时脚本不会自动登录刷新，需要人工更新 `A6M1N_TOKEN`。
- 常用拉取参数优先改 `fetch_jobs.json`；公共参数改 `defaults`，单个账单类型参数改对应 `jobs.<job_name>`。
- 工具不会替代人工判断 `expense_type_id`。
- 候选规则默认基于未命中字段值生成精确正则，可能偏保守。
- `status=0` 和 `status=-1` 的规则默认不参与匹配；需要时加 `--include-inactive`。
- 当前 `account_check` 目录不是 git 仓库，所以没有 commit 记录。

## 后续可做

- 增加 `outputs/<platform>/` 目录约定，统一保存分析报告。
- 支持批量 job 配置，一次拉取并分析多个平台/source_type。
- 增加候选规则与现有规则的冲突检测。
- 增加相似规则推荐，辅助判断 `expense_type_id` 和 `sort_order`。
- 增加候选 seeds patch 输出，但仍保留人工 review。
