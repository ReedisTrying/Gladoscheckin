import unittest
from unittest.mock import MagicMock, Mock

import browser_checkin


class BrowserTests(unittest.TestCase):
    def test_cookies_preserve_equals_and_bind_to_official_host(self):
        cookies = browser_checkin.parse_cookies("gld:sess=abc==; gld:sess.sig=xyz; ")
        self.assertEqual(len(cookies), 2)
        self.assertEqual(cookies[0]["value"], "abc==")
        self.assertTrue(all(c["url"] == "https://glados.cloud/" for c in cookies))

    def test_response_must_be_post_to_exact_official_endpoint(self):
        for url, method, expected in (
            ("https://glados.cloud/api/user/checkin", "POST", True),
            ("https://glados.cloud/api/user/checkin/challenge", "GET", False),
            ("https://glados.cloud/api/user/checkin", "GET", False),
            ("https://glados.cloud.attacker.invalid/api/user/checkin", "POST", False),
        ):
            with self.subTest(url=url, method=method):
                response = Mock(url=url, request=Mock(method=method))
                self.assertEqual(browser_checkin.is_checkin_response(response), expected)

    def test_submit_clicks_once_and_reads_real_response(self):
        context = MagicMock()
        page = context.new_page.return_value
        response = page.expect_response.return_value.__enter__.return_value.value
        response.status = 200
        response.json.return_value = {"code": 0, "points": 10}
        self.assertEqual(browser_checkin.submit_page(context), {"code": 0, "points": 10})
        page.get_by_role.return_value.first.click.assert_called_once()
        page.goto.assert_called_once()

    def test_invalid_json_object_is_not_success(self):
        context = MagicMock()
        response = context.new_page.return_value.expect_response.return_value.__enter__.return_value.value
        response.status = 200
        response.json.return_value = []
        self.assertEqual(browser_checkin.submit_page(context)["reason"], "browser-invalid-response")


if __name__ == "__main__":
    unittest.main()
