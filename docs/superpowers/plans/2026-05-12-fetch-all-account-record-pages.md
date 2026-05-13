# Fetch All Account Record Pages Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch every page of account-record check results by default.

**Architecture:** Keep `fetch_check_all_user` as the single-page primitive and add a plural `fetch_check_all_users` method that loops through pages and merges `data.content`. CLI entry points use the plural method unless `--single-page` is passed.

**Tech Stack:** Python standard library (`argparse`, `copy`, `unittest`).

---

### Task 1: Fetcher Pagination

**Files:**
- Modify: `account_record_fetcher.py`
- Test: `tests/test_account_record_fetcher.py`

- [ ] Write a failing test proving two paged API responses are merged into one JSON response.
- [ ] Run the targeted fetcher test and confirm it fails because the plural method does not exist.
- [ ] Add `fetch_check_all_users` and `--single-page`.
- [ ] Run the targeted fetcher test and confirm it passes.

### Task 2: Workflow And Docs

**Files:**
- Modify: `account_record_workflow.py`
- Modify: `README.md`
- Test: `tests/test_account_record_workflow.py`

- [ ] Write a failing workflow test proving the workflow calls the all-pages fetch method.
- [ ] Update workflow CLI and fake fetcher support.
- [ ] Update README to describe default all-page behavior and `--single-page`.
- [ ] Run full unit tests and CLI help checks.
