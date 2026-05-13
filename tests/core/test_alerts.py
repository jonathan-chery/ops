"""Tests for ops.core.alerts."""

from unittest.mock import MagicMock, patch

from ops.core.alerts import AlertManager


class TestAlertManager:
    def test_send_alert_without_webhook_returns_false(self, tmp_ops_dir):
        mgr = AlertManager(state_dir=str(tmp_ops_dir))
        assert mgr.send_alert("app", 100, "node", "fail") is False

    @patch("ops.core.alerts.requests.post")
    def test_send_alert_dispatches(self, mock_post, tmp_ops_dir):
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        mgr = AlertManager(webhook_url="https://example.com/hook", state_dir=str(tmp_ops_dir))
        assert mgr.send_alert("app", 100, "node", "error msg") is True
        assert mock_post.call_count == 1
        payload = mock_post.call_args[1]["json"]
        assert payload["app"] == "app"
        assert payload["vmid"] == 100
        assert payload["node"] == "node"
        assert payload["error"] == "error msg"

    @patch("ops.core.alerts.requests.post")
    def test_send_alert_respects_cooldown(self, mock_post, tmp_ops_dir):
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        mgr = AlertManager(
            webhook_url="https://example.com/hook",
            cooldown_seconds=300,
            state_dir=str(tmp_ops_dir),
        )
        assert mgr.send_alert("app", 100, "node", "error") is True
        assert mgr.send_alert("app", 100, "node", "error again") is False

    @patch("ops.core.alerts.requests.post")
    def test_test_alert(self, mock_post, tmp_ops_dir):
        mock_post.return_value = MagicMock(status_code=200, raise_for_status=lambda: None)
        mgr = AlertManager(webhook_url="https://example.com/hook", state_dir=str(tmp_ops_dir))
        assert mgr.test_alert() is True

    @patch("ops.core.alerts.requests.post")
    def test_send_alert_transport_failure(self, mock_post, tmp_ops_dir):
        import requests

        mock_post.side_effect = requests.RequestException("timeout")
        mgr = AlertManager(webhook_url="https://example.com/hook", state_dir=str(tmp_ops_dir))
        assert mgr.send_alert("app", 100, "node", "error") is False
