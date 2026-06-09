#!/usr/bin/env python3
"""Run named account-record fetch jobs from a small JSON config."""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

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
    "pdd": "PINDUODUO",
    "kuaishou": "KUAISHOU",
    "jingdong": "JINGDONG",
    "dou": "DOUDIAN",
    "xhs": "XIAOHONGSHU",
    "wxxd": "WXXD",
}
PLATFORM_CANONICAL_NAMES = {
    "PDD": "PINDUODUO",
    "DOU": "DOUDIAN",
    "XHS": "XIAOHONGSHU",
}
PLATFORM_OUTPUT_LABELS = {
    "TAOBAO": "淘宝",
    "ALIBABA": "1688",
    "PINDUODUO": "拼多多",
    "KUAISHOU": "快手",
    "JINGDONG": "京东",
    "DOUDIAN": "抖店",
    "XIAOHONGSHU": "小红书",
    "WXXD": "微信小店",
}
SOURCE_TYPE_BILL_LABELS = {
    "TAOBAO_ACCOUNT_RECORD": "通用账单",
    "TB_WHALE_ACCOUNT_RECORD": "聚合结算账单明细",
    "TAOBAO_HAIWAI_ACCOUNT_RECORD": "国际支付宝账单明细",
    "TB_ALIPAY_SMALL_TRANSFER_ACCOUNT_RECORD": "小额打款",
    "ALIBABA_ALIPAY_ACCOUNT_RECORD": "支付宝账单",
    "PDD_MALL_ACCOUNT_RECORD": "货款账单",
    "PDD_MARKETING_ACCOUNT_RECORD": "营销账单",
    "PDD_MARKETING_ACTIVITY_SETTLEMENT_DETAIL": "营销活动结算对账单",
    "KUAISHOU_DEPOSIT_BILL": "保证金明细",
    "KUAISHOU_ACCOUNT_BILL": "资金账单明细",
    "KUAISHOU_ORDER_FLOW_DETAIL": "订单流水明细",
    "JINGDONG_INSURANCE_BILL": "保险费明细",
    "JINGDONG_LEDGER_BILL_DETAIL": "商家账单明细",
    "DOU_ORDER_SETTLE_BILL_DETAIL": "结算账单明细",
    "DOU_SHOP_ACCOUNT_ITEM": "资金流水账单",
    "DOU_DEPOSIT_BILL": "保证金明细",
    "DOU_MANAGER_ACCOUNT_DETAIL": "管家账户明细",
    "DOU_INSURANCE_BILL": "保险费明细",
    "XHS_SELLER_ACCOUNT_RECORD": "货款动账流水",
    "XHS_TRANSACTION": "订单结算货款",
    "WXXD_FUNDS_FLOW_DETAIL": "资金流水账单",
}
DISPLAY_NAME_PLATFORM_PREFIXES = (
    "淘宝",
    "1688",
    "阿里巴巴",
    "拼多多",
    "快手",
    "京东",
    "抖店",
    "小红书",
    "微信小店",
)


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
    progress: Callable[[str], None] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    output: Path | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    user_id_or_nick: str | None = None,
    node_id: int | None = None,
    single_page: bool = False,
    node_workers: int = 1,
    record_workers: int = 1,
    resume_dir: Path | None = None,
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
    explicit_output = output is not None
    if explicit_output:
        job["output"] = str(output)
    if page_size is not None:
        job["page_size"] = page_size
    if page_number is not None:
        job["page_number"] = page_number
    if user_id_or_nick is not None:
        job["user_id_or_nick"] = user_id_or_nick
    if node_id is not None:
        job["node_id"] = node_id

    require_job_fields(job_name, job, ["platform", "data_type", "start_time", "end_time"])
    job["platform"] = canonical_platform(str(job["platform"]))

    output_path = Path(str(job["output"])) if explicit_output else build_default_output_path(job)
    active_fetcher = fetcher or AccountRecordFetcher(load_settings(env_path), progress=progress)
    node_ids = node_ids_for_job(job)
    log_progress(
        progress,
        f"job start name={job_name} platform={job['platform']} data_type={job['data_type']} "
        f"nodes={len(node_ids)} time_range={str(job['start_time'])!r}..{str(job['end_time'])!r}",
    )
    responses = []
    completed_node_ids = []
    current_node_id = None
    try:
        max_node_workers = max(1, int(node_workers or 1))
        if max_node_workers == 1 or len(node_ids) == 1:
            for index, active_node_id in enumerate(node_ids, start=1):
                current_node_id = active_node_id
                log_progress(progress, f"node start job={job_name} node={index}/{len(node_ids)} node_id={active_node_id}")
                response_for_node = fetch_one_node(
                    active_fetcher,
                    job,
                    node_id=active_node_id,
                    single_page=single_page,
                    record_workers=record_workers,
                    resume_dir=resume_dir,
                )
                users, pages, total = response_counts(response_for_node)
                log_progress(
                    progress,
                    f"node done job={job_name} node={index}/{len(node_ids)} node_id={active_node_id} "
                    f"users={users} pages={pages} total={total}",
                )
                responses.append(response_for_node)
                completed_node_ids.append(active_node_id)
        else:
            responses_by_index: list[dict[str, Any] | None] = [None] * len(node_ids)
            with ThreadPoolExecutor(max_workers=max_node_workers) as executor:
                futures = {}
                for index, active_node_id in enumerate(node_ids, start=1):
                    log_progress(progress, f"node start job={job_name} node={index}/{len(node_ids)} node_id={active_node_id}")
                    future = executor.submit(
                        fetch_one_node,
                        active_fetcher,
                        job,
                        node_id=active_node_id,
                        single_page=single_page,
                        record_workers=record_workers,
                        resume_dir=resume_dir,
                    )
                    futures[future] = (index, active_node_id)
                for future in as_completed(futures):
                    index, active_node_id = futures[future]
                    current_node_id = active_node_id
                    response_for_node = future.result()
                    responses_by_index[index - 1] = response_for_node
                    responses.append(response_for_node)
                    completed_node_ids.append(active_node_id)
                    users, pages, total = response_counts(response_for_node)
                    log_progress(
                        progress,
                        f"node done job={job_name} node={index}/{len(node_ids)} node_id={active_node_id} "
                        f"users={users} pages={pages} total={total}",
                    )
            responses = [response for response in responses_by_index if response is not None]
            completed_node_ids = [node_id for node_id, response in zip(node_ids, responses_by_index) if response is not None]
    except Exception as error:
        partial_responses = list(responses)
        partial_node_ids = list(completed_node_ids)
        current_partial_response = getattr(error, "partial_response", None)
        if isinstance(current_partial_response, dict) and current_node_id is not None:
            partial_responses.append(current_partial_response)
            partial_node_ids.append(current_node_id)

        if partial_responses:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            partial_response = partial_response_for_error(partial_responses, partial_node_ids, error)
            partial_path = partial_output_path(output_path)
            write_output(partial_path, partial_response)
            log_progress(progress, f"partial saved job={job_name} path={partial_path}")
        raise
    response = responses[0] if len(responses) == 1 else merge_node_responses(responses, node_ids)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_output(output_path, response)
    return output_path, response


def run_fetch_jobs(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    fetcher: AccountRecordFetcher | Any | None = None,
    progress: Callable[[str], None] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    user_id_or_nick: str | None = None,
    node_id: int | None = None,
    single_page: bool = False,
    node_workers: int = 1,
    record_workers: int = 1,
    resume_dir: Path | None = None,
) -> list[tuple[str, Path, dict[str, Any]]]:
    jobs = load_fetch_jobs(config_path)
    active_fetcher = fetcher or AccountRecordFetcher(load_settings(env_path), progress=progress)
    results: list[tuple[str, Path, dict[str, Any]]] = []
    for job_name in jobs:
        output_path, response = run_fetch_job(
            job_name,
            config_path=config_path,
            env_path=env_path,
            fetcher=active_fetcher,
            progress=progress,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size,
            page_number=page_number,
            user_id_or_nick=user_id_or_nick,
            node_id=node_id,
            single_page=single_page,
            node_workers=node_workers,
            record_workers=record_workers,
            resume_dir=resume_dir,
        )
        results.append((job_name, output_path, response))
    return results


def run_fetch_platform(
    platform_alias: str,
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    fetcher: AccountRecordFetcher | Any | None = None,
    progress: Callable[[str], None] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    page_size: int | None = None,
    page_number: int | None = None,
    user_id_or_nick: str | None = None,
    node_id: int | None = None,
    single_page: bool = False,
    node_workers: int = 1,
    record_workers: int = 1,
    resume_dir: Path | None = None,
) -> list[tuple[str, Path, dict[str, Any]]]:
    platform = platform_for_alias(platform_alias)
    if platform is None:
        available = ", ".join(sorted(PLATFORM_ALIASES))
        raise FetchJobError(f"Unknown platform alias {platform_alias!r}. Available platforms: {available}")

    jobs = load_fetch_jobs(config_path)
    active_fetcher = fetcher or AccountRecordFetcher(load_settings(env_path), progress=progress)
    results: list[tuple[str, Path, dict[str, Any]]] = []
    for job_name, job in jobs.items():
        if canonical_platform(str(job.get("platform"))) != platform:
            continue
        output_path, response = run_fetch_job(
            job_name,
            config_path=config_path,
            env_path=env_path,
            fetcher=active_fetcher,
            progress=progress,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size,
            page_number=page_number,
            user_id_or_nick=user_id_or_nick,
            node_id=node_id,
            single_page=single_page,
            node_workers=node_workers,
            record_workers=record_workers,
            resume_dir=resume_dir,
        )
        results.append((job_name, output_path, response))

    if not results:
        raise FetchJobError(f"No fetch jobs configured for platform {platform}")
    return results


def platform_for_alias(value: str) -> str | None:
    return PLATFORM_ALIASES.get(value.lower())


def canonical_platform(value: str) -> str:
    platform = value.upper()
    return PLATFORM_CANONICAL_NAMES.get(platform, platform)


def build_default_output_path(job: dict[str, Any]) -> Path:
    platform_label = output_platform_label(job)
    source_type = output_source_type(job)
    bill_label = output_bill_label(job, platform_label, source_type)
    filename = f"{platform_label}-{bill_label}-{source_type}.json"
    return output_root_for_job(job) / output_platform_directory(job, platform_label) / safe_path_part(filename)


def output_platform_label(job: dict[str, Any]) -> str:
    platform = canonical_platform(str(job.get("platform", "")))
    return PLATFORM_OUTPUT_LABELS.get(platform, platform or "UNKNOWN")


def output_source_type(job: dict[str, Any]) -> str:
    source_type = str(job.get("source_type") or job.get("data_type") or "UNKNOWN")
    return safe_path_part(source_type)


def output_platform_directory(job: dict[str, Any], platform_label: str) -> str:
    start_date = compact_date_for_path(job.get("start_time"))
    end_date = compact_date_for_path(job.get("end_time"))
    if start_date and end_date:
        return safe_path_part(f"{platform_label}（{start_date}至{end_date}）")
    return safe_path_part(platform_label)


def compact_date_for_path(value: Any) -> str | None:
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    date_part = text[:10]
    parts = date_part.split("-")
    if len(parts) != 3:
        return None
    year, month, day = parts
    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return None
    return f"{year}{month.zfill(2)}{day.zfill(2)}"


def output_bill_label(job: dict[str, Any], platform_label: str, source_type: str) -> str:
    if job.get("bill_type"):
        return safe_path_part(str(job["bill_type"]))
    if job.get("bill_name"):
        return safe_path_part(str(job["bill_name"]))
    if source_type in SOURCE_TYPE_BILL_LABELS:
        return SOURCE_TYPE_BILL_LABELS[source_type]

    display_name = str(job.get("display_name", "")).strip()
    for prefix in (platform_label, *DISPLAY_NAME_PLATFORM_PREFIXES):
        if display_name.startswith(prefix):
            display_name = display_name[len(prefix):].strip()
            break
    return safe_path_part(display_name or source_type)


def output_root_for_job(job: dict[str, Any]) -> Path:
    output = job.get("output")
    if not output:
        return Path("inputs")

    output_path = Path(str(output))
    parts = output_path.parts
    for index, part in enumerate(parts):
        if part == "inputs":
            return Path(*parts[: index + 1])
    return output_path.parent


def safe_path_part(value: str) -> str:
    return value.replace("/", "-").replace("\\", "-").strip()


def node_ids_for_job(job: dict[str, Any]) -> list[int]:
    if job.get("node_id") is not None:
        return [int(job["node_id"])]
    raw_node_ids = job.get("node_ids")
    if raw_node_ids is None:
        return [1]
    if not isinstance(raw_node_ids, list) or not raw_node_ids:
        raise FetchJobError("node_ids must be a non-empty JSON array")
    return [int(node_id) for node_id in raw_node_ids]


def fetch_one_node(
    fetcher: Any,
    job: dict[str, Any],
    *,
    node_id: int,
    single_page: bool,
    record_workers: int = 1,
    resume_dir: Path | None = None,
) -> dict[str, Any]:
    fetch_method = fetcher.fetch_check_all_user if single_page else fetcher.fetch_check_all_users
    kwargs = {
        "platform": str(job["platform"]),
        "data_type": str(job["data_type"]),
        "start_time": str(job["start_time"]),
        "end_time": str(job["end_time"]),
        "page_size": int(job.get("page_size", 5)),
        "page_number": int(job.get("page_number", 1)),
        "user_id_or_nick": str(job.get("user_id_or_nick", "")),
        "node_id": node_id,
    }
    if not single_page:
        kwargs["record_workers"] = record_workers
        kwargs["resume_dir"] = resume_dir
    return fetch_method(**kwargs)


def log_progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def response_counts(response: dict[str, Any]) -> tuple[str, str, str]:
    data = response.get("data")
    if not isinstance(data, dict):
        return "?", "?", "?"
    content = data.get("content", [])
    users = len(content) if isinstance(content, list) else 0
    pages_value = data.get("pages", [])
    if isinstance(pages_value, list):
        pages = len(pages_value)
    else:
        pages = parse_optional_int(data.get("totalPage")) or 1
    total = parse_optional_int(data.get("total"))
    return str(users), str(pages), format_count(total)


def partial_output_path(output_path: Path) -> Path:
    return output_path.with_name(f"{output_path.stem}.partial{output_path.suffix}")


def partial_response_for_error(
    responses: list[dict[str, Any]],
    node_ids: list[int],
    error: BaseException,
) -> dict[str, Any]:
    partial = merge_node_responses(responses, node_ids)
    partial = copy.deepcopy(partial)
    partial["_partialFetch"] = {
        "partial": True,
        "error": str(error),
        "completedNodeIds": node_ids,
    }
    return partial


def merge_node_responses(responses: list[dict[str, Any]], node_ids: list[int]) -> dict[str, Any]:
    merged = copy.deepcopy(responses[0])
    merged_data = merged.setdefault("data", {})
    if not isinstance(merged_data, dict):
        merged["data"] = merged_data = {}

    combined_content: list[Any] = []
    combined_pages: list[Any] = []
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
        pages = data.get("pages", [])
        if isinstance(pages, list):
            for page in pages:
                combined_pages.append(page_with_node_id(page, node_id))

    merged_data["content"] = combined_content
    merged_data["pages"] = combined_pages
    merged_data["total"] = total
    merged_data["nodeIds"] = node_ids
    merged_data["totalPage"] = 1
    return merged


def page_with_node_id(page: Any, node_id: int) -> Any:
    if not isinstance(page, dict):
        return page
    copied_page = copy.deepcopy(page)
    copied_page["nodeId"] = node_id
    content = copied_page.get("content", [])
    if isinstance(content, list):
        copied_content: list[Any] = []
        for item in content:
            if isinstance(item, dict):
                copied_item = copy.deepcopy(item)
                copied_item["nodeId"] = node_id
                copied_content.append(copied_item)
            else:
                copied_content.append(item)
        copied_page["content"] = copied_content
    return copied_page


def parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def format_count(value: Any) -> str:
    return "?" if value is None else str(value)


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
    parser.add_argument("--node-workers", type=int, default=1, help="Concurrent node fetch workers. Default: 1.")
    parser.add_argument("--record-workers", type=int, default=1, help="Concurrent per-merchant record page workers. Default: 1.")
    parser.add_argument("--resume-dir", type=Path, help="Cache fetched merchant record pages for resumable runs.")
    return parser.parse_args(argv)


def stderr_progress(message: str) -> None:
    timestamp = datetime.now().strftime("%Y%m%d %H:%M:%S")
    print(f"[{timestamp}] fetch {message}", file=sys.stderr, flush=True)


def format_elapsed_seconds(started_at: float) -> str:
    return f"{max(0.0, time.monotonic() - started_at):.2f}s"


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

    started_at = time.monotonic()
    try:
        if args.all:
            results = run_fetch_jobs(
                config_path=args.config,
                env_path=args.env,
                progress=stderr_progress,
                start_time=args.start_time,
                end_time=args.end_time,
                page_size=args.page_size,
                page_number=args.page_number,
                user_id_or_nick=args.user_id_or_nick,
                node_id=args.node_id,
                single_page=args.single_page,
                node_workers=args.node_workers,
                record_workers=args.record_workers,
                resume_dir=args.resume_dir,
            )
            elapsed = format_elapsed_seconds(started_at)
            for job_name, output_path, _ in results:
                print(f"Wrote {job_name}: {output_path} 耗时{elapsed}")
        elif platform_for_alias(str(args.job)) is not None:
            results = run_fetch_platform(
                str(args.job),
                config_path=args.config,
                env_path=args.env,
                progress=stderr_progress,
                start_time=args.start_time,
                end_time=args.end_time,
                page_size=args.page_size,
                page_number=args.page_number,
                user_id_or_nick=args.user_id_or_nick,
                node_id=args.node_id,
                single_page=args.single_page,
                node_workers=args.node_workers,
                record_workers=args.record_workers,
                resume_dir=args.resume_dir,
            )
            elapsed = format_elapsed_seconds(started_at)
            for job_name, output_path, _ in results:
                print(f"Wrote {job_name}: {output_path} 耗时{elapsed}")
        else:
            output_path, response = run_fetch_job(
                str(args.job),
                config_path=args.config,
                env_path=args.env,
                progress=stderr_progress,
                start_time=args.start_time,
                end_time=args.end_time,
                output=args.output,
                page_size=args.page_size,
                page_number=args.page_number,
                user_id_or_nick=args.user_id_or_nick,
                node_id=args.node_id,
                single_page=args.single_page,
                node_workers=args.node_workers,
                record_workers=args.record_workers,
                resume_dir=args.resume_dir,
            )
            print(f"Wrote {output_path} 耗时{format_elapsed_seconds(started_at)}")
    except (FetchJobError, JsonApiError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
