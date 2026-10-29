"""Restart-server request/status files shared with the host-side helper."""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from app.services import server_restart_service as srs


class TestServerRestart(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())

    def test_helper_offline_without_fresh_heartbeat(self):
        self.assertFalse(srs.watcher_online(self.root))
        hb = self.root / srs.HEARTBEAT_FILE
        hb.touch()
        self.assertTrue(srs.watcher_online(self.root))
        old = time.time() - srs.HEARTBEAT_MAX_AGE_S - 5
        os.utime(hb, (old, old))
        self.assertFalse(srs.watcher_online(self.root))

    def test_request_is_queued_once_and_resets_status(self):
        (self.root / srs.STATUS_FILE).write_text('{"state": "failed", "message": "old"}')
        first = srs.request_restart("alice", self.root)
        self.assertTrue(first["queued"])
        self.assertTrue(first["pending"])
        self.assertEqual(first["state"], "queued")
        self.assertFalse(srs.request_restart("bob", self.root)["queued"])

    def test_stale_request_is_not_pending(self):
        srs.request_restart("alice", self.root)
        old = time.time() - srs.REQUEST_STALE_S - 5
        os.utime(self.root / srs.REQUEST_FILE, (old, old))
        self.assertFalse(srs.request_pending(self.root))

    def test_status_tolerates_garbage(self):
        (self.root / srs.STATUS_FILE).write_text("not json")
        st = srs.status(self.root)
        self.assertEqual(st["state"], "idle")
        self.assertEqual(st["boot_id"], srs.BOOT_ID)


if __name__ == "__main__":
    unittest.main()
