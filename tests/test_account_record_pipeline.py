import json
import tempfile
import unittest
from pathlib import Path

from account_record_pipeline import format_summary, resolve_target_job_names, run_pipeline


class FakeFetcher:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def fetch_check_all_users(self, **kwargs):
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("unexpected fetch call")
        return self.responses.pop(0)


class TargetResolutionTests(unittest.TestCase):
    def test_resolve_target_job_names_supports_all_and_platform_alias(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "fetch_jobs.json"
            config_path.write_text(
                json.dumps(
                    {
                        "jobs": {
                            "taobao_a": {"platform": "TAOBAO", "data_type": "TAOBAO_ACCOUNT_RECORD", "output": "inputs/taobao/a.json"},
                            "taobao_b": {"platform": "TAOBAO", "data_type": "TAOBAO_ACCOUNT_RECORD", "output": "inputs/taobao/b.json"},
                            "dou_a": {"platform": "DOU", "data_type": "DOU_SHOP_ACCOUNT_ITEM", "output": "inputs/dou/a.json"},
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            self.assertEqual(resolve_target_job_names(None, all_jobs=True, config_path=config_path), ["taobao_a", "taobao_b", "dou_a"])
            self.assertEqual(resolve_target_job_names("taobao", all_jobs=False, config_path=config_path), ["taobao_a", "taobao_b"])
            self.assertEqual(resolve_target_job_names("dou_a", all_jobs=False, config_path=config_path), ["dou_a"])


class PipelineTests(unittest.TestCase):
    def test_run_pipeline_fetches_inputs_and_generates_split_reports(self):
        response = {
            "success": True,
            "code": 200,
            "message": "OK",
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
            rails_root = root / "rails"
            seed_dir = rails_root / "db" / "seeds" / "static" / "taobao"
            seed_dir.mkdir(parents=True, exist_ok=True)
            (seed_dir / "account_expense_type.seeds.rb").write_text(seed_content, encoding="utf-8")

            input_path = root / "inputs" / "taobao" / "taobao_check_result.json"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            config_path = root / "fetch_jobs.json"
            config_path.write_text(
                json.dumps(
                    {
                        "defaults": {
                            "start_time": "2026-05-01 00:00:00",
                            "end_time": "2026-05-13 23:59:59",
                        },
                        "jobs": {
                            "taobao": {
                                "platform": "TAOBAO",
                                "source_type": "TAOBAO_ACCOUNT_RECORD",
                                "data_type": "TAOBAO_ACCOUNT_RECORD",
                                "output": str(input_path),
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            fetcher = FakeFetcher([response])
            results, failures = run_pipeline(
                job="taobao",
                all_jobs=False,
                config_path=config_path,
                env_path=root / ".env",
                output_root=root / "outputs",
                rails_root=rails_root,
                fetch_jobs_path=config_path,
                fetcher=fetcher,
            )

            self.assertEqual(failures, [])
            self.assertEqual(len(results), 1)
            self.assertTrue(input_path.exists())
            report_path = root / "outputs" / "taobao" / "taobao_check_result" / "classification_required_platform_fee.md"
            self.assertTrue(report_path.exists())
            report = report_path.read_text(encoding="utf-8")
            self.assertIn("已命中规则: 130100", report)
            self.assertIn("新增候选", report)
            self.assertIn("基础软件服务费归类", report)
            self.assertIn("新平台服务费", report)
            self.assertEqual(len(fetcher.calls), 1)

    def test_format_summary_reports_success_and_failure_counts(self):
        summary = format_summary(
            [],
            [
                type("Failure", (), {"job_name": "taobao", "stage": "fetch", "error": "boom"})(),
            ],
        )

        self.assertIn("completed: 0", summary)
        self.assertIn("failed: 1", summary)
        self.assertIn("error fetch taobao: boom", summary)


if __name__ == "__main__":
    unittest.main()
