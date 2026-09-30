"""Test monitoring boundaries, event pairing, and password-gated UI."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.admin import check_password, read_logs, task_activity, visible_config
from app.config import settings


class AdminTests(unittest.TestCase):
    def test_password_fails_closed(self):
        with patch.object(settings, "ADMIN_PASSWORD", ""):
            self.assertFalse(check_password(""))
        with patch.object(settings, "ADMIN_PASSWORD", "pässword"):
            self.assertTrue(check_password("pässword"))
            self.assertFalse(check_password("wrong"))

    def test_log_read_is_bounded_and_redacts_export(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "app.log"
            path.write_text(
                "x" * (1024 * 1024 + 20) + "\n"
                "2026-09-30T10:00:00+1000 INFO request_id=req-1 logger=airline.test "
                "event=operation_started operation=retrieve api_key=private-key\n"
                "2026-09-30T10:00:01+1000 ERROR request_id=req-1 logger=airline.test "
                "event=operation_failed operation=retrieve duration_ms=1000 error_type=RuntimeError\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"LOG_FILE": str(path)}):
                rows, notice = read_logs()
                self.assertEqual(len(rows), 2)
                self.assertEqual(notice, "")
                self.assertNotIn("private-key", rows[0]["raw"])
                tasks = task_activity(rows)
                self.assertEqual(len(tasks), 1)
                self.assertEqual(tasks[0]["Status"], "Failed")
                self.assertEqual(len(read_logs(1)[0]), 1)
                path.unlink()
                self.assertTrue(read_logs()[1])

    def test_config_never_exposes_passwords(self):
        with patch.object(settings, "POSTGRES_PASSWORD", "private-test-secret"):
            result = visible_config()
            self.assertEqual(result["POSTGRES_PASSWORD"], "Configured")
            self.assertNotIn("private-test-secret", str(result))
            self.assertNotIn("ADMIN_PASSWORD", result)

    def test_admin_page_login_logout(self):
        from streamlit.testing.v1 import AppTest

        with patch.object(settings, "ADMIN_PASSWORD", "test-admin"):
            app = AppTest.from_file("pages/1_Admin.py").run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.tabs), 0)
            app.text_input[0].input("wrong")
            app.button[0].click().run()
            self.assertTrue(app.error)
            self.assertEqual(len(app.tabs), 0)
            app.text_input[0].input("test-admin")
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.tabs), 3)
            app.sidebar.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.tabs), 0)


if __name__ == "__main__":
    unittest.main()
