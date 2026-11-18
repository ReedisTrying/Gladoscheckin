"""Offline real-browser check; all official-host requests are intercepted."""

import os
import unittest

from playwright.sync_api import sync_playwright

from browser_checkin import BASE_URL, CHECKIN_PATH, submit_page


class BrowserSmoke(unittest.TestCase):
    def test_actual_button_and_response_capture(self):
        submissions = []

        def fixture(route):
            if route.request.method == "POST":
                submissions.append(route.request.url)
                route.fulfill(json={"code": 0, "points": 10})
            else:
                route.fulfill(content_type="text/html", body='''
                    <button onclick="fetch('/api/user/checkin', {method:'POST'})">Check in</button>
                ''')

        with sync_playwright() as playwright:
            with playwright.chromium.launch(
                channel=os.environ.get("GLADOS_BROWSER_CHANNEL", "chrome"), headless=True,
            ) as browser:
                with browser.new_context() as context:
                    context.route(BASE_URL + "/**", fixture)
                    self.assertEqual(submit_page(context), {"code": 0, "points": 10, "_browser_verification": "unknown"})
        self.assertEqual(submissions, [BASE_URL + CHECKIN_PATH])
