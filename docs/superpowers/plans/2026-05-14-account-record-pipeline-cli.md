# Account Record Pipeline CLI Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single Python CLI that fetches account-record check results into `inputs/` and then batch-generates split classification reports under `outputs/` for the same run.

**Architecture:** Keep the fetch and classify engines unchanged. Introduce a thin orchestration module that reuses `fetch_account_records.py` for job resolution and data fetch, then reuses `classify_records.py` to generate split reports for every fetched input file. Surface per-job success/failure in the CLI exit code and printed summary.

**Tech Stack:** Python standard library, existing fetch/classify modules, existing unittest suite.

---

### Task 1: Define the Pipeline Contract

**Files:**
- Create: `account_record_pipeline.py`
- Test: `tests/test_account_record_pipeline.py`

- [ ] **Step 1: Write failing tests for job selection and end-to-end orchestration**

```python
def test_pipeline_runs_fetch_then_classify_for_all_jobs():
    ...
```

- [ ] **Step 2: Run the new tests to confirm they fail**

Run: `python3 -m unittest tests/test_account_record_pipeline.py -v`

Expected: `ImportError` or missing symbol failures before implementation.

- [ ] **Step 3: Implement the minimal orchestration helpers**

```python
def run_pipeline(...):
    ...
```

- [ ] **Step 4: Run the new tests again**

Run: `python3 -m unittest tests/test_account_record_pipeline.py -v`

Expected: PASS.

### Task 2: Wire the CLI and Document It

**Files:**
- Modify: `README.md`
- Modify: `account_record_pipeline.py`

- [ ] **Step 1: Add a CLI entrypoint and summary output**
- [ ] **Step 2: Document the new one-command workflow in README**
- [ ] **Step 3: Run the focused test suite**

Run:
`python3 -m unittest tests/test_account_record_pipeline.py tests/test_fetch_account_records.py tests/test_classify_records.py -v`

Expected: PASS.

### Task 3: Verify Whole-Repo Safety

**Files:**
- Modify: none

- [ ] **Step 1: Run repository test suite**

Run:
`python3 -m unittest discover tests -v`

Expected: PASS.

- [ ] **Step 2: Run pytest without third-party auto-load**

Run:
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests -q`

Expected: PASS.
