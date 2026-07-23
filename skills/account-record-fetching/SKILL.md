---
name: account-record-fetching
description: 用于在 account_check 项目中拉取或刷新平台账单检查结果 JSON、更新 inputs、执行 fetch_jobs.json 中的任务。
---

# 账单检查结果拉取

适用目录：`/Users/wangqing/PycharmProjects/account_check`

## 先看

- `fetch_jobs.json`：job、平台别名、输出路径
- `.env`：本地 token，不要打印或提交

## 常用命令

```bash
python3 fetch_account_records.py taobao
python3 fetch_account_records.py dou_shop_account_item
python3 fetch_account_records.py --all
```

覆盖时间：

```bash
python3 fetch_account_records.py dou_shop_account_item \
  --start-time "2026-05-01 00:00:00" \
  --end-time "2026-05-13 23:59:59"
```

默认输出：`inputs/<中文平台（YYYYMMDD至YYYYMMDD）>/<中文平台>-<账单类型>-<SOURCE_TYPE>.json`

示例：`inputs/淘宝（20260503至20260517）/淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json`

长时间范围的切片原始数据保存在 `inputs/slices/<中文平台（YYYYMMDD至YYYYMMDD）>/`，合并结果仍保存在 `inputs/` 下的平台时间目录。

平台目录里的时间范围来自 `start_time` / `end_time`。显式传 `--output` 时使用调用方给定路径。

## 分页行为

- 默认抓取所有页。
- 先抓完外层商家列表页，即合并所有 `data.content[]`。
- 再按每个商家的 `pagedRecords.totalPage` / `total` 抓完该商家的账单明细页。
- `--single-page` 只用于接口调试，不用于刷新完整 inputs。

## 验证

```bash
python3 -m unittest tests/test_fetch_account_records.py tests/test_account_record_fetcher.py -v
```
