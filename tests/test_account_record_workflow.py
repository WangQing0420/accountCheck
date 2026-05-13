import tempfile
import unittest
from pathlib import Path

from account_record_fetcher import FetchSettings
from account_record_workflow import run_workflow


class FakeFetcher:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def fetch_check_all_user(self, **kwargs):
        self.calls.append(kwargs)
        return self.response

    def fetch_check_all_users(self, **kwargs):
        self.calls.append({"all_pages": True, **kwargs})
        return self.response


class WorkflowTests(unittest.TestCase):
    def test_run_workflow_fetches_and_builds_report(self):
        response = {
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
                                {"id": 1, "memo": "淘宝穿搭推广服务费(1)扣款"},
                                {"id": 2, "memo": "淘宝穿搭推广服务费(1)扣款"},
                            ]
                        },
                    }
                ]
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            rails_root = Path(tmpdir) / "rails"
            seed_path = rails_root / "db" / "seeds" / "static" / "taobao"
            seed_path.mkdir(parents=True, exist_ok=True)
            (seed_path / "account_expense_type.seeds.rb").write_text("account_record_types = {}\n", encoding="utf-8")

            settings = FetchSettings(token="env-token", base_url="https://example.test")
            fetcher = FakeFetcher(response)

            fetched, report = run_workflow(
                settings,
                platform="TAOBAO",
                source_type="TAOBAO_ACCOUNT_RECORD",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
                rails_root=rails_root,
                fetcher=fetcher,
            )

        self.assertEqual(fetched, response)
        self.assertTrue(fetcher.calls[0]["all_pages"])
        self.assertEqual(fetcher.calls[0]["platform"], "TAOBAO")
        self.assertIn("账单归类分析报告", report)
        self.assertIn("未归类分组", report)


if __name__ == "__main__":
    unittest.main()
