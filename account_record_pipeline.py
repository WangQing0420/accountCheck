#!/usr/bin/env python3
"""Fetch account record check results and generate grouping reports."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from account_record_fetcher import DEFAULT_ENV_PATH, JsonApiError
from classify_records import load_rows, render_report
from fetch_account_records import (
    DEFAULT_CONFIG_PATH,
    FetchJobError,
    load_fetch_jobs,
    platform_for_alias,
    run_fetch_job,
)


DEFAULT_OUTPUT_ROOT = Path("outputs")


@dataclass(frozen=True)
class PipelineJobResult:
    job_name: str
    input_path: Path
    output_paths: dict[str, Path]


@dataclass(frozen=True)
class PipelineJobFailure:
    job_name: str
    stage: str
    error: str


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch account-record check results and generate grouping reports."
    )
    parser.add_argument("job", nargs="?", help="Fetch job name or platform alias, e.g. dou.")
    parser.add_argument("--all", action="store_true", help="Fetch every job in the config file.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help=f"Fetch job config path. Default: {DEFAULT_CONFIG_PATH}.")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH, help=f"Path to .env file. Default: {DEFAULT_ENV_PATH}.")
    parser.add_argument("--start-time", help='Override job start time, e.g. "2026-05-01 00:00:00".')
    parser.add_argument("--end-time", help='Override job end time, e.g. "2026-05-13 23:59:59".')
    parser.add_argument("--page-size", type=int, help="Override page size.")
    parser.add_argument("--page-number", type=int, help="Override start page number.")
    parser.add_argument("--user-id-or-nick", help="Override optional user id or nick filter.")
    parser.add_argument("--node-id", type=int, help="Override node id.")
    parser.add_argument("--single-page", action="store_true", help="Fetch only --page-number instead of all pages.")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT, help=f"Root directory for grouping reports. Default: {DEFAULT_OUTPUT_ROOT}.")
    args = parser.parse_args(argv)
    if args.all and args.job:
        parser.error("provide either a job name or --all, not both")
    if not args.all and not args.job:
        parser.error("provide a job name or --all")
    return args


def resolve_target_job_names(job: str | None, *, all_jobs: bool, config_path: Path) -> list[str]:
    jobs = load_fetch_jobs(config_path)
    if all_jobs:
        target = list(jobs)
        if not target:
            raise FetchJobError("No fetch jobs configured")
        return target

    assert job is not None
    platform = platform_for_alias(job)
    if platform is not None:
        target = [name for name, config in jobs.items() if str(config.get("platform")) == platform]
        if not target:
            raise FetchJobError(f"No fetch jobs configured for platform {platform}")
        return target
    if job not in jobs:
        available = ", ".join(sorted(jobs)) or "(none)"
        raise FetchJobError(f"Unknown fetch job {job!r}. Available jobs: {available}")
    return [job]


def run_pipeline(
    *,
    job: str | None,
    all_jobs: bool,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    start_time: str | None = None,
    end_time: str | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    user_id_or_nick: str | None = None,
    node_id: int | None = None,
    single_page: bool = False,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    fetcher: Any | None = None,
) -> tuple[list[PipelineJobResult], list[PipelineJobFailure]]:
    results: list[PipelineJobResult] = []
    failures: list[PipelineJobFailure] = []
    target_job_names = resolve_target_job_names(job, all_jobs=all_jobs, config_path=config_path)

    for job_name in target_job_names:
        try:
            input_path, _ = run_fetch_job(
                job_name,
                config_path=config_path,
                env_path=env_path,
                fetcher=fetcher,
                start_time=start_time,
                end_time=end_time,
                page_size=page_size,
                page_number=page_number,
                user_id_or_nick=user_id_or_nick,
                node_id=node_id,
                single_page=single_page,
            )
        except (FetchJobError, JsonApiError, OSError, ValueError) as error:
            failures.append(PipelineJobFailure(job_name=job_name, stage="fetch", error=str(error)))
            continue

        try:
            rows = load_rows(input_path)
            report_path = infer_report_output_path(input_path, output_root)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(render_report(rows, source_name=str(input_path)), encoding="utf-8")
            output_paths = {"all": report_path}
        except (OSError, ValueError, json.JSONDecodeError) as error:
            failures.append(PipelineJobFailure(job_name=job_name, stage="classify", error=str(error)))
            continue

        results.append(PipelineJobResult(job_name=job_name, input_path=input_path, output_paths=output_paths))

    return results, failures


def infer_report_output_path(input_path: Path, output_root: Path) -> Path:
    platform = input_path.parent.name if input_path.parent.name else "unknown"
    return output_root / platform / f"{input_path.stem}.md"


def format_summary(results: list[PipelineJobResult], failures: list[PipelineJobFailure]) -> str:
    lines = [
        f"completed: {len(results)}",
        f"failed: {len(failures)}",
    ]
    for result in results:
        lines.append(f"ok {result.job_name}: {result.input_path}")
    for failure in failures:
        lines.append(f"error {failure.stage} {failure.job_name}: {failure.error}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        results, failures = run_pipeline(
            job=args.job,
            all_jobs=args.all,
            config_path=args.config,
            env_path=args.env,
            start_time=args.start_time,
            end_time=args.end_time,
            page_size=args.page_size,
            page_number=args.page_number,
            user_id_or_nick=args.user_id_or_nick,
            node_id=args.node_id,
            single_page=args.single_page,
            output_root=args.output_root,
        )
    except (FetchJobError, JsonApiError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(format_summary(results, failures))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
