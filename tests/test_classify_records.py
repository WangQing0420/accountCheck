import json
import tempfile
import unittest
from pathlib import Path

from classify_records import build_group_name, classify_rows, infer_split_output_paths, main, render_report, select_template_path


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

    def test_excludes_personal_freeform_memos_from_classification(self):
        rows = [
            {"id": "1", "memo": "从容里衣服工厂货款", "businessType": "其它", "outAmount": 100},
            {"id": "2", "memo": "5.9和5.10退货", "businessType": "other", "inAmount": 100},
            {"id": "3", "memo": "还贷款", "businessType": "other", "outAmount": 100},
        ]

        groups = classify_rows(rows)

        self.assertEqual(len(groups), 3)
        for group in groups:
            self.assertFalse(group.classification_required)
            self.assertFalse(group.platform_fee_candidate)
            self.assertIn("个人/非店铺流水", group.assessment_reasons)

    def test_keeps_store_fund_flows_classification_required_but_not_platform_fee(self):
        rows = [
            {"id": "1", "memo": "mlu", "businessType": "提现", "outAmount": 100},
            {"id": "2", "memo": "交易货款1234567890123456", "businessType": "交易分账", "inAmount": 100},
            {"id": "3", "memo": "商家权益红包-资金方案支付充值-商家权益账户", "businessType": "其它", "outAmount": 100},
        ]

        groups = classify_rows(rows)

        self.assertEqual(len(groups), 3)
        for group in groups:
            self.assertTrue(group.classification_required)
            self.assertFalse(group.platform_fee_candidate)

    def test_marks_only_strong_fee_signals_as_platform_fee_candidates(self):
        rows = [
            {"id": "1", "memo": "保险承保-安心充电险保费收取-订单号［1234567890123456]", "businessType": "其它", "outAmount": 10},
            {"id": "2", "memo": "淘宝穿搭推广服务费(1234567890123456)扣款", "businessType": "other", "outAmount": 20},
            {"id": "3", "memo": "预约转账", "businessType": "其它", "outAmount": 30},
            {"id": "4", "memo": "卓梵推广预支", "businessType": "other", "outAmount": 40},
            {"id": "5", "memo": "嘉年华推广预支", "businessType": "other", "outAmount": 50},
        ]

        groups = classify_rows(rows)
        by_memo = {group.normalized_fields["memo"]: group for group in groups}

        self.assertTrue(by_memo["保险承保-安心充电险保费收取-订单号［*]"].platform_fee_candidate)
        self.assertTrue(by_memo["淘宝穿搭推广服务费(*)扣款"].platform_fee_candidate)
        self.assertFalse(by_memo["预约转账"].classification_required)
        self.assertFalse(by_memo["预约转账"].platform_fee_candidate)
        self.assertFalse(by_memo["卓梵推广预支"].classification_required)
        self.assertFalse(by_memo["卓梵推广预支"].platform_fee_candidate)
        self.assertFalse(by_memo["嘉年华推广预支"].classification_required)
        self.assertFalse(by_memo["嘉年华推广预支"].platform_fee_candidate)

    def test_renders_empty_input_as_empty_report(self):
        report = render_report([], source_name="empty.json")

        self.assertIn("输入文件: `empty.json`", report)
        self.assertIn("输入行数: `0`", report)
        self.assertIn("无可归类记录。", report)

    def test_builds_readable_candidate_names_without_id_placeholders(self):
        cases = [
            ("淘宝穿搭推广服务费(*)扣款", "淘宝穿搭推广服务费"),
            ("消费券价格管控补贴扣回(*)扣款", "消费券价格管控补贴扣回"),
            ("保险承保-安心充电险保费收取-订单号［*]", "安心充电险保费"),
            ("代扣款（扣款用途：极速基础运费_*，付款方：深圳市栩琛科技有限公司）", "极速基础运费"),
            ("代扣款（扣款用途：闪购仓-高周转仓租（*）扣款）", "闪购仓-高周转仓租"),
            ("代扣款（扣款用途：消费券价格管控补贴扣回(*)退款，付款方：浙江天猫技术有限公司）", "消费券价格管控补贴扣回退款"),
            ("1688官方寄件退货服务费(供应链 运单号:*)", "1688官方寄件退货服务费"),
        ]

        for memo, expected_name in cases:
            with self.subTest(memo=memo):
                group = classify_rows([{"id": "1", "memo": memo, "outAmount": 1}])[0]

                self.assertEqual(build_group_name(group), expected_name)


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
            self.assertIn("# 平台费用检查 - 淘宝 - 通用账单 - 平台费用模板", platform_fee)
            self.assertIn("| 平台费用名称 | 科目 | 账单归类名称 |", platform_fee)
            self.assertIn("| {平台费用名称} | {科目} | 基础软件服务费 |", platform_fee)
            self.assertIn("样例ID: 1", platform_fee)
            self.assertNotIn("### 分组", platform_fee)
            self.assertIn("# 平台费用检查 - 淘宝 - 通用账单 - 资金分析模板", non_platform_fee)
            self.assertIn("| 订单货款结算收入 |", non_platform_fee)
            self.assertIn("样例ID: 2", non_platform_fee)
            self.assertIn("账单归类: `不需要`", no_classification)

    def test_split_report_reuses_existing_rule_names_and_marks_new_candidates(self):
        data = {
            "success": True,
            "data": {
                "content": [
                    {
                        "pagedRecords": {
                            "content": [
                                {"id": "1", "memo": "基础软件服务费(1234567890123456)", "outAmount": 30},
                                {"id": "2", "memo": "新平台服务费(1234567890123456)", "outAmount": 10},
                            ]
                        }
                    }
                ]
            },
        }
        seed_content = """
account_expense_types = [
  { parent_id: 1000, parent_name: '平台扣点', actives: [
    { types: [[1301, '基础软件服务费']] },
  ] },
]

account_record_types = {
  130100 => { name: '基础软件服务费归类', match_rule: { memo: '基础软件服务费.*' }, expense_type_id: 1301, source_type: :TAOBAO_ACCOUNT_RECORD, sort_order: 90 },
}
"""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rails_seed_dir = root / "rails" / "db" / "seeds" / "static" / "taobao"
            rails_seed_dir.mkdir(parents=True)
            (rails_seed_dir / "account_expense_type.seeds.rb").write_text(seed_content, encoding="utf-8")
            input_dir = root / "inputs" / "taobao"
            input_dir.mkdir(parents=True)
            input_path = input_dir / "taobao_check_result.json"
            input_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            fetch_jobs_path = root / "fetch_jobs.json"
            fetch_jobs_path.write_text(
                json.dumps(
                    {
                        "jobs": {
                            "taobao": {
                                "platform": "TAOBAO",
                                "source_type": "TAOBAO_ACCOUNT_RECORD",
                                "output": str(input_path),
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            exit_code = main([
                str(input_path),
                "--split",
                "--output-root",
                str(root / "outputs"),
                "--rails-root",
                str(root / "rails"),
                "--fetch-jobs",
                str(fetch_jobs_path),
            ])

            self.assertEqual(exit_code, 0)
            report = (
                root
                / "outputs"
                / "taobao"
                / "taobao_check_result"
                / "classification_required_platform_fee.md"
            ).read_text(encoding="utf-8")
            self.assertIn("| 基础软件服务费 | 平台扣点 | 基础软件服务费归类 |", report)
            self.assertIn("已命中规则: 130100", report)
            self.assertIn("expense_type_id=1301", report)
            self.assertIn("| {平台费用名称} | {科目} | 新平台服务费 |", report)
            self.assertIn("新增候选", report)

    def test_infer_split_output_paths_uses_parent_platform_and_input_stem(self):
        paths = infer_split_output_paths(Path("inputs/taobao/taobao_check_result.json"), Path("outputs"))

        self.assertEqual(
            paths["classification_required_platform_fee"],
            Path("outputs/taobao/taobao_check_result/classification_required_platform_fee.md"),
        )

    def test_select_template_path_uses_platform_aliases_and_bill_name_hints(self):
        cases = [
            (
                "inputs/dou/dou_insurance_bill_check_result.json",
                "平台费用检查-抖店-保险费明细-平台费用模板.md",
            ),
            (
                "inputs/wxxd/wxxd_funds_flow_detail_check_result.json",
                "平台费用检查-微信小店-资金流水账单-平台费用模板.md",
            ),
            (
                "inputs/alibaba/alibaba_alipay_account_record_check_result.json",
                "平台费用检查-1688-支付宝账单-平台费用模板.md",
            ),
            (
                "inputs/pdd/pdd_mall_account_record_check_result.json",
                "平台费用检查-拼多多-货款账单-平台费用模板.md",
            ),
            (
                "inputs/pdd/pdd_marketing_account_record_check_result.json",
                "平台费用检查-拼多多-营销账单-平台费用模板.md",
            ),
        ]

        for input_name, template_name in cases:
            with self.subTest(input_name=input_name):
                path = select_template_path(
                    "classification_required_platform_fee",
                    Path(input_name),
                )

                self.assertIsNotNone(path)
                self.assertEqual(path.name, template_name)

    def test_select_template_path_does_not_guess_when_bill_name_has_no_template_hint(self):
        path = select_template_path(
            "classification_required_platform_fee",
            Path("inputs/dou/dou_qianchuan_item_ad_record_check_result.json"),
        )

        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
