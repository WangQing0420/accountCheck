#!/usr/bin/env python3
"""Merge two dated account-check input ranges by platform and bill type."""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence


DATED_DIR_RE = re.compile(r"^(?P<platform>.+)（(?P<start>\d{8})至(?P<end>\d{8})）$")
TIME_FIELDS = [
    "createTime",
    "createdTime",
    "billTime",
    "accountTime",
    "occurTime",
    "payTime",
    "settleTime",
    "gmtCreate",
    "gmtModified",
]
RECORD_ID_FIELDS = [
    "id",
    "billNo",
    "serialNo",
    "flowNo",
    "tradeNo",
    "orderNo",
    "merchantOrderNo",
    "transactionId",
]
FALLBACK_RECORD_FIELDS = [
    "createTime",
    "billTime",
    "accountTime",
    "occurTime",
    "payTime",
    "inAmount",
    "outAmount",
    "amount",
    "businessType",
    "bizType",
    "bizDesc",
    "memo",
    "remark",
]


@dataclass(frozen=True)
class DatedInputDir:
    path: Path
    platform: str
    start: str
    end: str


@dataclass
class MergeStats:
    left_records: int
    right_records: int
    merged_records: int
    duplicates: int
    dedupe_strategy: str
    merchants_before: tuple[int, int]
    merchants_after: int
    conflicts: list[str] = field(default_factory=list)


def parse_dated_input_dir(path: Path) -> DatedInputDir | None:
    match = DATED_DIR_RE.match(path.name)
    if not match:
        return None
    return DatedInputDir(
        path=path,
        platform=match.group("platform"),
        start=match.group("start"),
        end=match.group("end"),
    )


def merge_documents(left: dict[str, Any], right: dict[str, Any]) -> tuple[dict[str, Any], MergeStats]:
    return merge_documents_many([left, right])


def merge_documents_many(documents: Sequence[dict[str, Any]]) -> tuple[dict[str, Any], MergeStats]:
    if not documents:
        raise ValueError("Expected at least one document to merge")

    merged = copy.deepcopy(documents[0])
    merged_data = merged.setdefault("data", {})

    merchant_order: list[tuple[Any, ...]] = []
    merchants_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    merchant_counts: list[int] = []
    record_counts: list[int] = []
    duplicate_count = 0
    key_kinds: set[str] = set()
    conflicts: list[str] = []

    for document in documents:
        data = document.get("data", {})
        merchants = list_content(data)
        merchant_counts.append(len(merchants))
        document_record_count = 0
        for merchant in merchants:
            key = merchant_key(merchant)
            rows = merchant_rows(merchant)
            document_record_count += len(rows)
            if key not in merchants_by_key:
                merchants_by_key[key] = copy.deepcopy(merchant)
                set_merchant_rows(merchants_by_key[key], [])
                merchant_order.append(key)
            target = merchants_by_key[key]
            existing_rows = merchant_rows(target)
            existing_keys = {record_key(key, row)[0]: row for row in existing_rows}
            for row in rows:
                row_key, key_kind = record_key(key, row)
                key_kinds.add(key_kind)
                if row_key in existing_keys:
                    duplicate_count += 1
                    if existing_keys[row_key] != row:
                        conflicts.append(format_conflict(key, row_key))
                    continue
                existing_rows.append(copy.deepcopy(row))
                existing_keys[row_key] = existing_rows[-1]
            set_merchant_rows(target, existing_rows)
        record_counts.append(document_record_count)

    merged_merchants = [merchants_by_key[key] for key in merchant_order]
    for merchant in merged_merchants:
        rows = sorted_rows(merchant_rows(merchant))
        set_merchant_rows(merchant, rows)
        rebuild_paged_records(merchant.setdefault("pagedRecords", {}))

    merged_data["content"] = merged_merchants
    rebuild_outer_data(merged_data)
    stats = MergeStats(
        left_records=record_counts[0],
        right_records=sum(record_counts[1:]),
        merged_records=sum(len(merchant_rows(merchant)) for merchant in merged_merchants),
        duplicates=duplicate_count,
        dedupe_strategy=dedupe_strategy(key_kinds),
        merchants_before=(merchant_counts[0], sum(merchant_counts[1:])),
        merchants_after=len(merged_merchants),
        conflicts=conflicts,
    )
    return merged, stats


def list_content(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    content = value.get("content", [])
    if not isinstance(content, list):
        return []
    return [item for item in content if isinstance(item, dict)]


def merchant_key(merchant: dict[str, Any]) -> tuple[Any, ...]:
    node_id = merchant.get("nodeId")
    user_id = merchant.get("userId")
    nick = merchant.get("nick")
    if node_id not in {None, ""} and user_id not in {None, ""}:
        return ("nodeId+userId", str(node_id), str(user_id))
    if user_id not in {None, ""}:
        return ("userId", str(user_id))
    if node_id not in {None, ""}:
        return ("nodeId", str(node_id))
    if nick not in {None, ""}:
        return ("nick", str(nick))
    return ("merchant", json.dumps(merchant, ensure_ascii=False, sort_keys=True, default=str))


def merchant_rows(merchant: dict[str, Any]) -> list[dict[str, Any]]:
    paged_records = merchant.get("pagedRecords", {})
    if not isinstance(paged_records, dict):
        return []
    content = paged_records.get("content", [])
    if not isinstance(content, list):
        return []
    return [row for row in content if isinstance(row, dict)]


def set_merchant_rows(merchant: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    paged_records = merchant.setdefault("pagedRecords", {})
    if not isinstance(paged_records, dict):
        merchant["pagedRecords"] = {}
        paged_records = merchant["pagedRecords"]
    paged_records["content"] = rows


def record_key(merchant: tuple[Any, ...], row: dict[str, Any]) -> tuple[tuple[Any, ...], str]:
    for field_name in RECORD_ID_FIELDS:
        value = row.get(field_name)
        if value not in {None, ""}:
            return (merchant + (field_name, str(value)), field_name)
    fallback = tuple((field_name, normalize_key_value(row.get(field_name))) for field_name in FALLBACK_RECORD_FIELDS)
    return (merchant + ("fallback", fallback), "fallback")


def normalize_key_value(value: Any) -> str:
    if value in {None, ""}:
        return ""
    return str(value).strip()


def sorted_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = list(enumerate(rows))
    indexed.sort(key=lambda item: (sort_time_value(item[1]), item[0]))
    return [row for _, row in indexed]


def sort_time_value(row: dict[str, Any]) -> str:
    for field_name in TIME_FIELDS:
        value = row.get(field_name)
        if value not in {None, ""}:
            return str(value)
    return "99999999"


def rebuild_paged_records(paged_records: dict[str, Any]) -> None:
    content = paged_records.get("content", [])
    if not isinstance(content, list):
        content = []
        paged_records["content"] = content
    page_size = int_or_default(paged_records.get("pageSize"), 20)
    total = len(content)
    total_page = math.ceil(total / page_size) if total else 0
    paged_records["pageNumber"] = 1
    paged_records["pageSize"] = page_size
    paged_records["total"] = total
    paged_records["totalPage"] = total_page
    paged_records["pages"] = build_pages(total, page_size)


def rebuild_outer_data(data: dict[str, Any]) -> None:
    content = data.get("content", [])
    if not isinstance(content, list):
        content = []
        data["content"] = content
    page_size = int_or_default(data.get("pageSize"), 50)
    total = len(content)
    total_page = math.ceil(total / page_size) if total else 0
    data["pageNumber"] = 1
    data["pageSize"] = page_size
    data["total"] = total
    data["totalPage"] = total_page
    data["pages"] = build_pages(total, page_size)
    if "nodeIds" in data:
        data["nodeIds"] = unique_values(merchant.get("nodeId") for merchant in content if isinstance(merchant, dict))


def build_pages(total: int, page_size: int) -> list[dict[str, int]]:
    if total == 0:
        return []
    total_page = math.ceil(total / page_size)
    pages = []
    for page_number in range(1, total_page + 1):
        if page_number < total_page:
            content_count = page_size
        else:
            content_count = total - page_size * (page_number - 1)
        pages.append(
            {
                "pageNumber": page_number,
                "pageSize": page_size,
                "total": total,
                "totalPage": total_page,
                "contentCount": content_count,
            }
        )
    return pages


def int_or_default(value: Any, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def unique_values(values: Any) -> list[Any]:
    result = []
    seen = set()
    for value in values:
        if value in {None, ""}:
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def dedupe_strategy(key_kinds: set[str]) -> str:
    if key_kinds == {"id"}:
        return "merchant scoped id"
    if not key_kinds:
        return "no records"
    if len(key_kinds) == 1:
        return f"merchant scoped {next(iter(key_kinds))}"
    return "merchant scoped mixed"


def format_conflict(merchant: tuple[Any, ...], row_key: tuple[Any, ...]) -> str:
    return f"merchant={merchant!r} record_key={row_key!r}"


def merge_input_directories(input_root: Path) -> list[tuple[Path, Path, Path, MergeStats]]:
    dated_dirs = [parsed for path in sorted(input_root.iterdir()) if path.is_dir() for parsed in [parse_dated_input_dir(path)] if parsed]
    by_platform: dict[str, list[DatedInputDir]] = {}
    for dated_dir in dated_dirs:
        by_platform.setdefault(dated_dir.platform, []).append(dated_dir)

    merged_files: list[tuple[Path, Path, Path, MergeStats]] = []
    for platform, platform_dirs in sorted(by_platform.items()):
        source_dirs = select_source_dirs(platform_dirs)
        if len(source_dirs) < 2:
            print(f"SKIPPED {platform}: expected at least 2 source dated directories, found {len(source_dirs)}")
            continue
        ordered_dirs = sorted(source_dirs, key=lambda item: (item.start, item.end))
        output_dir = input_root / f"{platform}（{ordered_dirs[0].start}至{ordered_dirs[-1].end}）"
        files_by_dir = [
            {path.name: path for path in dated_dir.path.glob("*.json") if path.is_file()}
            for dated_dir in ordered_dirs
        ]
        common_filenames = set(files_by_dir[0])
        for files in files_by_dir[1:]:
            common_filenames &= set(files)
        for filename in sorted(common_filenames):
            source_paths = [files[filename] for files in files_by_dir]
            output_path = output_dir / filename
            stats = merge_files(source_paths, output_path)
            merged_files.append((source_paths[0], source_paths[-1], output_path, stats))
            print_audit(source_paths, output_path, stats)
        all_filenames = set().union(*(set(files) for files in files_by_dir))
        for filename in sorted(all_filenames - common_filenames):
            print(f"SKIPPED {platform}/{filename}")
            print("  reason: file is not present in every source range")
    return merged_files


def select_source_dirs(platform_dirs: list[DatedInputDir]) -> list[DatedInputDir]:
    if len(platform_dirs) <= 2:
        return platform_dirs
    min_start = min(item.start for item in platform_dirs)
    max_end = max(item.end for item in platform_dirs)
    without_full_span = [item for item in platform_dirs if item.start != min_start or item.end != max_end]
    if len(without_full_span) >= 2:
        return without_full_span
    return platform_dirs


def merge_files(source_paths: list[Path], output_path: Path) -> MergeStats:
    documents = [json.loads(path.read_text(encoding="utf-8")) for path in source_paths]
    if not all(isinstance(document, dict) for document in documents):
        raise ValueError(f"Expected JSON objects: {', '.join(str(path) for path in source_paths)}")
    merged, stats = merge_documents_many(documents)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return stats


def print_audit(source_paths: list[Path], output_path: Path, stats: MergeStats) -> None:
    print(f"MERGED {output_path}")
    for index, source_path in enumerate(source_paths, start=1):
        print(f"  source{index}: {source_path}")
    print(f"  merchants: {stats.merchants_before[0]} + {stats.merchants_before[1]} -> {stats.merchants_after}")
    print(f"  records: {stats.left_records} + {stats.right_records} = {stats.left_records + stats.right_records} raw")
    print(f"  duplicates: {stats.duplicates}")
    print(f"  merged records: {stats.merged_records}")
    print(f"  dedupe strategy: {stats.dedupe_strategy}")
    for conflict in stats.conflicts:
        print("WARNING duplicate key has different content")
        print(f"  duplicate key: {conflict}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge dated account-check input ranges.")
    parser.add_argument("--input-root", type=Path, default=Path("inputs"), help="Input root directory. Default: inputs.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.input_root.is_dir():
        raise FileNotFoundError(f"Input root not found: {args.input_root}")
    merge_input_directories(args.input_root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
