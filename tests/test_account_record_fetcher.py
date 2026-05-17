import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from account_record_fetcher import (
    AccountRecordFetcher,
    FetchSettings,
    JsonApiError,
    load_dotenv,
    load_settings,
)


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, url, payload, headers):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        return self.responses.pop(0)


class EnvAndSettingsTests(unittest.TestCase):
    def test_load_dotenv_parses_quotes_export_and_comments(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            handle.write(
                textwrap.dedent(
                    """
                    # local secrets
                    export A6M1N_TOKEN="demo-token"
                    A6M1N_BASE_URL=https://example.test
                    EMPTY=
                    """
                )
            )
            path = Path(handle.name)

        try:
            values = load_dotenv(path)
        finally:
            path.unlink()

        self.assertEqual(values["A6M1N_TOKEN"], "demo-token")
        self.assertEqual(values["A6M1N_BASE_URL"], "https://example.test")
        self.assertEqual(values["EMPTY"], "")

    def test_load_settings_requires_token(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            handle.write("A6M1N_BASE_URL=https://example.test\n")
            path = Path(handle.name)

        try:
            with self.assertRaises(JsonApiError):
                load_settings(path)
        finally:
            path.unlink()

    def test_load_settings_reads_token_and_base_url(self):
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as handle:
            handle.write("A6M1N_TOKEN=env-token\nA6M1N_BASE_URL=https://example.test\n")
            path = Path(handle.name)

        try:
            settings = load_settings(path)
        finally:
            path.unlink()

        self.assertEqual(settings.token, "env-token")
        self.assertEqual(settings.base_url, "https://example.test")


class FetcherTests(unittest.TestCase):
    def settings(self) -> FetchSettings:
        return FetchSettings(token="env-token", base_url="https://example.test")

    def test_fetch_uses_env_token_without_login(self):
        client = FakeHttpClient(
            [
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [], "total": 0},
                }
            ]
        )
        fetcher = AccountRecordFetcher(self.settings(), client)

        result = fetcher.fetch_check_all_user(
            platform="TAOBAO",
            data_type="TAOBAO_ACCOUNT_RECORD",
            start_time="2026-04-23 00:00:00",
            end_time="2026-05-07 23:59:59",
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["url"], "https://example.test/api/accountRecordCheckResult/checkAllUser")
        self.assertEqual(client.calls[0]["headers"]["Authorization"], "Bearer env-token")
        self.assertEqual(client.calls[0]["headers"]["Platform"], "TAOBAO")

    def test_fetch_raises_api_error_when_env_token_is_expired(self):
        client = FakeHttpClient(
            [
                {"success": False, "code": 401, "message": "expired", "data": None},
            ]
        )
        fetcher = AccountRecordFetcher(self.settings(), client)

        with self.assertRaises(JsonApiError):
            fetcher.fetch_check_all_user(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
            )

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["headers"]["Authorization"], "Bearer env-token")

    def test_fetch_raises_api_error_when_response_contains_app_level_status_500(self):
        client = FakeHttpClient(
            [
                {
                    "timestamp": "2026-05-13 13:38:40",
                    "status": 500,
                    "error": "Internal Server Error",
                    "path": "/api/accountRecordCheckResult/checkAllUser",
                    "data": {"content": [], "total": 0},
                }
            ]
        )
        fetcher = AccountRecordFetcher(self.settings(), client)

        with self.assertRaises(JsonApiError) as context:
            fetcher.fetch_check_all_user(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
            )

        self.assertIn("Internal Server Error", str(context.exception))
        self.assertEqual(len(client.calls), 1)

    def test_fetch_all_users_merges_all_pages(self):
        client = FakeHttpClient(
            [
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [{"userId": 1}, {"userId": 2}], "total": 3},
                },
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [{"userId": 3}], "total": 3},
                },
            ]
        )
        fetcher = AccountRecordFetcher(self.settings(), client)

        result = fetcher.fetch_check_all_users(
            platform="TAOBAO",
            data_type="TAOBAO_ACCOUNT_RECORD",
            start_time="2026-04-23 00:00:00",
            end_time="2026-05-07 23:59:59",
            page_size=2,
        )

        self.assertEqual(result["data"]["content"], [{"userId": 1}, {"userId": 2}, {"userId": 3}])
        self.assertEqual(client.calls[0]["payload"]["pageNumber"], 1)
        self.assertEqual(client.calls[1]["payload"]["pageNumber"], 2)

    def test_fetch_all_users_fetches_all_paged_records_for_each_user(self):
        client = FakeHttpClient(
            [
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {
                        "content": [
                            {
                                "userId": 1,
                                "nick": "shop-a",
                                "pagedRecords": {
                                    "content": [{"id": "r1"}, {"id": "r2"}],
                                    "pageNumber": 1,
                                    "pageSize": 2,
                                    "total": 3,
                                    "totalPage": 2,
                                },
                            },
                            {
                                "userId": 2,
                                "nick": "shop-b",
                                "pagedRecords": {
                                    "content": [{"id": "s1"}],
                                    "pageNumber": 1,
                                    "pageSize": 2,
                                    "total": 1,
                                    "totalPage": 1,
                                },
                            },
                        ],
                        "total": 2,
                    },
                },
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {
                        "content": [
                            {
                                "userId": 1,
                                "nick": "shop-a",
                                "pagedRecords": {
                                    "content": [{"id": "r3"}],
                                    "pageNumber": 2,
                                    "pageSize": 2,
                                    "total": 3,
                                    "totalPage": 2,
                                },
                            }
                        ],
                        "total": 1,
                    },
                },
            ]
        )
        fetcher = AccountRecordFetcher(self.settings(), client)

        result = fetcher.fetch_check_all_users(
            platform="TAOBAO",
            data_type="TAOBAO_ACCOUNT_RECORD",
            start_time="2026-04-23 00:00:00",
            end_time="2026-05-07 23:59:59",
            page_size=10,
        )

        users = result["data"]["content"]
        self.assertEqual(users[0]["pagedRecords"]["content"], [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}])
        self.assertEqual(users[0]["pagedRecords"]["pageNumber"], 1)
        self.assertEqual(users[0]["pagedRecords"]["total"], 3)
        self.assertEqual(users[0]["pagedRecords"]["totalPage"], 2)
        self.assertEqual(users[1]["pagedRecords"]["content"], [{"id": "s1"}])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["payload"]["userIdOrNick"], "1")
        self.assertEqual(client.calls[1]["payload"]["pageNumber"], 2)
        self.assertEqual(client.calls[1]["payload"]["pageSize"], 2)


if __name__ == "__main__":
    unittest.main()
