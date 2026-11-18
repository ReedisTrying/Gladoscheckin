import contextlib
import io
import os
import unittest
from unittest.mock import Mock, patch

import requests

import checkin


def response(body, status=200):
    result = Mock(status_code=status)
    result.json.return_value = body
    return result


class CheckinTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.headers = checkin.build_headers("gld:sess=dummy")
        self.session.get.return_value = response({"code": 0, "nonce": "test-nonce", "ttl": 120})

    def test_turnstile_stops_before_any_post(self):
        self.session.get.return_value = response({"code": 0, "turnstile": "public-sitekey"})
        self.assertEqual(checkin.do_checkin(self.session, self.headers)[0], "blocked")
        self.session.post.assert_not_called()

    def test_invalid_challenges_do_not_submit(self):
        cases = [None, [], {"code": -2}, {"code": 0},
                 {"code": 0, "nonce": "n", "ttl": 1},
                 {"code": 0, "nonce": "n", "ttl": "nan"},
                 {"code": 0, "nonce": "n", "ttl": "inf"}]
        for case in cases:
            with self.subTest(case=case):
                self.session.get.return_value = response(case)
                self.assertEqual(checkin.do_checkin(self.session, self.headers)[0], "fail")
        self.session.post.assert_not_called()

    def test_http_challenge_error_does_not_submit(self):
        self.session.get.return_value = response({}, 403)
        self.assertEqual(checkin.do_checkin(self.session, self.headers)[0], "fail")
        self.session.post.assert_not_called()

    @patch("checkin.time.sleep")
    def test_current_protocol_without_turnstile(self, sleep):
        self.session.post.return_value = response({"code": 0, "points": 10})
        self.assertEqual(checkin.do_checkin(self.session, self.headers), ("success", "签到成功", 10))
        sleep.assert_called_once_with(2.5)
        args = self.session.post.call_args.kwargs
        self.assertEqual(args["json"], {
            "token": "glados.network", "nonce": "test-nonce",
            "proof": "e60cd42961dd78f51c69a0df365df12a53d39a4988be5a524ba816d7ee94a7c6", "tsState": "off",
        })
        self.session.post.assert_called_once()

    def test_error_code_overrides_success_words(self):
        for code in (4, 5, -1, None):
            self.assertEqual(checkin.classify_checkin({
                "code": code, "message": "Checkin success; already checked", "points": 100,
            })[0], "fail")

    def test_cloudflare_error_overrides_zero_code(self):
        self.assertEqual(checkin.classify_checkin({
            "code": 0, "message": "Cloudflare verification failed. Nothing was recorded — please retry.",
        }), ("blocked", "Cloudflare 验证未通过，未记录签到；请在官网完成签到。", 0))

    def test_reason_overrides_repeated_flag(self):
        self.assertEqual(checkin.classify_checkin({
            "code": 5, "reason": "turnstile", "repeated": True,
        })[0], "blocked")

    def test_failed_text_overrides_repeated_flag(self):
        self.assertEqual(checkin.classify_checkin({
            "code": 0, "repeated": True, "message": "Failed; nothing was recorded",
        })[0], "fail")

    def test_device_mismatch_is_not_cookie_expiry(self):
        kind, message, _ = checkin.classify_checkin({"code": 4, "reason": "device-mismatch"})
        self.assertEqual(kind, "fail")
        self.assertIn("USER_AGENTS", message)

    def test_new_observation_is_success_not_repeat(self):
        self.assertEqual(checkin.classify_checkin({
            "code": 0, "message": "Today's observation logged. Return tomorrow.", "points": 12,
        })[0], "success")

    def test_existing_record_does_not_prove_browser_verification(self):
        self.assertEqual(checkin.classify_checkin({
            "code": 1, "repeated": True, "_browser_verification": "timeout",
        })[0], "blocked")

    def test_repeated_flag_and_legacy_repeat(self):
        for body in ({"code": 0, "repeated": True, "points": 100},
                     {"code": 1, "message": "Checkin Repeats! Please Try Tomorrow!"}):
            self.assertEqual(checkin.classify_checkin(body)[::2], ("repeat", 0))

    @patch("checkin.time.sleep")
    def test_uncertain_post_is_never_retried_or_logged_raw(self, sleep):
        self.session.post.side_effect = requests.Timeout("secret-cookie-value")
        kind, message, _ = checkin.do_checkin(self.session, self.headers)
        self.assertEqual(kind, "fail")
        self.assertNotIn("secret-cookie-value", message)
        self.assertIn("不确定", message)
        self.session.post.assert_called_once()

    def test_status_requires_success_code(self):
        self.session.get.return_value = response({"code": -2, "data": {"email": "a@b.c"}})
        self.assertIsNotNone(checkin.get_account_status(self.session, self.headers)[2])

    @patch("checkin.requests.Session")
    def test_status_only_never_calls_checkin_or_challenge(self, factory):
        factory.return_value.__enter__.return_value = self.session
        self.session.get.return_value = response({"code": 0, "data": {"email": "a@b.c", "leftDays": "12.5"}})
        with contextlib.redirect_stdout(io.StringIO()):
            kind, context = checkin.process_account("dummy", 1, status_only=True)
        self.assertEqual(kind, "status")
        self.assertIn("未执行签到", context)
        self.session.get.assert_called_once_with(checkin.STATUS_URL, headers=checkin.build_headers("dummy"), timeout=checkin.TIMEOUT)
        self.session.post.assert_not_called()

    def test_configurable_user_agent(self):
        self.assertEqual(checkin.build_headers("dummy", "my-browser")["User-Agent"], "my-browser")

    @patch("checkin.pushdeer_send")
    @patch("checkin.process_account")
    def test_main_blocked_exits_two(self, process, notify):
        process.return_value = ("blocked", "needs official site")
        with patch.dict(os.environ, {"COOKIES": "dummy"}, clear=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(checkin.main(), 2)

    @patch("checkin.process_account")
    def test_empty_account_list_is_failure(self, process):
        with patch.dict(os.environ, {"COOKIES": " & "}, clear=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(checkin.main(), 1)
        process.assert_not_called()


if __name__ == "__main__":
    unittest.main()
