#!/usr/bin/env python3
"""Run named account-record fetch jobs from a small JSON config."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

from account_record_fetcher import (
    AccountRecordFetcher,
    DEFAULT_ENV_PATH,
    JsonApiError,
    load_settings,
    write_output,
)


DEFAULT_CONFIG_PATH = Path("fetch_jobs.json")
PLATFORM_ALIASES = {
    "taobao": "TAOBAO",
    "alibaba": "ALIBABA",
    "pdd": "PDD",
    "kuaishou": "KUAISHOU",
    "jingdong": "JINGDONG",
    "dou": "DOU",
    "xhs": "XHS",
    "wxxd": "WXXD",
}


class FetchJobError(RuntimeError):
    pass


def load_fetch_jobs(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        raise FetchJobError(f"Fetch job config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FetchJobError("Fetch job config must be a JSON object")
    if "jobs" in data:
        defaults = data.get("defaults", {})
        raw_jobs = data.get("jobs")
        if not isinstance(defaults, dict):
            raise FetchJobError("Fetch job defaults must be a JSON object")
        if not isinstance(raw_jobs, dict):
            raise FetchJobError("Fetch job config field 'jobs' must be a JSON object")
        return normalize_jobs(raw_jobs, defaults)
    return normalize_jobs(data, {})


def normalize_jobs(raw_jobs: dict[str, Any], defaults: dict[str, Any]) -> dict[str, dict[str, Any]]:
    jobs: dict[str, dict[str, Any]] = {}
    for name, job in raw_jobs.items():
        if not isinstance(job, dict):
            raise FetchJobError(f"Fetch job {name!r} must be a JSON object")
        jobs[str(name)] = {**defaults, **job}
    return jobs


def run_fetch_job(
    job_name: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    fetcher: AccountRecordFetcher | Any | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    output: Path | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    user_id_or_nick: str | None = None,
    node_id: int | None = None,
    single_page: bool = False,
) -> tuple[Path, dict[str, Any]]:
    jobs = load_fetch_jobs(config_path)
    if job_name not in jobs:
        available = ", ".join(sorted(jobs)) or "(none)"
        raise FetchJobError(f"Unknown fetch job {job_name!r}. Available jobs: {available}")

    job = dict(jobs[job_name])
    if start_time is not None:
        job["start_time"] = start_time
    if end_time is not None:
        job["end_time"] = end_time
    if output is not None:
        job["output"] = str(output)
    if page_size is not None:
        job["page_size"] = page_size
    if page_number is not None:
        job["page_number"] = page_number
    if user_id_or_nick is not None:
        job["user_id_or_nick"] = user_id_or_nick
    if node_id is not None:
        job["node_id"] = node_id

    require_job_fields(job_name, job, ["platform", "data_type", "start_time", "end_time", "output"])

    active_fetcher = fetcher or AccountRecordFetcher(load_settings(env_path))
    node_ids = node_ids_for_job(job)
    responses = [
        fetch_one_node(active_fetcher, job, node_id=active_node_id, single_page=single_page)
        for active_node_id in node_ids
    ]
    response = responses[0] if len(responses) == 1 else merge_node_responses(responses, node_ids)

    output_path = Path(str(job["output"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_output(output_path, response)
    return output_path, response


def run_fetch_jobs(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    fetcher: AccountRecordFetcher | Any | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    user_id_or_nick: str | None = None,
    node_id: int | None = None,
    single_page: bool = False,
) -> list[tuple[str, Path, dict[str, Any]]]:
    jobs = load_fetch_jobs(config_path)
    active_fetcher = fetcher or AccountRecordFetcher(load_settings(env_path))
    results: list[tuple[str, Path, dict[str, Any]]] = []
    for job_name in jobs:
        output_path, response = run_fetch_job(
            job_name,
            config_path=config_path,
            env_path=env_path,
            fetcher=active_fetcher,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size,
            page_number=page_number,
            user_id_or_nick=user_id_or_nick,
            node_id=node_id,
            single_page=single_page,
        )
        results.append((job_name, output_path, response))
    return results


def run_fetch_platform(
    platform_alias: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    fetcher: AccountRecordFetcher | Any | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    user_id_or_nick: str | None = None,
    node_id: int | None = None,
    single_page: bool = False,
) -> list[tuple[str, Path, dict[str, Any]]]:
    platform = platform_for_alias(platform_alias)
    if platform is None:
        available = ", ".join(sorted(PLATFORM_ALIASES))
        raise FetchJobError(f"Unknown platform alias {platform_alias!r}. Available platforms: {available}")

    jobs = load_fetch_jobs(config_path)
    active_fetcher = fetcher or AccountRecordFetcher(load_settings(env_path))
    results: list[tuple[str, Path, dict[str, Any]]] = []
    for job_name, job in jobs.items():
        if str(job.get("platform")) != platform:
            continue
        output_path, response = run_fetch_job(
            job_name,
            config_path=config_path,
            env_path=env_path,
            fetcher=active_fetcher,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size,
            page_number=page_number,
            user_id_or_nick=user_id_or_nick,
            node_id=node_id,
            single_page=single_page,
        )
        results.append((job_name, output_path, response))

    if not results:
        raise FetchJobError(f"No fetch jobs configured for platform {platform}")
    return results


def platform_for_alias(value: str) -> str | None:
    return PLATFORM_ALIASES.get(value.lower())


def node_ids_for_job(job: dict[str, Any]) -> list[int]:
    if job.get("node_id") is not None:
        return [int(job["node_id"])]
    raw_node_ids = job.get("node_ids")
    if raw_node_ids is None:
        return [1]
    if not isinstance(raw_node_ids, list) or not raw_node_ids:
        raise FetchJobError("node_ids must be a non-empty JSON array")
    return [int(node_id) for node_id in raw_node_ids]


def fetch_one_node(fetcher: Any, job: dict[str, Any], *, node_id: int, single_page: bool) -> dict[str, Any]:
    fetch_method = fetcher.fetch_check_all_user if single_page else fetcher.fetch_check_all_users
    return fetch_method(
        platform=str(job["platform"]),
        data_type=str(job["data_type"]),
        start_time=str(job["start_time"]),
        end_time=str(job["end_time"]),
        page_size=int(job.get("page_size", 5)),
        page_number=int(job.get("page_number", 1)),
        user_id_or_nick=str(job.get("user_id_or_nick", "")),
        node_id=node_id,
    )


def merge_node_responses(responses: list[dict[str, Any]], node_ids: list[int]) -> dict[str, Any]:
    merged = copy.deepcopy(responses[0])
    merged_data = merged.setdefault("data", {})
    if not isinstance(merged_data, dict):
        merged["data"] = merged_data = {}

    combined_content: list[Any] = []
    total = 0
    for response, node_id in zip(responses, node_ids):
        data = response.get("data")
        if not isinstance(data, dict):
            continue
        total += parse_optional_int(data.get("total")) or 0
        content = data.get("content", [])
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict):
                copied_item = copy.deepcopy(item)
                copied_item["nodeId"] = node_id
                combined_content.append(copied_item)
            else:
                combined_content.append(item)

    merged_data["content"] = combined_content
    merged_data["total"] = total
    merged_data["nodeIds"] = node_ids
    merged_data["totalPage"] = 1
    return merged


def parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def require_job_fields(job_name: str, job: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if job.get(field) in {None, ""}]
    if missing:
        raise FetchJobError(f"Fetch job {job_name!r} is missing required fields: {', '.join(missing)}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a named account-record fetch job from fetch_jobs.json.")
    parser.add_argument("job", nargs="?", help="Fetch job name or platform alias, e.g. dou.")
    parser.add_argument("--all", action="store_true", help="Fetch every job in the config file.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help=f"Fetch job config path. Default: {DEFAULT_CONFIG_PATH}.")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH, help=f"Path to .env file. Default: {DEFAULT_ENV_PATH}.")
    parser.add_argument("--start-time", help='Override job start time, e.g. "2026-05-01 00:00:00".')
    parser.add_argument("--end-time", help='Override job end time, e.g. "2026-05-13 23:59:59".')
    parser.add_argument("--output", type=Path, help="Override output JSON path.")
    parser.add_argument("--page-size", type=int, help="Override page size.")
    parser.add_argument("--page-number", type=int, help="Override start page number.")
    parser.add_argument("--user-id-or-nick", help="Override optional user id or nick filter.")
    parser.add_argument("--node-id", type=int, help="Override node id.")
    parser.add_argument("--single-page", action="store_true", help="Fetch only --page-number instead of all pages.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.all and args.job:
        print("error: provide either a job name or --all, not both", file=sys.stderr)
        return 1
    if args.all and args.output is not None:
        print("error: --output cannot be used with --all because each job writes its own output", file=sys.stderr)
        return 1
    if args.job and platform_for_alias(str(args.job)) is not None and args.output is not None:
        print("error: --output cannot be used with a platform alias because each job writes its own output", file=sys.stderr)
        return 1
    if not args.all and not args.job:
        print("error: provide a job name or --all", file=sys.stderr)
        return 1

    try:
        if args.all:
            results = run_fetch_jobs(
                config_path=args.config,
                env_path=args.env,
                start_time=args.start_time,
                end_time=args.end_time,
                page_size=args.page_size,
                page_number=args.page_number,
                user_id_or_nick=args.user_id_or_nick,
                node_id=args.node_id,
                single_page=args.single_page,
            )
            for job_name, output_path, _ in results:
                print(f"Wrote {job_name}: {output_path}")
        elif platform_for_alias(str(args.job)) is not None:
            results = run_fetch_platform(
                str(args.job),
                config_path=args.config,
                env_path=args.env,
                start_time=args.start_time,
                end_time=args.end_time,
                page_size=args.page_size,
                page_number=args.page_number,
                user_id_or_nick=args.user_id_or_nick,
                node_id=args.node_id,
                single_page=args.single_page,
            )
            for job_name, output_path, _ in results:
                print(f"Wrote {job_name}: {output_path}")
        else:
            output_path, response = run_fetch_job(
                str(args.job),
                config_path=args.config,
                env_path=args.env,
                start_time=args.start_time,
                end_time=args.end_time,
                output=args.output,
                page_size=args.page_size,
                page_number=args.page_number,
                user_id_or_nick=args.user_id_or_nick,
                node_id=args.node_id,
                single_page=args.single_page,
            )
            print(f"Wrote {output_path}")
    except (FetchJobError, JsonApiError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
