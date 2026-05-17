import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from classify_records import (
    classify_rows,
    load_rows,
    main,
    render_report,
)


class ClassifyRowsTests(unittest.TestCase):
    def test_loads_check_result_json_rows(self):
        data = {
            "success": True,
            "data": {
                "content": [
                    {
                        "pagedRecords": {
                            "content": [
                                {"id": "1", "memo": "第一条"},
                                {"id": "2", "memo": "第二条"},
                            ]
                        }
                    }
                ]
            },
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
            path = Path(handle.name)

        try:
            rows = load_rows(path)
        finally:
            path.unlink()

        self.assertEqual(rows, [{"id": "1", "memo": "第一条"}, {"id": "2", "memo": "第二条"}])

    def test_groups_memos_that_only_differ_by_long_ids(self):
        rows = [
            {
                "id": "1",
                "memo": "淘宝穿搭推广服务费(5112558363717031319)扣款",
                "businessType": "other",
                "outAmount": 5,
            },
            {
                "id": "2",
                "memo": "淘宝穿搭推广服务费(6112558363717031318)扣款",
                "businessType": "other",
                "outAmount": 7,
            },
            {
                "id": "3",
                "memo": "基础软件服务费(1234567890123456)扣款",
                "businessType": "other",
                "outAmount": 3,
            },
        ]

        groups = classify_rows(rows)

        self.assertEqual(len(groups), 2)
        largest = groups[0]
        self.assertEqual(largest.count, 2)
        self.assertEqual(largest.out_amount, 12)
        self.assertEqual(largest.normalized_fields["memo"], "淘宝穿搭推广服务费(*)扣款")
        self.assertEqual(largest.normalized_fields["businessType"], "other")
        self.assertIn("淘宝穿搭推广服务费(5112558363717031319)扣款", largest.examples["memo"])

    def test_keeps_different_business_descriptions_separate(self):
        rows = [
            {"id": "1", "bizDesc": "售后退款订单1234567890123456", "inAmount": 10},
            {"id": "2", "bizDesc": "售后退款订单2234567890123456", "inAmount": 11},
            {"id": "3", "bizDesc": "平台补贴订单3234567890123456", "inAmount": 12},
        ]

        groups = classify_rows(rows)

        self.assertEqual(len(groups), 2)
        self.assertEqual(groups[0].normalized_fields["bizDesc"], "售后退款订单*")
        self.assertEqual(groups[0].in_amount, 21)
        self.assertEqual(groups[1].normalized_fields["bizDesc"], "平台补贴订单*")

    def test_ignores_description_field_that_is_only_a_long_id(self):
        rows = [
            {"id": "1", "memo": "2026050400003001300084143540", "businessType": "other"},
            {"id": "2", "memo": "2701793282064007080", "businessType": "other"},
        ]

        groups = classify_rows(rows)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].normalized_fields, {"businessType": "other"})

    def test_renders_empty_input_as_empty_report(self):
        report = render_report([], source_name="empty.json")

        self.assertIn("输入文件: `empty.json`", report)
        self.assertIn("输入行数: `0`", report)
        self.assertIn("无可分组记录。", report)

    def test_report_only_contains_grouping_and_aggregation_fields(self):
        report = render_report(
            [
                {"id": "1", "memo": "基础软件服务费(1234567890123456)", "outAmount": 30},
                {"id": "2", "memo": "基础软件服务费(2234567890123456)", "outAmount": 40},
            ],
            source_name="input.json",
        )

        self.assertIn("### 分组 1: 2 行", report)
        self.assertIn("- 支出合计: `70`", report)
        self.assertIn("- memo: `基础软件服务费(*)`", report)


class CliTests(unittest.TestCase):
    def test_main_writes_report_for_check_result_json(self):
        data = {
            "success": True,
            "data": {
                "content": [
                    {
                        "pagedRecords": {
                            "content": [
                                {"id": "1", "memo": "基础软件服务费(1234567890123456)", "outAmount": 30},
                                {"id": "2", "memo": "基础软件服务费(2234567890123456)", "outAmount": 40},
                            ]
                        }
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "input.json"
            output_path = Path(directory) / "report.md"
            input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            exit_code = main(["--input", str(input_path), "--output", str(output_path)])

            self.assertEqual(exit_code, 0)
            report = output_path.read_text(encoding="utf-8")
            self.assertIn("### 分组 1: 2 行", report)
            self.assertIn("- 支出合计: `70`", report)
            self.assertIn("- memo: `基础软件服务费(*)`", report)

    def test_main_writes_reports_for_chinese_platform_name(self):
        data = {
            "success": True,
            "data": {
                "content": [
                    {
                        "pagedRecords": {
                            "content": [
                                {"id": "1", "memo": "基础软件服务费(1234567890123456)", "outAmount": 30},
                            ]
                        }
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "inputs" / "淘宝"
            input_dir.mkdir(parents=True)
            (input_dir / "淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json").write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with redirect_stdout(StringIO()):
                    exit_code = main(["淘宝"])
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 0)
            report_path = root / "outputs" / "淘宝" / "淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.md"
            self.assertTrue(report_path.exists())
            self.assertIn("基础软件服务费(*)", report_path.read_text(encoding="utf-8"))

    def test_main_writes_reports_for_platform_alias(self):
        data = {
            "success": True,
            "data": {
                "content": [
                    {
                        "pagedRecords": {
                            "content": [
                                {"id": "1", "memo": "订单货款1234567890123456", "inAmount": 50},
                            ]
                        }
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "inputs" / "淘宝"
            input_dir.mkdir(parents=True)
            (input_dir / "淘宝-聚合结算账单明细-TB_WHALE_ACCOUNT_RECORD.json").write_text(
                json.dumps(data, ensure_ascii=False),
                encoding="utf-8",
            )
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with redirect_stdout(StringIO()):
                    exit_code = main(["taobao"])
            finally:
                os.chdir(old_cwd)

            self.assertEqual(exit_code, 0)
            report_path = root / "outputs" / "淘宝" / "淘宝-聚合结算账单明细-TB_WHALE_ACCOUNT_RECORD.md"
            self.assertTrue(report_path.exists())
            self.assertIn("订单货款*", report_path.read_text(encoding="utf-8"))

    def test_output_is_rejected_for_platform_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "inputs" / "淘宝").mkdir(parents=True)
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with self.assertRaises(SystemExit):
                    main(["淘宝", "--output", "one.md"])
            finally:
                os.chdir(old_cwd)


if __name__ == "__main__":
    unittest.main()
