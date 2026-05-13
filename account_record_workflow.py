#!/usr/bin/env python3
"""Fetch account record check-result data and analyze it in one command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from account_record_fetcher import (
    AccountRecordFetcher,
    JsonApiError,
    DEFAULT_ENV_PATH,
    FetchSettings,
    load_settings,
    write_output,
)
from bill_rule_analyzer import (
    DEFAULT_RAILS_ROOT,
    load_check_result_rows,
    load_seed_rules,
    render_report,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch account record check-result data and generate a seed analysis report.")
    parser.add_argument("--platform", required=True, help="Platform header, e.g. TAOBAO.")
    parser.add_argument("--source-type", required=True, help="Account source type, e.g. TAOBAO_ACCOUNT_RECORD.")
    parser.add_argument("--data-type", required=True, help="Account record data type, e.g. TAOBAO_ACCOUNT_RECORD.")
    parser.add_argument("--start-time", required=True, help='Start time, e.g. "2026-04-23 00:00:00".')
    parser.add_argument("--end-time", required=True, help='End time, e.g. "2026-05-07 23:59:59".')
    parser.add_argument("--page-size", type=int, default=5, help="User group page size. Default: 5.")
    parser.add_argument("--page-number", type=int, default=1, help="User group page number. Default: 1.")
    parser.add_argument("--user-id-or-nick", default="", help="Optional user id or nick filter.")
    parser.add_argument("--node-id", type=int, default=1, help="Node id. Default: 1.")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH, help="Path to .env file. Default: .env.")
    parser.add_argument("--single-page", action="store_true", help="Fetch only --page-number instead of all pages.")
    parser.add_argument("--rails-root", type=Path, default=DEFAULT_RAILS_ROOT, help="Path to plutus-rails.")
    parser.add_argument("--include-inactive", action="store_true", help="Also match status=0/-1 seed rules.")
    parser.add_argument("--report-output", type=Path, help="Write Markdown report to this file. Defaults to stdout.")
    parser.add_argument("--raw-output", type=Path, help="Write the fetched raw JSON response to this file.")
    return parser.parse_args(argv)


def run_workflow(
    settings: FetchSettings,
    *,
    platform: str,
    source_type: str,
    data_type: str,
    start_time: str,
    end_time: str,
    page_size: int = 5,
    page_number: int = 1,
    user_id_or_nick: str = "",
    node_id: int = 1,
    single_page: bool = False,
    rails_root: Path = DEFAULT_RAILS_ROOT,
    include_inactive: bool = False,
    fetcher: AccountRecordFetcher | None = None,
) -> tuple[dict[str, Any], str]:
    active_fetcher = fetcher or AccountRecordFetcher(settings)
    fetch_method = active_fetcher.fetch_check_all_user if single_page else active_fetcher.fetch_check_all_users
    response = fetch_method(
        platform=platform,
        data_type=data_type,
        start_time=start_time,
        end_time=end_time,
        page_size=page_size,
        page_number=page_number,
        user_id_or_nick=user_id_or_nick,
        node_id=node_id,
    )
    rows = load_check_result_rows(response)
    rules = load_seed_rules(rails_root, platform)
    report = render_report(rows, rules, platform, source_type, include_inactive=include_inactive)
    return response, report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.env)
        response, report = run_workflow(
            settings,
            platform=args.platform,
            source_type=args.source_type,
            data_type=args.data_type,
            start_time=args.start_time,
            end_time=args.end_time,
            page_size=args.page_size,
            page_number=args.page_number,
            user_id_or_nick=args.user_id_or_nick,
            node_id=args.node_id,
            single_page=args.single_page,
            rails_root=args.rails_root,
            include_inactive=args.include_inactive,
        )
        if args.raw_output:
            write_output(args.raw_output, response)
        if args.report_output:
            args.report_output.write_text(report, encoding="utf-8")
        else:
            print(report)
    except JsonApiError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
