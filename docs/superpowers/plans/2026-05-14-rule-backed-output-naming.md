# Rule Backed Output Naming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill compatible output rows with existing Rails rule names, platform fee names, and subjects while leaving new candidates as placeholders.

**Architecture:** Reuse `bill_rule_analyzer.py` to parse Rails `AccountRecordType` and add an `AccountExpenseType` index for `expense_type_id`. Extend `classify_records.py` split rendering to optionally load rule context from `fetch_jobs.json` and Rails seeds, match representative group examples against active rules, and resolve template placeholders from matched metadata.

**Tech Stack:** Python standard library, existing Markdown renderer, existing unittest/pytest suites.

---

### Task 1: Parse Expense Type Names

**Files:**
- Modify: `bill_rule_analyzer.py`
- Test: `tests/test_bill_rule_analyzer.py`

- [ ] Write failing tests for parsing child expense names and parent subject names from `account_expense_types`.
- [ ] Implement a small parser/index using existing Ruby literal parsing helpers where possible.
- [ ] Verify `python3 -m unittest tests/test_bill_rule_analyzer.py -v`.

### Task 2: Match Classification Groups To Existing Rules

**Files:**
- Modify: `classify_records.py`
- Test: `tests/test_classify_records.py`

- [ ] Write failing tests where a split report gets `账单归类名称`, `平台费用名称`, and `科目` from matched Rails rules.
- [ ] Add optional rule context loading from `fetch_jobs.json` and Rails seeds.
- [ ] Match group examples against active rules using source type inferred from fetch job output path.
- [ ] Fill matched rows with rule metadata; leave unmatched new candidates as placeholders and mark them as `新增候选`.

### Task 3: Regenerate And Verify Outputs

**Files:**
- Modify: `outputs/**`
- Test: full test suite

- [ ] Regenerate reports with `for f in inputs/*/*.json; do python3 classify_records.py "$f" --split; done`.
- [ ] Run `python3 -m unittest discover tests -v`.
- [ ] Run `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q`.
