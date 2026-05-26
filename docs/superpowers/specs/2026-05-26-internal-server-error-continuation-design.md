# Internal Server Error Continuation During Bill Fetching

## Goal

When a bill fetch job fails because the remote platform returns an internal
server error, batch fetching must attempt every remaining bill job. A failure
for one bill type must not prevent another bill type for the same platform, or
a later platform, from being fetched.

## Scope

- Apply continuation behavior to batch execution paths:
  `fetch_account_records.py --all` and `run_fetch.py`.
- Keep single-job execution behavior unchanged: an internal server error for a
  requested job remains an error.
- Treat the bill job, not the platform, as the unit of failure.
- Do not convert failed requests into empty successful JSON output.

## Error Classification

An internal server error is a `JsonApiError` identifying an HTTP/API status
`500` or a server-error response message such as `Internal Server Error`.
During batch execution, this class of error is non-fatal for the batch and is
recorded against the current job.

Fatal errors continue to stop execution immediately. These include
authentication/authorization failures, invalid token responses, invalid
configuration, and invalid time-range/argument errors. The existing
authentication protections in `run_fetch.py` remain in place.

Errors outside this targeted server-error behavior retain their existing
semantics unless already treated as resumable by `run_fetch.py`.

## Components And Data Flow

### `fetch_account_records.py --all`

The basic batch runner currently stops when `run_fetch_job()` raises. It will
catch internal-server-error failures per job, append a failure record, emit a
progress message, and continue iterating through configured jobs in order.

Because a successful-results-only list cannot accurately represent a partially
failed run, the batch result will expose both written results and failed jobs.
The CLI prints written outputs and a concise failure summary after all jobs
have been attempted. It returns a non-zero status when any bill job failed,
while still fulfilling the requirement to continue fetching.

### `run_fetch.py`

The resumable runner already records non-fatal failures and continues, but its
fatal-error classifier currently treats a non-partial `JsonApiError`, including
an internal server error, as fatal. The classifier will explicitly classify
internal server errors as non-fatal before the existing fallback rule. The
existing status JSON and end-of-run summary will therefore record the failed
bill job while later jobs continue.

### Individual Fetching

`AccountRecordFetcher` will continue to raise `JsonApiError` for an internal
server response. No successful output JSON is written for the failed bill
job. This preserves the distinction between "no records" and "fetch failed".

## Logging And Output

- A failed bill task logs its job name and server error.
- Successful later tasks write their normal JSON outputs.
- `run_fetch.py` persists server-error failures in its existing status file.
- The basic `--all` command reports failed jobs at completion and signals a
  partial batch failure using its exit status.

## Testing

Add tests that first reproduce the current premature termination:

- `fetch_account_records.py` batch execution continues after one internal
  server error and invokes the next bill job, including another bill type on
  the same platform.
- Its CLI reports the completed writes and failure, and completes with a
  failure exit status only after attempting the remaining jobs.
- `run_fetch.py` records a `JsonApiError` representing `Internal Server Error`
  as a job failure and continues to a later job.
- Existing tests continue proving authentication errors stop immediately and
  single fetch calls raise API server errors.

Only after these tests fail for the expected current behavior will the batch
classification and reporting code be changed.
