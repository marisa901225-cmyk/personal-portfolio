import asyncio
import os
import tempfile
import unittest

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_temp_dir.name}/test.db")
os.environ.setdefault("API_TOKEN", "")

from backend.main import health, root  # noqa: E402


class MainHealthTests(unittest.TestCase):
    def test_health_returns_ok(self) -> None:
        payload = asyncio.run(health())
        self.assertEqual(payload, {"status": "ok"})

    def test_root_returns_html(self) -> None:
        body = asyncio.run(root())
        self.assertIn("MyAsset Portfolio Backend", body)
