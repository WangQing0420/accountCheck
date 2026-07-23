import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from merge_input_ranges import main, merge_documents, merge_documents_many


def make_document(merchants):
    return {
        "success": True,
        "code": 0,
        "message": "OK",
        "data": {
            "content": merchants,
            "pageNumber": 1,
            "pageSize": 50,
            "total": len(merchants),
            "totalPage": 1,
            "pages": [
                {
                    "pageNumber": 1,
                    "pageSize": 50,
                    "total": len(merchants),
                    "totalPage": 1,
                    "contentCount": len(merchants),
                }
            ],
            "nodeIds": [merchant["nodeId"] for merchant in merchants if "nodeId" in merchant],
        },
    }


def make_merchant(user_id, nick, node_id, rows):
    return {
        "userId": user_id,
        "nick": nick,
        "nodeId": node_id,
        "pagedRecords": {
            "content": rows,
            "pageNumber": 1,
            "pageSize": 2,
            "total": len(rows),
            "totalPage": 1,
            "pages": [
                {
                    "pageNumber": 1,
                    "pageSize": 2,
                    "total": len(rows),
                    "totalPage": 1,
                    "contentCount": len(rows),
                }
            ],
        },
    }


class MergeDocumentsTests(unittest.TestCase):
    def test_merges_three_documents_and_rebuilds_metadata(self):
        documents = [
            make_document([make_merchant("u1", "店铺A", 11, [{"id": "1"}])]),
            make_document([make_merchant("u1", "店铺A", 11, [{"id": "2"}])]),
            make_document([make_merchant("u1", "店铺A", 11, [{"id": "2"}, {"id": "3"}])]),
        ]

        merged, stats = merge_documents_many(documents)

        self.assertEqual(
            [row["id"] for row in merged["data"]["content"][0]["pagedRecords"]["content"]],
            ["1", "2", "3"],
        )
        self.assertEqual(stats.left_records, 1)
        self.assertEqual(stats.right_records, 3)
        self.assertEqual(stats.duplicates, 1)
        self.assertEqual(stats.merged_records, 3)

    def test_merges_same_merchant_records_and_dedupes_by_id(self):
        left = make_document(
            [
                make_merchant(
                    "u1",
                    "店铺A",
                    11,
                    [
                        {"id": "1", "createTime": "2026-06-11 10:00:00", "inAmount": "10"},
                        {"id": "2", "createTime": "2026-06-12 10:00:00", "inAmount": "20"},
                    ],
                )
            ]
        )
        right = make_document(
            [
                make_merchant(
                    "u1",
                    "店铺A",
                    11,
                    [
                        {"id": "2", "createTime": "2026-06-12 10:00:00", "inAmount": "20"},
                        {"id": "3", "createTime": "2026-06-25 10:00:00", "inAmount": "30"},
                    ],
                )
            ]
        )

        merged, stats = merge_documents(left, right)

        merchant = merged["data"]["content"][0]
        rows = merchant["pagedRecords"]["content"]
        self.assertEqual([row["id"] for row in rows], ["1", "2", "3"])
        self.assertEqual(merchant["pagedRecords"]["total"], 3)
        self.assertEqual(merchant["pagedRecords"]["totalPage"], 2)
        self.assertEqual(merchant["pagedRecords"]["pages"][-1]["contentCount"], 1)
        self.assertEqual(merged["data"]["total"], 1)
        self.assertEqual(stats.left_records, 2)
        self.assertEqual(stats.right_records, 2)
        self.assertEqual(stats.duplicates, 1)
        self.assertEqual(stats.merged_records, 3)
        self.assertEqual(stats.dedupe_strategy, "merchant scoped id")

    def test_adds_new_merchants_and_rebuilds_outer_pages(self):
        left = make_document([make_merchant("u1", "店铺A", 11, [{"id": "1"}])])
        right = make_document([make_merchant("u2", "店铺B", 12, [{"id": "2"}])])

        merged, stats = merge_documents(left, right)

        self.assertEqual([merchant["nick"] for merchant in merged["data"]["content"]], ["店铺A", "店铺B"])
        self.assertEqual(merged["data"]["total"], 2)
        self.assertEqual(merged["data"]["pages"][0]["contentCount"], 2)
        self.assertEqual(merged["data"]["nodeIds"], [11, 12])
        self.assertEqual(stats.merchants_before, (1, 1))
        self.assertEqual(stats.merchants_after, 2)


class CliTests(unittest.TestCase):
    def test_main_merges_three_source_ranges_and_ignores_existing_full_span(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ranges = [("20260601", "20260615"), ("20260616", "20260630"), ("20260701", "20260701")]
            filename = "淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json"
            for index, (start, end) in enumerate(ranges, start=1):
                source_dir = root / "inputs" / f"淘宝（{start}至{end}）"
                source_dir.mkdir(parents=True)
                (source_dir / filename).write_text(
                    json.dumps(
                        make_document([make_merchant("u1", "店铺A", 11, [{"id": str(index)}])]),
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            existing_output_dir = root / "inputs" / "淘宝（20260601至20260701）"
            existing_output_dir.mkdir(parents=True)
            (existing_output_dir / filename).write_text("{}", encoding="utf-8")

            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with redirect_stdout(StringIO()):
                    exit_code = main([])
            finally:
                os.chdir(old_cwd)

            output = json.loads((existing_output_dir / filename).read_text(encoding="utf-8"))
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                [row["id"] for row in output["data"]["content"][0]["pagedRecords"]["content"]],
                ["1", "2", "3"],
            )

    def test_main_merges_matching_dated_directories_and_prints_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left_dir = root / "inputs" / "拼多多（20260611至20260624）"
            right_dir = root / "inputs" / "拼多多（20260625至20260707）"
            left_dir.mkdir(parents=True)
            right_dir.mkdir(parents=True)
            filename = "拼多多-货款账单-PDD_MALL_ACCOUNT_RECORD.json"
            (left_dir / filename).write_text(
                json.dumps(make_document([make_merchant("u1", "店铺A", 11, [{"id": "1"}])]), ensure_ascii=False),
                encoding="utf-8",
            )
            (right_dir / filename).write_text(
                json.dumps(make_document([make_merchant("u1", "店铺A", 11, [{"id": "2"}])]), ensure_ascii=False),
                encoding="utf-8",
            )
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main([])
            finally:
                os.chdir(old_cwd)

            output_dir = root / "inputs" / "拼多多（20260611至20260707）"
            output_path = output_dir / filename
            self.assertEqual(exit_code, 0)
            self.assertTrue(output_path.exists())
            self.assertFalse((output_dir / "_merge_audit.json").exists())
            self.assertIn("MERGED inputs/拼多多（20260611至20260707）/拼多多-货款账单-PDD_MALL_ACCOUNT_RECORD.json", stdout.getvalue())
            self.assertIn("duplicates: 0", stdout.getvalue())

    def test_main_ignores_existing_merged_span_when_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left_dir = root / "inputs" / "拼多多（20260611至20260624）"
            right_dir = root / "inputs" / "拼多多（20260625至20260707）"
            existing_output_dir = root / "inputs" / "拼多多（20260611至20260707）"
            left_dir.mkdir(parents=True)
            right_dir.mkdir(parents=True)
            existing_output_dir.mkdir(parents=True)
            filename = "拼多多-货款账单-PDD_MALL_ACCOUNT_RECORD.json"
            (left_dir / filename).write_text(
                json.dumps(make_document([make_merchant("u1", "店铺A", 11, [{"id": "1"}])]), ensure_ascii=False),
                encoding="utf-8",
            )
            (right_dir / filename).write_text(
                json.dumps(make_document([make_merchant("u1", "店铺A", 11, [{"id": "2"}])]), ensure_ascii=False),
                encoding="utf-8",
            )
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                stdout = StringIO()
                with redirect_stdout(stdout):
                    exit_code = main([])
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 0)
            self.assertIn("MERGED inputs/拼多多（20260611至20260707）/拼多多-货款账单-PDD_MALL_ACCOUNT_RECORD.json", stdout.getvalue())
            self.assertNotIn("expected 2 dated directories, found 3", stdout.getvalue())
