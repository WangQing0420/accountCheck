# Account Record Fetcher Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small CLI that reads a local `.env` token and fetches account record check-result JSON.

**Architecture:** Keep this separate from `bill_rule_analyzer.py`. The fetcher owns admin API token authentication, request execution, and pretty JSON output. Tests use fake HTTP clients so no real credentials or network calls are required.

**Tech Stack:** Python standard library (`argparse`, `json`, `urllib`, `unittest`).

---

### Task 1: Fetcher Core

**Files:**
- Create: `account_record_fetcher.py`
- Test: `tests/test_account_record_fetcher.py`

- [ ] Write failing tests for `.env` parsing, token settings loading, token-authenticated requests, and expired-token errors.
- [ ] Run `python3 -m unittest tests/test_account_record_fetcher.py -v` and confirm failures.
- [ ] Implement the minimal fetcher code using dependency-injected HTTP client hooks for tests.
- [ ] Run the targeted tests and confirm pass.

### Task 2: CLI and Docs

**Files:**
- Create: `.env.example`
- Create/Modify: `.gitignore`
- Modify: `README.md`

- [ ] Add CLI arguments for platform, data type, time range, page size, page number, env path, and output path.
- [ ] Document `.env` keys and example command.
- [ ] Ensure `.env` is ignored and `.env.example` contains no secrets.
- [ ] Run full test suite and `python3 account_record_fetcher.py --help`.
