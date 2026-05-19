import json
import tempfile
import textwrap
import threading
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

from account_record_fetcher import (
    AccountRecordFetcher,
    FetchSettings,
    JsonApiError,
    UrlLibJsonClient,
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
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class KeyedRecordPageHttpClient:
    def __init__(self, *, total_pages: int = 4):
        self.total_pages = total_pages
        self.calls = []
        self.lock = threading.Lock()

    def post_json(self, url, payload, headers):
        with self.lock:
            self.calls.append({"url": url, "payload": dict(payload), "headers": headers})
        page_number = int(payload["pageNumber"])
        if url.endswith("/checkAllUser"):
            return {
                "success": True,
                "code": 200,
                "message": "OK",
                "data": {
                    "content": [
                        {
                            "userId": 1,
                            "nick": "shop-a",
                            "pagedRecords": {
                                "content": [{"id": "r1"}],
                                "pageNumber": 1,
                                "pageSize": 1,
                                "total": self.total_pages,
                                "totalPage": self.total_pages,
                            },
                        }
                    ],
                    "total": 1,
                },
            }
        if url.endswith("/checkSingleUser"):
            return {
                "success": True,
                "code": 200,
                "message": "OK",
                "data": {
                    "content": [{"id": f"r{page_number}"}],
                    "pageNumber": page_number,
                    "pageSize": 1,
                    "total": self.total_pages,
                    "totalPage": self.total_pages,
                },
            }
        raise AssertionError(f"unexpected url: {url}")


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


class FakeUrlopenResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return b'{"success": true, "data": {"content": []}}'


class UrlLibJsonClientTests(unittest.TestCase):
    def test_post_json_retries_transient_urlopen_error(self):
        attempts = []

        def fake_urlopen(request, timeout):
            attempts.append({"request": request, "timeout": timeout})
            if len(attempts) == 1:
                raise urllib.error.URLError("EOF occurred in violation of protocol")
            return FakeUrlopenResponse()

        client = UrlLibJsonClient()
        with patch("urllib.request.urlopen", fake_urlopen):
            try:
                response = client.post_json("https://example.test/api", {"pageNumber": 1}, {"Platform": "TAOBAO"})
            except urllib.error.URLError as error:
                self.fail(f"did not retry transient urlopen error: {error}")

        self.assertTrue(response["success"])
        self.assertEqual(len(attempts), 2)


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
                    "data": {"content": [{"userId": 1}, {"userId": 2}], "total": 3, "pageNumber": 1, "pageSize": 2},
                },
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [{"userId": 3}], "total": 3, "pageNumber": 2, "pageSize": 2},
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
        self.assertEqual(len(result["data"]["pages"]), 2)
        self.assertEqual(result["data"]["pages"][0]["content"], [{"userId": 1}, {"userId": 2}])
        self.assertEqual(result["data"]["pages"][0]["pageNumber"], 1)
        self.assertEqual(result["data"]["pages"][1]["content"], [{"userId": 3}])
        self.assertEqual(result["data"]["pages"][1]["pageNumber"], 2)
        self.assertEqual(client.calls[0]["payload"]["pageNumber"], 1)
        self.assertEqual(client.calls[1]["payload"]["pageNumber"], 2)

    def test_fetch_all_users_reports_user_page_progress(self):
        client = FakeHttpClient(
            [
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [{"userId": 1}], "total": 2, "pageNumber": 1, "pageSize": 1},
                },
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [{"userId": 2}], "total": 2, "pageNumber": 2, "pageSize": 1},
                },
            ]
        )
        messages = []
        fetcher = AccountRecordFetcher(self.settings(), client, progress=messages.append)

        fetcher.fetch_check_all_users(
            platform="TAOBAO",
            data_type="TAOBAO_ACCOUNT_RECORD",
            start_time="2026-04-23 00:00:00",
            end_time="2026-05-07 23:59:59",
            page_size=1,
        )

        self.assertIn(
            "users page platform=TAOBAO data_type=TAOBAO_ACCOUNT_RECORD node_id=1 page=1 "
            "users=1 fetched_users=1 total_users=2",
            messages,
        )
        self.assertIn(
            "users page platform=TAOBAO data_type=TAOBAO_ACCOUNT_RECORD node_id=1 page=2 "
            "users=1 fetched_users=2 total_users=2",
            messages,
        )

    def test_fetch_all_users_reports_user_page_request_elapsed_time(self):
        client = FakeHttpClient(
            [
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [], "total": 0, "pageNumber": 1, "pageSize": 1},
                },
            ]
        )
        messages = []
        fetcher = AccountRecordFetcher(self.settings(), client, progress=messages.append)

        fetcher.fetch_check_all_users(
            platform="TAOBAO",
            data_type="TAOBAO_ACCOUNT_RECORD",
            start_time="2026-04-23 00:00:00",
            end_time="2026-05-07 23:59:59",
            page_size=1,
        )

        self.assertIn(
            "users page start platform=TAOBAO data_type=TAOBAO_ACCOUNT_RECORD node_id=1 page=1",
            messages,
        )
        self.assertTrue(
            any(
                message.startswith(
                    "users page done platform=TAOBAO data_type=TAOBAO_ACCOUNT_RECORD node_id=1 "
                    "page=1 users=0"
                )
                and "elapsed_ms=" in message
                for message in messages
            ),
            messages,
        )

    def test_fetch_all_users_error_carries_partial_response(self):
        client = FakeHttpClient(
            [
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {"content": [{"userId": 1}], "total": 2, "pageNumber": 1, "pageSize": 1},
                },
                OSError("network dropped"),
            ]
        )
        fetcher = AccountRecordFetcher(self.settings(), client)

        with self.assertRaises(Exception) as context:
            fetcher.fetch_check_all_users(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
                page_size=1,
            )

        self.assertTrue(hasattr(context.exception, "partial_response"))
        partial_response = context.exception.partial_response
        self.assertIn("network dropped", str(context.exception))
        self.assertEqual(partial_response["data"]["content"], [{"userId": 1}])
        self.assertEqual(len(partial_response["data"]["pages"]), 1)
        self.assertEqual(partial_response["data"]["total"], 2)

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
                        "content": [{"id": "r3"}],
                        "pageNumber": 2,
                        "pageSize": 2,
                        "total": 3,
                        "totalPage": 2,
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
        self.assertEqual(len(users[0]["pagedRecords"]["pages"]), 2)
        self.assertEqual(users[0]["pagedRecords"]["pages"][0]["content"], [{"id": "r1"}, {"id": "r2"}])
        self.assertEqual(users[0]["pagedRecords"]["pages"][0]["pageNumber"], 1)
        self.assertEqual(users[0]["pagedRecords"]["pages"][1]["content"], [{"id": "r3"}])
        self.assertEqual(users[0]["pagedRecords"]["pages"][1]["pageNumber"], 2)
        self.assertEqual(users[0]["pagedRecords"]["pageNumber"], 1)
        self.assertEqual(users[0]["pagedRecords"]["total"], 3)
        self.assertEqual(users[0]["pagedRecords"]["totalPage"], 2)
        self.assertEqual(users[1]["pagedRecords"]["content"], [{"id": "s1"}])
        self.assertEqual(len(users[1]["pagedRecords"]["pages"]), 1)
        self.assertEqual(users[1]["pagedRecords"]["pages"][0]["content"], [{"id": "s1"}])
        self.assertEqual(users[1]["pagedRecords"]["pages"][0]["pageNumber"], 1)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(client.calls[1]["url"], "https://example.test/api/accountRecordCheckResult/checkSingleUser")
        self.assertEqual(client.calls[1]["payload"]["userIdOrNick"], "1")
        self.assertEqual(client.calls[1]["payload"]["pageNumber"], 2)
        self.assertEqual(client.calls[1]["payload"]["pageSize"], 2)

    def test_fetch_all_users_fetches_record_pages_with_workers_and_preserves_page_order(self):
        client = KeyedRecordPageHttpClient(total_pages=4)
        fetcher = AccountRecordFetcher(self.settings(), client)

        result = fetcher.fetch_check_all_users(
            platform="TAOBAO",
            data_type="TAOBAO_ACCOUNT_RECORD",
            start_time="2026-04-23 00:00:00",
            end_time="2026-05-07 23:59:59",
            page_size=10,
            record_workers=3,
        )

        paged_records = result["data"]["content"][0]["pagedRecords"]
        self.assertEqual(paged_records["content"], [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}, {"id": "r4"}])
        self.assertEqual([page["pageNumber"] for page in paged_records["pages"]], [1, 2, 3, 4])
        single_user_pages = [
            call["payload"]["pageNumber"]
            for call in client.calls
            if call["url"].endswith("/checkSingleUser")
        ]
        self.assertEqual(sorted(single_user_pages), [2, 3, 4])

    def test_fetch_all_users_reports_record_page_request_elapsed_time(self):
        client = KeyedRecordPageHttpClient(total_pages=3)
        messages = []
        fetcher = AccountRecordFetcher(self.settings(), client, progress=messages.append)

        fetcher.fetch_check_all_users(
            platform="TAOBAO",
            data_type="TAOBAO_ACCOUNT_RECORD",
            start_time="2026-04-23 00:00:00",
            end_time="2026-05-07 23:59:59",
            page_size=10,
        )

        self.assertIn(
            "records page start platform=TAOBAO data_type=TAOBAO_ACCOUNT_RECORD node_id=1 "
            "user='1' user_index=1/1 page=2/3",
            messages,
        )
        self.assertTrue(
            any(
                message.startswith(
                    "records page done platform=TAOBAO data_type=TAOBAO_ACCOUNT_RECORD node_id=1 "
                    "user='1' user_index=1/1 page=2/3 records=1"
                )
                and "elapsed_ms=" in message
                for message in messages
            ),
            messages,
        )

    def test_fetch_all_users_reuses_cached_record_pages_when_resuming(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "fetch-cache"
            first_client = KeyedRecordPageHttpClient(total_pages=3)
            first_fetcher = AccountRecordFetcher(self.settings(), first_client)
            first_fetcher.fetch_check_all_users(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
                page_size=10,
                record_workers=2,
                resume_dir=cache_dir,
            )

            second_client = KeyedRecordPageHttpClient(total_pages=3)
            second_fetcher = AccountRecordFetcher(self.settings(), second_client)
            result = second_fetcher.fetch_check_all_users(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
                page_size=10,
                record_workers=2,
                resume_dir=cache_dir,
            )

        self.assertEqual(
            result["data"]["content"][0]["pagedRecords"]["content"],
            [{"id": "r1"}, {"id": "r2"}, {"id": "r3"}],
        )
        second_single_user_calls = [
            call for call in second_client.calls if call["url"].endswith("/checkSingleUser")
        ]
        self.assertEqual(second_single_user_calls, [])

    def test_fetch_all_users_reports_record_page_cache_hit_elapsed_time(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir) / "fetch-cache"
            first_client = KeyedRecordPageHttpClient(total_pages=3)
            first_fetcher = AccountRecordFetcher(self.settings(), first_client)
            first_fetcher.fetch_check_all_users(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
                page_size=10,
                resume_dir=cache_dir,
            )

            second_client = KeyedRecordPageHttpClient(total_pages=3)
            messages = []
            second_fetcher = AccountRecordFetcher(self.settings(), second_client, progress=messages.append)
            second_fetcher.fetch_check_all_users(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
                page_size=10,
                resume_dir=cache_dir,
            )

        self.assertTrue(
            any(
                message.startswith(
                    "records page cache hit platform=TAOBAO data_type=TAOBAO_ACCOUNT_RECORD node_id=1 "
                    "user='1' user_index=1/1 page=2/3 records=1"
                )
                and "elapsed_ms=" in message
                for message in messages
            ),
            messages,
        )

    def test_fetch_all_users_raises_when_record_pages_are_incomplete(self):
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
                            }
                        ],
                        "total": 1,
                    },
                },
                {
                    "success": True,
                    "code": 200,
                    "message": "OK",
                    "data": {
                        "content": [],
                        "pageNumber": 2,
                        "pageSize": 2,
                        "total": 3,
                        "totalPage": 2,
                    },
                },
            ]
        )
        fetcher = AccountRecordFetcher(self.settings(), client)

        with self.assertRaises(JsonApiError) as context:
            fetcher.fetch_check_all_users(
                platform="TAOBAO",
                data_type="TAOBAO_ACCOUNT_RECORD",
                start_time="2026-04-23 00:00:00",
                end_time="2026-05-07 23:59:59",
                page_size=10,
            )

        self.assertIn("Incomplete pagedRecords", str(context.exception))


if __name__ == "__main__":
    unittest.main()
