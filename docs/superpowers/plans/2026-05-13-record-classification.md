# Record Classification Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic command that groups similar bill records from one check-result JSON file.

**Architecture:** Keep this separate from `bill_rule_analyzer.py` seed matching. Reuse `load_check_result_rows()` for input parsing, then normalize selected descriptive fields into stable grouping keys and render a Markdown report.

**Tech Stack:** Python standard library, existing unittest/pytest test style.

---

### Task 1: Classification Behavior

**Files:**
- Create: `classify_records.py`
- Test: `tests/test_classify_records.py`

- [ ] Write failing tests for grouping memo values that differ only by long IDs or numeric parentheses.
- [ ] Write failing tests for keeping different descriptions separate.
- [ ] Write failing tests for empty check-result inputs.
- [ ] Implement field alias lookup, text normalization, grouping, amount summary, and Markdown rendering.
- [ ] Run focused tests.

### Task 2: CLI and Docs

**Files:**
- Modify: `README.md`
- Test: `tests/test_classify_records.py`

- [ ] Add a CLI test that writes a report from a temporary JSON file.
- [ ] Implement `--input`, optional `--output`, `--fields`, `--sample-size`, and stdout behavior.
- [ ] Document usage in README.
- [ ] Run full relevant tests.
