#!/usr/bin/env python3
"""Fetch account record check-result data with a .env API token."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://a6m1n.topkjs.com"
DEFAULT_ENV_PATH = Path(".env")


class JsonApiError(RuntimeError):
    def __init__(self, message: str, code: int | str | None = None):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchSettings:
    token: str
    base_url: str


class UrlLibJsonClient:
    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=body, method="POST")
        for key, value in headers.items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raw = error.read().decode("utf-8", errors="replace")
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise JsonApiError(f"HTTP {error.code}: {raw}", code=error.code) from exc


class AccountRecordFetcher:
    def __init__(self, settings: FetchSettings, http_client: UrlLibJsonClient | Any | None = None):
        self.settings = settings
        self.http_client = http_client or UrlLibJsonClient()

    def fetch_check_all_user(
        self,
        *,
        platform: str,
        data_type: str,
        start_time: str,
        end_time: str,
        page_size: int = 5,
        page_number: int = 1,
        user_id_or_nick: str = "",
        node_id: int = 1,
    ) -> dict[str, Any]:
        payload = build_check_all_user_payload(
            data_type=data_type,
            start_time=start_time,
            end_time=end_time,
            page_size=page_size,
            page_number=page_number,
            user_id_or_nick=user_id_or_nick,
            node_id=node_id,
        )
        response = self._post_check_all_user(platform, self.settings.token, payload)
        ensure_success(response)
        return response

    def fetch_check_all_users(
        self,
        *,
        platform: str,
        data_type: str,
        start_time: str,
        end_time: str,
        page_size: int = 5,
        page_number: int = 1,
        user_id_or_nick: str = "",
        node_id: int = 1,
    ) -> dict[str, Any]:
        current_page = page_number
        first_response: dict[str, Any] | None = None
        combined_content: list[Any] = []
        total: int | None = None

        while True:
            response = self.fetch_check_all_user(
                platform=platform,
                data_type=data_type,
                start_time=start_time,
                end_time=end_time,
                page_size=page_size,
                page_number=current_page,
                user_id_or_nick=user_id_or_nick,
                node_id=node_id,
            )
            if first_response is None:
                first_response = copy.deepcopy(response)

            data = response.get("data")
            page_content = data.get("content", []) if isinstance(data, dict) else []
            if not isinstance(page_content, list):
                page_content = []
            combined_content.extend(page_content)

            if isinstance(data, dict) and total is None:
                total = parse_optional_int(data.get("total"))

            if total is not None:
                if current_page * page_size >= total:
                    break
                if not page_content:
                    break
            elif len(page_content) < page_size:
                break

            current_page += 1

        self._complete_user_record_pages(
            combined_content,
            platform=platform,
            data_type=data_type,
            start_time=start_time,
            end_time=end_time,
            node_id=node_id,
        )

        if first_response is None:
            return {}
        first_data = first_response.setdefault("data", {})
        if isinstance(first_data, dict):
            first_data["content"] = combined_content
            if total is not None:
                first_data["total"] = total
        return first_response

    def _post_check_all_user(self, platform: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = auth_headers(token, platform)
        return self.http_client.post_json(self._url("/api/accountRecordCheckResult/checkAllUser"), payload, headers)

    def _complete_user_record_pages(
        self,
        users: list[Any],
        *,
        platform: str,
        data_type: str,
        start_time: str,
        end_time: str,
        node_id: int,
    ) -> None:
        for user in users:
            if not isinstance(user, dict):
                continue
            paged_records = user.get("pagedRecords")
            if not isinstance(paged_records, dict):
                continue

            content = paged_records.get("content", [])
            if not isinstance(content, list):
                content = []
            current_page = parse_optional_int(paged_records.get("pageNumber")) or 1
            record_page_size = parse_optional_int(paged_records.get("pageSize")) or len(content) or 1
            total_page = parse_optional_int(paged_records.get("totalPage"))
            total = parse_optional_int(paged_records.get("total"))
            if total_page is None and total is not None:
                total_page = (total + record_page_size - 1) // record_page_size
            if total_page is None or current_page >= total_page:
                continue

            user_id_or_nick = record_page_user_id_or_nick(user)
            if not user_id_or_nick:
                continue

            combined_records = list(content)
            next_page = current_page + 1
            while next_page <= total_page:
                response = self.fetch_check_all_user(
                    platform=platform,
                    data_type=data_type,
                    start_time=start_time,
                    end_time=end_time,
                    page_size=record_page_size,
                    page_number=next_page,
                    user_id_or_nick=user_id_or_nick,
                    node_id=node_id,
                )
                next_paged_records = find_user_paged_records(response, user)
                if next_paged_records is None:
                    break

                page_content = next_paged_records.get("content", [])
                if not isinstance(page_content, list):
                    page_content = []
                combined_records.extend(page_content)

                next_total = parse_optional_int(next_paged_records.get("total"))
                if next_total is not None:
                    total = next_total
                    paged_records["total"] = next_total
                next_total_page = parse_optional_int(next_paged_records.get("totalPage"))
                if next_total_page is not None:
                    total_page = next_total_page
                    paged_records["totalPage"] = next_total_page

                if not page_content:
                    break
                next_page += 1

            paged_records["content"] = combined_records

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}{path}"


def default_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }


def auth_headers(token: str, platform: str) -> dict[str, str]:
    headers = default_headers()
    headers["Authorization"] = f"Bearer {token}"
    headers["Platform"] = platform
    return headers


def build_check_all_user_payload(
    *,
    data_type: str,
    start_time: str,
    end_time: str,
    page_size: int,
    page_number: int,
    user_id_or_nick: str,
    node_id: int,
) -> dict[str, Any]:
    return {
        "pageSize": page_size,
        "pageNumber": page_number,
        "dataType": data_type,
        "nodeId": node_id,
        "userIdOrNick": user_id_or_nick,
        "dateRange": [start_time, end_time],
        "startTime": start_time,
        "endTime": end_time,
        "filterOptions": [],
    }


def parse_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def record_page_user_id_or_nick(user: dict[str, Any]) -> str:
    for key in ("userId", "user_id", "nick", "userNick"):
        value = user.get(key)
        if value not in {None, ""}:
            return str(value)
    return ""


def find_user_paged_records(response: dict[str, Any], user: dict[str, Any]) -> dict[str, Any] | None:
    data = response.get("data")
    if not isinstance(data, dict):
        return None
    content = data.get("content", [])
    if not isinstance(content, list):
        return None

    fallback: dict[str, Any] | None = None
    for item in content:
        if not isinstance(item, dict):
            continue
        paged_records = item.get("pagedRecords")
        if not isinstance(paged_records, dict):
            continue
        if fallback is None:
            fallback = paged_records
        if is_same_user(item, user):
            return paged_records
    return fallback


def is_same_user(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for key in ("userId", "user_id"):
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value not in {None, ""} and right_value not in {None, ""}:
            return str(left_value) == str(right_value)

    for key in ("nick", "userNick"):
        left_value = left.get(key)
        right_value = right.get(key)
        if left_value not in {None, ""} and right_value not in {None, ""}:
            return str(left_value) == str(right_value)
    return False


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key] = value
    return values


def load_settings(env_path: Path) -> FetchSettings:
    env_values = load_dotenv(env_path)
    values = {**env_values, **os.environ}
    token = values.get("A6M1N_TOKEN")
    if not token:
        raise JsonApiError(f"Missing A6M1N_TOKEN in {env_path}")
    return FetchSettings(
        token=token,
        base_url=values.get("A6M1N_BASE_URL", DEFAULT_BASE_URL),
    )


def ensure_success(response: dict[str, Any]) -> None:
    if response.get("success") is False:
        raise JsonApiError(str(response.get("message") or "API request failed"), code=response.get("code"))
    status = parse_optional_int(response.get("status"))
    if status is not None and status >= 400:
        message = str(response.get("error") or response.get("message") or f"HTTP {status}")
        raise JsonApiError(message, code=status)


def write_output(path: Path | None, data: dict[str, Any]) -> None:
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path:
        path.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch account record check-result data from admin API.")
    parser.add_argument("--platform", required=True, help="Platform header, e.g. TAOBAO.")
    parser.add_argument("--data-type", required=True, help="Account record data type, e.g. TAOBAO_ACCOUNT_RECORD.")
    parser.add_argument("--start-time", required=True, help='Start time, e.g. "2026-04-23 00:00:00".')
    parser.add_argument("--end-time", required=True, help='End time, e.g. "2026-05-07 23:59:59".')
    parser.add_argument("--page-size", type=int, default=5, help="User group page size. Default: 5.")
    parser.add_argument("--page-number", type=int, default=1, help="User group page number. Default: 1.")
    parser.add_argument("--user-id-or-nick", default="", help="Optional user id or nick filter.")
    parser.add_argument("--node-id", type=int, default=1, help="Node id. Default: 1.")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH, help="Path to .env file. Default: .env.")
    parser.add_argument("--single-page", action="store_true", help="Fetch only --page-number instead of all pages.")
    parser.add_argument("--output", type=Path, help="Write formatted JSON to this file. Defaults to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        settings = load_settings(args.env)
        fetcher = AccountRecordFetcher(settings)
        fetch_method = fetcher.fetch_check_all_user if args.single_page else fetcher.fetch_check_all_users
        data = fetch_method(
            platform=args.platform,
            data_type=args.data_type,
            start_time=args.start_time,
            end_time=args.end_time,
            page_size=args.page_size,
            page_number=args.page_number,
            user_id_or_nick=args.user_id_or_nick,
            node_id=args.node_id,
        )
        write_output(args.output, data)
    except JsonApiError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
