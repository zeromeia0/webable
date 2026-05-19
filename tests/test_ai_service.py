"""Tests for optional Ollama AI (mocked HTTP; no live Ollama)."""

from __future__ import annotations

import json
import os
import unittest
from io import BytesIO
from unittest import mock
from urllib.error import HTTPError

from app.services import ai_service


class TestAiServiceConfig(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("OLLAMA_MODEL", None)
        os.environ.pop("OLLAMA_BASE_URL", None)

    def test_default_model_is_minimax_cloud(self):
        self.assertEqual(ai_service.ollama_model(), "minimax-m2.5:cloud")
        self.assertNotEqual(ai_service.ollama_model(), "qwen2.5-coder:3b")

    def test_env_ollama_model_overrides_default(self):
        os.environ["OLLAMA_MODEL"] = "custom-model:7b"
        self.assertEqual(ai_service.ollama_model(), "custom-model:7b")

    def test_env_ollama_base_url_overrides_default(self):
        os.environ["OLLAMA_BASE_URL"] = "http://example:11434"
        self.assertEqual(ai_service.ollama_base_url(), "http://example:11434")


class TestAskOllama(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("OLLAMA_MODEL", None)
        os.environ.pop("OLLAMA_BASE_URL", None)

    @mock.patch("app.services.ai_service.urlrequest.urlopen")
    def test_successful_response(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"response": "Your balance looks stable."}
        ).encode()
        result = ai_service.ask_ollama("How am I doing?", {"total_income": 1000})
        self.assertTrue(result.ok)
        self.assertEqual(result.answer, "Your balance looks stable.")
        req = mock_urlopen.call_args[0][0]
        body = json.loads(req.data.decode())
        self.assertEqual(body["model"], "minimax-m2.5:cloud")

    @mock.patch("app.services.ai_service.urlrequest.urlopen", side_effect=OSError("connection refused"))
    def test_ollama_unreachable(self, _mock_urlopen):
        result = ai_service.ask_ollama("Hello?", {"total_income": 1})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, ai_service.REASON_UNREACHABLE)
        self.assertEqual(result.error, ai_service.MSG_UNREACHABLE)
        self.assertFalse(result.can_signin)

    @mock.patch("app.services.ai_service.urlrequest.urlopen")
    def test_ollama_auth_required(self, mock_urlopen):
        err_body = json.dumps(
            {"error": "unauthorized", "signin_url": "https://ollama.com/connect?name=host&key=abc"}
        ).encode()
        mock_urlopen.side_effect = HTTPError(
            "http://ollama:11434/api/generate",
            401,
            "Unauthorized",
            hdrs=None,
            fp=BytesIO(err_body),
        )
        result = ai_service.ask_ollama("Hello?", {"total_income": 1})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, ai_service.REASON_AUTH_REQUIRED)
        self.assertTrue(result.can_signin)
        self.assertIn("signed in", result.error or "")
        self.assertTrue(result.signin_url.startswith("https://ollama.com/connect"))

    @mock.patch("app.services.ai_service.urlrequest.urlopen")
    def test_no_raw_db_fields_in_prompt(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"response": "ok"}
        ).encode()
        ctx = {
            "workspace": "Home",
            "total_income": 2000,
            "top_expenses": [{"name": "Rent", "amount_eur": 700}],
        }
        ai_service.ask_ollama("What are my top expenses?", ctx)
        req = mock_urlopen.call_args[0][0]
        prompt = json.loads(req.data.decode())["prompt"]
        self.assertIn("total_income", prompt)
        self.assertNotIn("finance_db_path", prompt)
        self.assertNotIn("one_time_transactions", prompt)


class TestSigninLink(unittest.TestCase):
    @mock.patch("app.services.ai_service._ollama_request")
    def test_fetch_signin_link_from_api_me(self, mock_req):
        mock_req.return_value = {
            "reachable": True,
            "ok": False,
            "status": 401,
            "signin_url": "https://ollama.com/connect?name=x&key=y",
            "error": "unauthorized",
        }
        out = ai_service.fetch_ollama_signin_link()
        self.assertEqual(out["signin_url"], "https://ollama.com/connect?name=x&key=y")
        mock_req.assert_called_with("POST", "/api/me", {})

    @mock.patch("app.services.ai_service._ollama_request")
    def test_fetch_signin_link_signed_in(self, mock_req):
        mock_req.return_value = {"reachable": True, "ok": True, "status": 200, "body": {"name": "user"}}
        out = ai_service.fetch_ollama_signin_link()
        self.assertTrue(out.get("signed_in"))

    @mock.patch("app.services.ai_service._ollama_request")
    def test_fetch_signin_link_unreachable(self, mock_req):
        mock_req.return_value = {"reachable": False, "ok": False, "reason": ai_service.REASON_UNREACHABLE}
        out = ai_service.fetch_ollama_signin_link()
        self.assertIn("error", out)
        self.assertNotIn("signin_url", out)


class TestSummarizedContext(unittest.TestCase):
    @mock.patch("app.services.ai_service.eom_summary_service.build_live_preview")
    @mock.patch("app.services.ai_service.wishlist_service.list_items", return_value=[])
    @mock.patch("app.services.ai_service.mss.compute_snapshot_payload")
    def test_summarize_workspace_context_shape(self, mock_compute, _wishlist, _eom):
        mock_compute.side_effect = [
            {
                "month_label": "April 2026",
                "total_income": 1000,
                "total_expenses": 800,
                "net_balance": 200,
                "safe_to_spend": 50,
                "fixed_expenses_percent_income": "40.0",
                "top_expenses": [{"name": "Rent", "amount_eur": 500}],
                "top_income": [{"name": "Salary", "amount_eur": 1000}],
                "comparison": {},
            },
            {
                "month_label": "May 2026",
                "total_income": 1200,
                "total_expenses": 900,
                "net_balance": 300,
                "safe_to_spend": 75,
                "fixed_expenses_percent_income": "45.0",
                "top_expenses": [{"name": "Rent", "amount_eur": 500}],
                "top_income": [{"name": "Salary", "amount_eur": 1200}],
                "comparison": {
                    "income_change": 200,
                    "expenses_change": 100,
                    "savings_change": 100,
                    "plain_summary": "Income increased.",
                },
            },
        ]
        user = mock.Mock(enable_iefp_mode=False)
        inst = mock.Mock(name="Main", finance_db_path="/tmp/x.db", logic_db_path="/tmp/y.db")
        summary = ai_service.summarize_workspace_context(None, user, inst, include_wishlist=False, include_eom=False)
        self.assertEqual(summary["workspace"], "Main")
        self.assertEqual(summary["total_income"], 1200)
        self.assertEqual(summary["current_month_balance"], 300)
        self.assertEqual(summary["safe_to_spend"], 75)
        self.assertIn("month_over_month", summary)
        self.assertNotIn("projection", summary)
        self.assertNotIn("one_time_transactions", summary)


if __name__ == "__main__":
    unittest.main()
