import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fetch_account_records import (
    DEFAULT_CONFIG_PATH,
    build_default_output_path,
    load_fetch_jobs,
    main,
    run_fetch_job,
    run_fetch_jobs,
    run_fetch_platform,
)


class FakeFetcher:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def fetch_check_all_users(self, **kwargs):
        self.calls.append({"all_pages": True, **kwargs})
        return self.response

    def fetch_check_all_user(self, **kwargs):
        self.calls.append({"all_pages": False, **kwargs})
        return self.response


class FakeMultiNodeFetcher:
    def __init__(self):
        self.calls = []

    def fetch_check_all_users(self, **kwargs):
        self.calls.append({"all_pages": True, **kwargs})
        node_id = kwargs["node_id"]
        return {
            "success": True,
            "data": {
                "content": [{"userId": node_id * 100}],
                "total": 1,
                "totalPage": 1,
            },
        }

    def fetch_check_all_user(self, **kwargs):
        self.calls.append({"all_pages": False, **kwargs})
        node_id = kwargs["node_id"]
        return {
            "success": True,
            "data": {
                "content": [{"userId": node_id * 100}],
                "total": 1,
                "totalPage": 1,
            },
        }


class FetchAccountRecordsTests(unittest.TestCase):
    def write_config(self, tmpdir: str, *, node_ids: list[int] | None = None) -> Path:
        path = Path(tmpdir) / "fetch_jobs.json"
        taobao_job = {
            "display_name": "淘宝支付宝",
            "platform": "TAOBAO",
            "data_type": "TAOBAO_ACCOUNT_RECORD",
            "source_type": "TAOBAO_ACCOUNT_RECORD",
            "output": str(Path(tmpdir) / "inputs" / "taobao" / "taobao_check_result.json"),
        }
        if node_ids is not None:
            taobao_job["node_ids"] = node_ids
        path.write_text(
            json.dumps(
                {
                    "defaults": {
                        "start_time": "2026-04-23 00:00:00",
                        "end_time": "2026-05-07 23:59:59",
                        "page_size": 50,
                        "page_number": 1,
                    },
                    "jobs": {
                        "taobao": taobao_job
                    },
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_load_fetch_jobs_reads_named_job(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir)

            jobs = load_fetch_jobs(config_path)

        self.assertIn("taobao", jobs)
        self.assertEqual(jobs["taobao"]["platform"], "TAOBAO")
        self.assertEqual(jobs["taobao"]["data_type"], "TAOBAO_ACCOUNT_RECORD")
        self.assertEqual(jobs["taobao"]["start_time"], "2026-04-23 00:00:00")
        self.assertEqual(jobs["taobao"]["end_time"], "2026-05-07 23:59:59")
        self.assertEqual(jobs["taobao"]["page_size"], 50)

    def test_default_config_assigns_platform_node_counts(self):
        jobs = load_fetch_jobs(DEFAULT_CONFIG_PATH)

        expected_node_ids_by_platform = {
            "PDD": [1, 2],
            "DOU": [1, 2, 3],
            "TAOBAO": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        }
        for job in jobs.values():
            platform = job["platform"]
            expected_node_ids = expected_node_ids_by_platform.get(platform)
            if expected_node_ids is None:
                self.assertNotIn("node_ids", job)
            else:
                self.assertEqual(job.get("node_ids"), expected_node_ids)

    def test_run_fetch_job_fetches_all_pages_and_writes_output(self):
        response = {"success": True, "data": {"content": [{"userId": 1}], "total": 1}}
        fetcher = FakeFetcher(response)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir)

            output_path, result = run_fetch_job("taobao", config_path=config_path, fetcher=fetcher)

            written = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(result, response)
        self.assertEqual(written, response)
        self.assertEqual(fetcher.calls[0]["all_pages"], True)
        self.assertEqual(fetcher.calls[0]["platform"], "TAOBAO")
        self.assertEqual(fetcher.calls[0]["data_type"], "TAOBAO_ACCOUNT_RECORD")
        self.assertEqual(fetcher.calls[0]["page_size"], 50)

    def test_run_fetch_job_uses_chinese_platform_bill_type_and_source_type_output_path(self):
        response = {"success": True, "data": {"content": [], "total": 0}}
        fetcher = FakeFetcher(response)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir)

            output_path, _ = run_fetch_job("taobao", config_path=config_path, fetcher=fetcher)

            written = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(
            output_path,
            Path(tmpdir) / "inputs" / "淘宝" / "淘宝-通用账单-TAOBAO_ACCOUNT_RECORD.json",
        )
        self.assertEqual(written, response)

    def test_build_default_output_path_uses_expected_names_from_default_config(self):
        jobs = load_fetch_jobs(DEFAULT_CONFIG_PATH)

        self.assertEqual(
            build_default_output_path(jobs["tb_whale_account_record"]),
            Path("inputs") / "淘宝" / "淘宝-聚合结算账单明细-TB_WHALE_ACCOUNT_RECORD.json",
        )
        self.assertEqual(
            build_default_output_path(jobs["alibaba_alipay_account_record"]),
            Path("inputs") / "1688" / "1688-支付宝账单-ALIBABA_ALIPAY_ACCOUNT_RECORD.json",
        )
        self.assertEqual(
            build_default_output_path(jobs["jingdong_insurance_bill"]),
            Path("inputs") / "京东" / "京东-保险费明细-JINGDONG_INSURANCE_BILL.json",
        )
        self.assertEqual(
            build_default_output_path(jobs["kuaishou_account_bill"]),
            Path("inputs") / "快手" / "快手-资金账单明细-KUAISHOU_ACCOUNT_BILL.json",
        )
        self.assertEqual(
            build_default_output_path({"platform": "DOU", "data_type": "DOU_SHOP_ACCOUNT_ITEM"}),
            Path("inputs") / "抖店" / "抖店-资金流水账单-DOU_SHOP_ACCOUNT_ITEM.json",
        )

    def test_run_fetch_job_allows_time_and_output_overrides(self):
        response = {"success": True, "data": {"content": [], "total": 0}}
        fetcher = FakeFetcher(response)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir)
            output_path = Path(tmpdir) / "custom.json"

            actual_output, _ = run_fetch_job(
                "taobao",
                config_path=config_path,
                fetcher=fetcher,
                start_time="2026-05-01 00:00:00",
                end_time="2026-05-13 23:59:59",
                output=output_path,
            )

        self.assertEqual(actual_output, output_path)
        self.assertEqual(fetcher.calls[0]["start_time"], "2026-05-01 00:00:00")
        self.assertEqual(fetcher.calls[0]["end_time"], "2026-05-13 23:59:59")

    def test_run_fetch_job_merges_configured_node_ids(self):
        fetcher = FakeMultiNodeFetcher()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir, node_ids=[1, 2])

            output_path, result = run_fetch_job("taobao", config_path=config_path, fetcher=fetcher)
            written = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual([call["node_id"] for call in fetcher.calls], [1, 2])
        self.assertEqual(result["data"]["total"], 2)
        self.assertEqual(result["data"]["content"], [{"userId": 100, "nodeId": 1}, {"userId": 200, "nodeId": 2}])
        self.assertEqual(written, result)

    def test_run_fetch_job_node_id_override_fetches_one_node(self):
        fetcher = FakeMultiNodeFetcher()
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir, node_ids=[1, 2])

            _, result = run_fetch_job("taobao", config_path=config_path, fetcher=fetcher, node_id=2)

        self.assertEqual([call["node_id"] for call in fetcher.calls], [2])
        self.assertEqual(result["data"]["total"], 1)
        self.assertEqual(result["data"]["content"], [{"userId": 200}])

    def test_run_fetch_jobs_fetches_every_configured_job_in_order(self):
        response = {"success": True, "data": {"content": [], "total": 0}}
        fetcher = FakeFetcher(response)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["jobs"]["pdd_mall_account_record"] = {
                "display_name": "拼多多货款账单明细",
                "platform": "PDD",
                "data_type": "PDD_MALL_ACCOUNT_RECORD",
                "source_type": "PDD_MALL_ACCOUNT_RECORD",
                "output": str(Path(tmpdir) / "inputs" / "pdd" / "pdd_mall_account_record_check_result.json"),
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            results = run_fetch_jobs(config_path=config_path, fetcher=fetcher)

        self.assertEqual([name for name, _, _ in results], ["taobao", "pdd_mall_account_record"])
        self.assertEqual([call["platform"] for call in fetcher.calls], ["TAOBAO", "PDD"])
        self.assertEqual([call["data_type"] for call in fetcher.calls], ["TAOBAO_ACCOUNT_RECORD", "PDD_MALL_ACCOUNT_RECORD"])

    def test_run_fetch_platform_fetches_matching_platform_jobs_in_order(self):
        response = {"success": True, "data": {"content": [], "total": 0}}
        fetcher = FakeFetcher(response)
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = self.write_config(tmpdir)
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["jobs"]["dou_order_settle_bill_detail"] = {
                "display_name": "抖店结算账单明细",
                "platform": "DOU",
                "data_type": "DOU_ORDER_SETTLE_BILL_DETAIL",
                "source_type": "DOU_ORDER_SETTLE_BILL_DETAIL",
                "output": str(Path(tmpdir) / "inputs" / "dou" / "dou_order_settle_bill_detail_check_result.json"),
            }
            config["jobs"]["dou_shop_account_item"] = {
                "display_name": "抖店资金流水明细",
                "platform": "DOU",
                "data_type": "DOU_SHOP_ACCOUNT_ITEM",
                "source_type": "DOU_SHOP_ACCOUNT_ITEM",
                "output": str(Path(tmpdir) / "inputs" / "dou" / "dou_shop_account_item_check_result.json"),
            }
            config_path.write_text(json.dumps(config), encoding="utf-8")

            results = run_fetch_platform("dou", config_path=config_path, fetcher=fetcher)

        self.assertEqual([name for name, _, _ in results], ["dou_order_settle_bill_detail", "dou_shop_account_item"])
        self.assertEqual([call["platform"] for call in fetcher.calls], ["DOU", "DOU"])
        self.assertEqual([call["data_type"] for call in fetcher.calls], ["DOU_ORDER_SETTLE_BILL_DETAIL", "DOU_SHOP_ACCOUNT_ITEM"])

    def test_main_all_rejects_single_output_override(self):
        code = main(["--all", "--output", "combined.json"])

        self.assertEqual(code, 1)

    def test_main_platform_alias_rejects_single_output_override(self):
        code = main(["dou", "--output", "combined.json"])

        self.assertEqual(code, 1)

    def test_main_requires_job_or_all(self):
        code = main([])

        self.assertEqual(code, 1)

    def test_main_all_prints_each_written_job(self):
        results = [
            ("taobao", Path("inputs/taobao/taobao_check_result.json"), {}),
            ("pdd_mall_account_record", Path("inputs/pdd/pdd_mall_account_record_check_result.json"), {}),
        ]

        stdout = io.StringIO()
        with patch("fetch_account_records.run_fetch_jobs", return_value=results), contextlib.redirect_stdout(stdout):
            code = main(["--all"])

        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.getvalue(),
            "Wrote taobao: inputs/taobao/taobao_check_result.json\n"
            "Wrote pdd_mall_account_record: inputs/pdd/pdd_mall_account_record_check_result.json\n",
        )

    def test_main_platform_alias_prints_each_written_job(self):
        results = [
            ("dou_order_settle_bill_detail", Path("inputs/dou/dou_order_settle_bill_detail_check_result.json"), {}),
            ("dou_shop_account_item", Path("inputs/dou/dou_shop_account_item_check_result.json"), {}),
        ]

        stdout = io.StringIO()
        with patch("fetch_account_records.run_fetch_platform", return_value=results), contextlib.redirect_stdout(stdout):
            code = main(["dou"])

        self.assertEqual(code, 0)
        self.assertEqual(
            stdout.getvalue(),
            "Wrote dou_order_settle_bill_detail: inputs/dou/dou_order_settle_bill_detail_check_result.json\n"
            "Wrote dou_shop_account_item: inputs/dou/dou_shop_account_item_check_result.json\n",
        )


if __name__ == "__main__":
    unittest.main()
