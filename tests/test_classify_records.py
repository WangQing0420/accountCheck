import json
import tempfile
import unittest
from pathlib import Path

from classify_records import classify_rows, infer_split_output_paths, main, render_report


class ClassifyRowsTests(unittest.TestCase):
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
        self.assertTrue(largest.classification_required)
        self.assertTrue(largest.platform_fee_candidate)
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
        self.assertFalse(groups[0].classification_required)
        self.assertFalse(groups[0].platform_fee_candidate)
        self.assertIn("缺少有效业务描述", groups[0].assessment_reasons)

    def test_marks_settlement_income_as_classification_required_but_not_platform_fee(self):
        rows = [
            {"id": "1", "memo": "订单货款结算收入1234567890123456", "inAmount": 100},
            {"id": "2", "memo": "订单货款结算收入2234567890123456", "inAmount": 200},
        ]

        groups = classify_rows(rows)

        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0].classification_required)
        self.assertFalse(groups[0].platform_fee_candidate)
        self.assertIn("货款/结算收入", groups[0].assessment_reasons)

    def test_renders_empty_input_as_empty_report(self):
        report = render_report([], source_name="empty.json")

        self.assertIn("输入文件: `empty.json`", report)
        self.assertIn("输入行数: `0`", report)
        self.assertIn("无可归类记录。", report)


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
            self.assertIn("- 账单归类: `需要`", report)
            self.assertIn("- 平台费用: `候选`", report)
            self.assertIn("- 支出合计: `70`", report)
            self.assertIn("- memo: `基础软件服务费(*)`", report)

    def test_short_split_command_writes_marker_reports_under_platform_directory(self):
        data = {
            "success": True,
            "data": {
                "content": [
                    {
                        "pagedRecords": {
                            "content": [
                                {"id": "1", "memo": "基础软件服务费(1234567890123456)", "outAmount": 30},
                                {"id": "2", "memo": "订单货款结算收入1234567890123456", "inAmount": 100},
                                {"id": "3", "memo": "2026050400003001300084143540", "businessType": "other"},
                            ]
                        }
                    }
                ]
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            input_dir = root / "inputs" / "taobao"
            input_dir.mkdir(parents=True)
            input_path = input_dir / "taobao_check_result.json"
            input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            exit_code = main([str(input_path), "--split", "--output-root", str(root / "outputs")])

            self.assertEqual(exit_code, 0)
            output_dir = root / "outputs" / "taobao" / "taobao_check_result"
            self.assertTrue((output_dir / "all.md").exists())
            platform_fee = (output_dir / "classification_required_platform_fee.md").read_text(encoding="utf-8")
            non_platform_fee = (output_dir / "classification_required_non_platform_fee.md").read_text(encoding="utf-8")
            no_classification = (output_dir / "no_classification_non_platform_fee.md").read_text(encoding="utf-8")
            self.assertIn("基础软件服务费(*)", platform_fee)
            self.assertIn("订单货款结算收入*", non_platform_fee)
            self.assertIn("账单归类: `不需要`", no_classification)

    def test_infer_split_output_paths_uses_parent_platform_and_input_stem(self):
        paths = infer_split_output_paths(Path("inputs/taobao/taobao_check_result.json"), Path("outputs"))

        self.assertEqual(
            paths["classification_required_platform_fee"],
            Path("outputs/taobao/taobao_check_result/classification_required_platform_fee.md"),
        )


if __name__ == "__main__":
    unittest.main()
