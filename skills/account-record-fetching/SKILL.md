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

输出：`inputs/<platform>/..._check_result.json`

## 验证

```bash
python3 -m unittest tests/test_fetch_account_records.py tests/test_account_record_fetcher.py -v
```
