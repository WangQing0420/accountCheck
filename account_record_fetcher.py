#!/usr/bin/env python3
"""Fetch account record check-result data with a .env API token."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DEFAULT_BASE_URL = "https://a6m1n.topkjs.com"
DEFAULT_ENV_PATH = Path(".env")


class JsonApiError(RuntimeError):
    def __init__(self, message: str, code: int | str | None = None):
        super().__init__(message)
        self.code = code


class PartialFetchError(JsonApiError):
    def __init__(
        self,
        message: str,
        *,
        partial_response: dict[str, Any],
        code: int | str | None = None,
    ):
        super().__init__(message, code=code)
        self.partial_response = partial_response


@dataclass(frozen=True)
class FetchSettings:
    token: str
    base_url: str


class UrlLibJsonClient:
    def __init__(self, max_attempts: int = 3):
        self.max_attempts = max(1, max_attempts)

    def post_json(self, url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        for attempt in range(1, self.max_attempts + 1):
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
            except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError, OSError):
                if attempt >= self.max_attempts:
                    raise
        raise JsonApiError("unreachable retry state")


class AccountRecordFetcher:
    def __init__(
        self,
        settings: FetchSettings,
        http_client: UrlLibJsonClient | Any | None = None,
        progress: Callable[[str], None] | None = None,
    ):
        self.settings = settings
        self.http_client = http_client or UrlLibJsonClient()
        self.progress = progress

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

    def fetch_check_single_user(
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
        response = self._post_check_single_user(platform, self.settings.token, payload)
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
        record_workers: int = 1,
        resume_dir: Path | None = None,
    ) -> dict[str, Any]:
        current_page = page_number
        first_response: dict[str, Any] | None = None
        combined_content: list[Any] = []
        pages: list[dict[str, Any]] = []
        total: int | None = None

        try:
            while True:
                self._progress(
                    f"users page start platform={platform} data_type={data_type} "
                    f"node_id={node_id} page={current_page}"
                )
                started_at = time.monotonic()
                try:
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
                except Exception as error:
                    self._progress(
                        f"users page error platform={platform} data_type={data_type} "
                        f"node_id={node_id} page={current_page} elapsed_ms={elapsed_ms(started_at)} "
                        f"error={error}"
                    )
                    raise
                if first_response is None:
                    first_response = copy.deepcopy(response)

                data = response.get("data")
                page_content = data.get("content", []) if isinstance(data, dict) else []
                if not isinstance(page_content, list):
                    page_content = []
                if isinstance(data, dict):
                    pages.append(page_snapshot(data, page_number=current_page, page_size=page_size))
                combined_content.extend(page_content)

                if isinstance(data, dict) and total is None:
                    total = parse_optional_int(data.get("total"))
                self._progress(
                    f"users page done platform={platform} data_type={data_type} node_id={node_id} "
                    f"page={current_page} users={len(page_content)} elapsed_ms={elapsed_ms(started_at)}"
                )
                self._progress(
                    f"users page platform={platform} data_type={data_type} node_id={node_id} "
                    f"page={current_page} users={len(page_content)} fetched_users={len(combined_content)} "
                    f"total_users={format_count(total)}"
                )

                if total is not None:
                    if current_page * page_size >= total:
                        break
                    if not page_content:
                        break
                elif len(page_content) < page_size:
                    break

                current_page += 1

            if total is not None and len(combined_content) != total:
                raise JsonApiError(f"Incomplete data.content: fetched {len(combined_content)} of {total}")

            self._complete_user_record_pages(
                combined_content,
                platform=platform,
                data_type=data_type,
                start_time=start_time,
                end_time=end_time,
                node_id=node_id,
                record_workers=record_workers,
                resume_dir=resume_dir,
            )
        except Exception as error:
            if first_response is None:
                raise
            raise PartialFetchError(
                str(error),
                partial_response=build_fetch_all_users_response(first_response, combined_content, pages, total),
                code=getattr(error, "code", None),
            ) from error

        if first_response is None:
            return {}
        return build_fetch_all_users_response(first_response, combined_content, pages, total)

    def _post_check_all_user(self, platform: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = auth_headers(token, platform)
        return self.http_client.post_json(self._url("/api/accountRecordCheckResult/checkAllUser"), payload, headers)

    def _post_check_single_user(self, platform: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = auth_headers(token, platform)
        return self.http_client.post_json(self._url("/api/accountRecordCheckResult/checkSingleUser"), payload, headers)

    def _complete_user_record_pages(
        self,
        users: list[Any],
        *,
        platform: str,
        data_type: str,
        start_time: str,
        end_time: str,
        node_id: int,
        record_workers: int = 1,
        resume_dir: Path | None = None,
    ) -> None:
        total_users = len(users)
        for user_index, user in enumerate(users, start=1):
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
            record_pages = [
                page_snapshot(paged_records, page_number=current_page, page_size=record_page_size)
            ]
            total_page = parse_optional_int(paged_records.get("totalPage"))
            total = parse_optional_int(paged_records.get("total"))
            if total_page is None and total is not None:
                total_page = (total + record_page_size - 1) // record_page_size
            self._progress_record_page(
                platform=platform,
                data_type=data_type,
                node_id=node_id,
                user=user,
                user_index=user_index,
                total_users=total_users,
                page=current_page,
                total_page=total_page,
                records=len(content),
                fetched_records=len(content),
                total_records=total,
            )
            if total_page is None or current_page >= total_page:
                paged_records["pages"] = record_pages
                ensure_complete_paged_records(user, paged_records, len(content), total)
                continue

            user_id_or_nick = record_page_user_id_or_nick(user)
            if not user_id_or_nick:
                raise JsonApiError(f"Incomplete pagedRecords: missing user id or nick for {record_label(user)}")

            combined_records = list(content)
            fetched_pages = self._fetch_record_pages(
                platform=platform,
                data_type=data_type,
                start_time=start_time,
                end_time=end_time,
                page_size=record_page_size,
                page_numbers=range(current_page + 1, total_page + 1),
                user_id_or_nick=user_id_or_nick,
                node_id=node_id,
                workers=record_workers,
                resume_dir=resume_dir,
                user_label=record_label(user),
                user_index=user_index,
                total_users=total_users,
                total_page=total_page,
            )
            for next_page, next_paged_records in fetched_pages:
                page_content = next_paged_records.get("content", [])
                if not isinstance(page_content, list):
                    page_content = []
                record_pages.append(
                    page_snapshot(next_paged_records, page_number=next_page, page_size=record_page_size)
                )
                combined_records.extend(page_content)

                next_total = parse_optional_int(next_paged_records.get("total"))
                if next_total is not None:
                    total = next_total
                    paged_records["total"] = next_total
                next_total_page = parse_optional_int(next_paged_records.get("totalPage"))
                if next_total_page is not None:
                    total_page = next_total_page
                    paged_records["totalPage"] = next_total_page
                self._progress_record_page(
                    platform=platform,
                    data_type=data_type,
                    node_id=node_id,
                    user=user,
                    user_index=user_index,
                    total_users=total_users,
                    page=next_page,
                    total_page=total_page,
                    records=len(page_content),
                    fetched_records=len(combined_records),
                    total_records=total,
                )

                if not page_content:
                    break

            paged_records["content"] = combined_records
            paged_records["pages"] = record_pages
            ensure_complete_paged_records(user, paged_records, len(combined_records), total)

    def _fetch_record_pages(
        self,
        *,
        platform: str,
        data_type: str,
        start_time: str,
        end_time: str,
        page_size: int,
        page_numbers: range,
        user_id_or_nick: str,
        node_id: int,
        workers: int,
        resume_dir: Path | None,
        user_label: str,
        user_index: int,
        total_users: int,
        total_page: int | None,
    ) -> list[tuple[int, dict[str, Any]]]:
        pages = list(page_numbers)
        if not pages:
            return []

        def fetch_page(page_number: int) -> tuple[int, dict[str, Any]]:
            page_label = format_count(total_page)
            self._progress(
                f"records page start platform={platform} data_type={data_type} node_id={node_id} "
                f"user={user_label!r} user_index={user_index}/{total_users} page={page_number}/{page_label}"
            )
            started_at = time.monotonic()
            try:
                cached = read_record_page_cache(
                    resume_dir,
                    platform=platform,
                    data_type=data_type,
                    node_id=node_id,
                    user_id_or_nick=user_id_or_nick,
                    start_time=start_time,
                    end_time=end_time,
                    page_size=page_size,
                    page_number=page_number,
                )
                if cached is not None:
                    cached_content = cached.get("content", []) if isinstance(cached, dict) else []
                    if not isinstance(cached_content, list):
                        cached_content = []
                    self._progress(
                        f"records page cache hit platform={platform} data_type={data_type} node_id={node_id} "
                        f"user={user_label!r} user_index={user_index}/{total_users} "
                        f"page={page_number}/{page_label} records={len(cached_content)} "
                        f"elapsed_ms={elapsed_ms(started_at)}"
                    )
                    return page_number, cached

                response = self.fetch_check_single_user(
                    platform=platform,
                    data_type=data_type,
                    start_time=start_time,
                    end_time=end_time,
                    page_size=page_size,
                    page_number=page_number,
                    user_id_or_nick=user_id_or_nick,
                    node_id=node_id,
                )
                paged_records = response.get("data") if isinstance(response.get("data"), dict) else None
                if paged_records is None:
                    raise JsonApiError(
                        f"Incomplete pagedRecords for {user_id_or_nick}: page {page_number} was not returned"
                    )
                write_record_page_cache(
                    resume_dir,
                    paged_records,
                    platform=platform,
                    data_type=data_type,
                    node_id=node_id,
                    user_id_or_nick=user_id_or_nick,
                    start_time=start_time,
                    end_time=end_time,
                    page_size=page_size,
                    page_number=page_number,
                )
                page_content = paged_records.get("content", [])
                if not isinstance(page_content, list):
                    page_content = []
                self._progress(
                    f"records page done platform={platform} data_type={data_type} node_id={node_id} "
                    f"user={user_label!r} user_index={user_index}/{total_users} "
                    f"page={page_number}/{page_label} records={len(page_content)} "
                    f"elapsed_ms={elapsed_ms(started_at)}"
                )
                return page_number, paged_records
            except Exception as error:
                self._progress(
                    f"records page error platform={platform} data_type={data_type} node_id={node_id} "
                    f"user={user_label!r} user_index={user_index}/{total_users} "
                    f"page={page_number}/{page_label} elapsed_ms={elapsed_ms(started_at)} error={error}"
                )
                raise

        max_workers = max(1, int(workers or 1))
        if max_workers == 1 or len(pages) == 1:
            return [fetch_page(page_number) for page_number in pages]

        fetched: list[tuple[int, dict[str, Any]]] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(fetch_page, page_number) for page_number in pages]
            for future in as_completed(futures):
                fetched.append(future.result())
        return sorted(fetched, key=lambda item: item[0])

    def _url(self, path: str) -> str:
        return f"{self.settings.base_url.rstrip('/')}{path}"

    def _progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)

    def _progress_record_page(
        self,
        *,
        platform: str,
        data_type: str,
        node_id: int,
        user: dict[str, Any],
        user_index: int,
        total_users: int,
        page: int,
        total_page: int | None,
        records: int,
        fetched_records: int,
        total_records: int | None,
    ) -> None:
        if total_page is not None and total_page <= 1:
            return
        self._progress(
            f"records page platform={platform} data_type={data_type} node_id={node_id} "
            f"user={record_label(user)!r} user_index={user_index}/{total_users} "
            f"page={page}/{format_count(total_page)} records={records} "
            f"fetched_records={fetched_records} total_records={format_count(total_records)}"
        )


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


def format_count(value: Any) -> str:
    return "?" if value is None else str(value)


def elapsed_ms(started_at: float) -> int:
    return max(0, int((time.monotonic() - started_at) * 1000))


def page_snapshot(data: dict[str, Any], *, page_number: int, page_size: int) -> dict[str, Any]:
    snapshot = copy.deepcopy(data)
    content = snapshot.pop("content", [])
    snapshot["contentCount"] = len(content) if isinstance(content, list) else 0
    snapshot.pop("pages", None)
    snapshot.setdefault("pageNumber", page_number)
    snapshot.setdefault("pageSize", page_size)
    return snapshot


def record_page_cache_path(
    resume_dir: Path | None,
    *,
    platform: str,
    data_type: str,
    node_id: int,
    user_id_or_nick: str,
    start_time: str,
    end_time: str,
    page_size: int,
    page_number: int,
) -> Path | None:
    if resume_dir is None:
        return None
    cache_identity = "\0".join([user_id_or_nick, start_time, end_time, str(page_size)])
    digest = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()[:24]
    return (
        resume_dir
        / safe_cache_part(platform)
        / safe_cache_part(data_type)
        / f"node-{node_id}"
        / digest
        / f"page-{page_number}.json"
    )


def read_record_page_cache(
    resume_dir: Path | None,
    *,
    platform: str,
    data_type: str,
    node_id: int,
    user_id_or_nick: str,
    start_time: str,
    end_time: str,
    page_size: int,
    page_number: int,
) -> dict[str, Any] | None:
    path = record_page_cache_path(
        resume_dir,
        platform=platform,
        data_type=data_type,
        node_id=node_id,
        user_id_or_nick=user_id_or_nick,
        start_time=start_time,
        end_time=end_time,
        page_size=page_size,
        page_number=page_number,
    )
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_record_page_cache(
    resume_dir: Path | None,
    data: dict[str, Any],
    *,
    platform: str,
    data_type: str,
    node_id: int,
    user_id_or_nick: str,
    start_time: str,
    end_time: str,
    page_size: int,
    page_number: int,
) -> None:
    path = record_page_cache_path(
        resume_dir,
        platform=platform,
        data_type=data_type,
        node_id=node_id,
        user_id_or_nick=user_id_or_nick,
        start_time=start_time,
        end_time=end_time,
        page_size=page_size,
        page_number=page_number,
    )
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def safe_cache_part(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)


def build_fetch_all_users_response(
    first_response: dict[str, Any],
    combined_content: list[Any],
    pages: list[dict[str, Any]],
    total: int | None,
) -> dict[str, Any]:
    response = copy.deepcopy(first_response)
    data = response.setdefault("data", {})
    if isinstance(data, dict):
        data["content"] = copy.deepcopy(combined_content)
        data["pages"] = copy.deepcopy(pages)
        if total is not None:
            data["total"] = total
    return response


def ensure_complete_paged_records(
    user: dict[str, Any],
    paged_records: dict[str, Any],
    fetched_count: int,
    total: int | None,
) -> None:
    expected_total = total
    if expected_total is None:
        expected_total = parse_optional_int(paged_records.get("total"))
    if expected_total is not None and fetched_count != expected_total:
        raise JsonApiError(
            f"Incomplete pagedRecords for {record_label(user)}: fetched {fetched_count} of {expected_total}"
        )


def record_label(user: dict[str, Any]) -> str:
    return record_page_user_id_or_nick(user) or "unknown user"


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
    parser.add_argument("--record-workers", type=int, default=1, help="Concurrent per-merchant record page workers. Default: 1.")
    parser.add_argument("--resume-dir", type=Path, help="Cache fetched merchant record pages for resumable runs.")
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
            **({} if args.single_page else {"record_workers": args.record_workers, "resume_dir": args.resume_dir}),
        )
        write_output(args.output, data)
    except JsonApiError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
