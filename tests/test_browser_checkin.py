import unittest
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import browser_checkin


class BrowserTests(unittest.TestCase):
    def test_proxy_is_applied_to_a_headed_browser(self):
        class StopBeforeLaunch(Exception):
            pass
        with patch.dict("os.environ", {"GLADOS_BROWSER_PROXY": "http://127.0.0.1:7890"}), patch("browser_checkin.browser_executable", return_value="fixture.exe"), patch("browser_checkin.subprocess.Popen", side_effect=StopBeforeLaunch) as start:
            with self.assertRaises(StopBeforeLaunch):
                with browser_checkin.standalone_context(Mock(), "msedge", headless=False):
                    self.fail("Must stop before a real process is launched")
            args = start.call_args.args[0]
            self.assertIn("--proxy-server=http://127.0.0.1:7890", args)
            self.assertNotIn("--headless=new", args)

    def test_proxy_credentials_are_rejected_before_launch(self):
        with patch.dict("os.environ", {"GLADOS_BROWSER_PROXY": "http://user:private@localhost:7890"}), patch("browser_checkin.browser_executable", return_value="fixture.exe"), patch("browser_checkin.subprocess.Popen") as start:
            with self.assertRaises(RuntimeError):
                with browser_checkin.standalone_context(Mock(), "msedge"):
                    self.fail("Must not put proxy credentials on the command line")
            start.assert_not_called()

    def test_refuses_existing_unowned_profile_without_starting_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "personal-data").write_text("fixture", encoding="utf-8")
            with patch("browser_checkin.browser_executable", return_value="fixture.exe"), patch("browser_checkin.subprocess.Popen") as start:
                with self.assertRaises(RuntimeError):
                    with browser_checkin.standalone_context(Mock(), "chrome", profile_directory=directory):
                        self.fail("Must not use an existing personal profile")
                start.assert_not_called()

    def test_profile_lock_prevents_concurrent_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            with browser_checkin.profile_lock(Path(directory)):
                with self.assertRaises(RuntimeError):
                    with browser_checkin.profile_lock(Path(directory)):
                        self.fail("Concurrent runs must not control the same profile")

    def test_cookies_preserve_equals_and_bind_to_official_host(self):
        cookies = browser_checkin.parse_cookies("gld:sess=abc==; gld:sess.sig=xyz; ")
        self.assertEqual(len(cookies), 2)
        self.assertEqual(cookies[0]["value"], "abc==")
        self.assertTrue(all(c["url"] == browser_checkin.BASE_URL + "/" for c in cookies))

    def test_response_must_be_post_to_exact_official_endpoint(self):
        for url, method, expected in (
            (browser_checkin.BASE_URL + "/api/user/checkin", "POST", True),
            (browser_checkin.BASE_URL + "/api/user/checkin/challenge", "GET", False),
            (browser_checkin.BASE_URL + "/api/user/checkin", "GET", False),
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
        response.request.post_data_json = {"tsState": "ok", "turnstile": "dummy", "nonce": "dummy"}
        response.json.return_value = {"code": 0, "points": 10}
        self.assertEqual(browser_checkin.submit_page(context), {"code": 0, "points": 10, "_browser_verification": "ok"})
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
