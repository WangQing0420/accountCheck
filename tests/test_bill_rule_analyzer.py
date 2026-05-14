import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from bill_rule_analyzer import (
    Rule,
    load_rows,
    parse_account_expense_types,
    parse_account_record_rules,
    render_report,
)


class RuleParserTests(unittest.TestCase):
    def test_parses_account_record_type_entries(self):
        content = textwrap.dedent(
            """
            AccountRecordType.transaction do
              {
                  1020 => { name: '运费险（保险账单）', match_rule: { insurance_product: '退换货运费险' }, expense_type_id: 10021, source_type: :DOU_INSURANCE_BILL, sort_order: 1000 },
                  20215 => { name: '物流轨迹超时-揽运超时赔付', match_rule: { remark: '物流轨迹超时-揽运超时赔付.*' }, extract_rule: { tid: { REMARK: '.*(P\\d+)' } }, expense_type_id: 20032, source_type: :XHS_SELLER_ACCOUNT_RECORD, sort_order: 20215, status: -1 },
                  10000000 => { name: '其他', source_type: :UNKNOWN, sort_order: 99999999 },
              }.each do |id, params|
              end
            end
            """
        )

        rules = parse_account_record_rules(content, platform="dou")

        self.assertEqual([rule.id for rule in rules], [1020, 20215, 10000000])
        self.assertEqual(rules[0].name, "运费险（保险账单）")
        self.assertEqual(rules[0].match_rule, {"INSURANCE_PRODUCT": "退换货运费险"})
        self.assertEqual(rules[0].expense_type_id, 10021)
        self.assertEqual(rules[0].source_type, "DOU_INSURANCE_BILL")
        self.assertEqual(rules[1].extract_rule, {"TID": {"REMARK": ".*(P\\d+)"}})
        self.assertEqual(rules[1].status, -1)

    def test_rule_matches_source_type_and_regex_fields(self):
        rule = Rule(
            id=1020,
            name="运费险",
            match_rule={"INSURANCE_PRODUCT": "退换货运费险"},
            extract_rule={},
            expense_type_id=10021,
            source_type="DOU_INSURANCE_BILL",
            sort_order=1000,
            status=1,
        )

        self.assertTrue(rule.matches({"insurance_product": "退换货运费险"}, "DOU_INSURANCE_BILL"))
        self.assertFalse(rule.matches({"insurance_product": "大件退换货运费险"}, "DOU_INSURANCE_BILL"))
        self.assertFalse(rule.matches({"insurance_product": "退换货运费险"}, "DOU_DEPOSIT_BILL"))

    def test_parses_taobao_variable_style_account_record_types(self):
        content = textwrap.dedent(
            """
            account_record_types = {
              130100 => { name: '基础软件服务费', match_rule: { memo: '(代扣款（扣款用途：)?基础软件服务费.*' }, expense_type_id: 1301, source_type: :all, sort_order: 90 },
            }

            AccountRecordType.transaction do
              account_record_types.each do |id, params|
              end
            end
            """
        )

        rules = parse_account_record_rules(content, platform="taobao")

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].source_type, "all")
        self.assertTrue(rules[0].matches({"memo": "基础软件服务费调整"}, "TAOBAO_ACCOUNT_RECORD"))

    def test_parses_account_expense_type_parent_and_child_names(self):
        content = textwrap.dedent(
            """
            account_expense_types = [
              { parent_id: 1000, parent_name: '平台扣点', actives: [
                { types: [[1301, '基础软件服务费'], [1001, '天猫佣金', { is_b: true }], [3090, '直播回放服务费', parent_cost_type_id: 23]] },
              ], inactives: [
                { types: [[1020, '垂直积分']] },
              ] },
              { parent_id: 3000, parent_name: '营销费', actives: [
                { types: [[3001, '淘客佣金']] },
              ] },
            ]
            """
        )

        expense_types = parse_account_expense_types(content)

        self.assertEqual(expense_types[1301].name, "基础软件服务费")
        self.assertEqual(expense_types[1301].parent_name, "平台扣点")
        self.assertEqual(expense_types[1001].name, "天猫佣金")
        self.assertEqual(expense_types[1001].parent_name, "平台扣点")
        self.assertEqual(expense_types[3090].name, "直播回放服务费")
        self.assertEqual(expense_types[3090].parent_name, "平台扣点")
        self.assertEqual(expense_types[3001].name, "淘客佣金")
        self.assertEqual(expense_types[3001].parent_name, "营销费")


class InputAndReportTests(unittest.TestCase):
    def test_loads_check_result_json_rows(self):
        data = {
            "success": True,
            "code": 200,
            "message": "OK",
            "data": {
                "content": [
                    {
                        "userId": 1,
                        "nick": "demo",
                        "pagedRecords": {
                            "content": [
                                {"id": "1", "insurance_product": "新保险"},
                                {"id": "2", "insurance_product": "旧保险"},
                            ]
                        },
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

        self.assertEqual(rows, [{"id": "1", "insurance_product": "新保险"}, {"id": "2", "insurance_product": "旧保险"}])

    def test_report_groups_unmatched_rows_and_renders_seed_snippet(self):
        rows = [
            {"id": "1", "insurance_product": "新保险"},
            {"id": "2", "insurance_product": "新保险"},
        ]
        report = render_report(rows=rows, rules=[], platform="dou", source_type="DOU_INSURANCE_BILL")

        self.assertIn("未归类分组", report)
        self.assertIn("新保险", report)
        self.assertIn("source_type: :DOU_INSURANCE_BILL", report)
        self.assertIn("expense_type_id: TODO", report)


if __name__ == "__main__":
    unittest.main()
