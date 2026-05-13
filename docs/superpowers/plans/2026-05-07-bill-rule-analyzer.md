# Bill Rule Analyzer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local tool that reads unmatched bill rows and existing Rails seed rules, then reports existing matches and candidate `AccountRecordType` snippets.

**Architecture:** A single Python CLI parses `db/seeds/static/<platform>/account_expense_type.seeds.rb` without booting Rails, loads exported unmatched rows, applies Rails-like match rules, and prints a Markdown report. The tool avoids project-specific dependencies so it can run from `account_check` before SQL files are ready.

**Tech Stack:** Python 3.10 standard library, `unittest`, local Rails seed files.

---

### Task 1: Parser And Matcher

**Files:**
- Create: `bill_rule_analyzer.py`
- Test: `tests/test_bill_rule_analyzer.py`

- [ ] **Step 1: Write failing tests**
  - Cover Ruby seed entry parsing for `match_rule`, `extract_rule`, `source_type`, `status`.
  - Cover Rails-style matching with uppercase rule keys and regex values.

- [ ] **Step 2: Run tests and verify failure**
  - Run: `python3 -m unittest tests/test_bill_rule_analyzer.py -v`
  - Expected: FAIL because `bill_rule_analyzer` does not exist.

- [ ] **Step 3: Implement parser and matcher**
  - Parse top-level `id => { ... }` entries from AccountRecordType blocks.
  - Convert Ruby symbols, strings, integers, booleans, and nested hashes into Python values.
  - Match rows by source type and all rule fields.

- [ ] **Step 4: Run tests and verify pass**
  - Run: `python3 -m unittest tests/test_bill_rule_analyzer.py -v`
  - Expected: PASS.

### Task 2: Input And Report CLI

**Files:**
- Modify: `bill_rule_analyzer.py`
- Test: `tests/test_bill_rule_analyzer.py`
- Create: `README.md`

- [ ] **Step 1: Write failing tests**
  - Cover CSV loading.
  - Cover SQL `INSERT INTO table (...) VALUES (...)` loading.
  - Cover Markdown report with unmatched group and snippet skeleton.

- [ ] **Step 2: Run tests and verify failure**
  - Run: `python3 -m unittest tests/test_bill_rule_analyzer.py -v`
  - Expected: FAIL for missing loaders/reporting.

- [ ] **Step 3: Implement loaders and report generation**
  - Support `--format csv|tsv|jsonl|sql`.
  - Generate grouped unmatched rows and `TODO` seed snippets.
  - Add source-type defaults for common platforms.

- [ ] **Step 4: Run tests and verify pass**
  - Run: `python3 -m unittest tests/test_bill_rule_analyzer.py -v`
  - Expected: PASS.

### Task 3: Manual Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Run unit tests**
  - Run: `python3 -m unittest tests/test_bill_rule_analyzer.py -v`

- [ ] **Step 2: Run CLI help**
  - Run: `python3 bill_rule_analyzer.py --help`

- [ ] **Step 3: Run against a tiny sample**
  - Run with an inline or temporary CSV sample for `dou` and `DOU_INSURANCE_BILL`.

