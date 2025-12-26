import asyncio
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

_temp_dir = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_temp_dir.name}/test.db")
os.environ["API_TOKEN"] = ""

from backend.main import api_health, app, health, root  # noqa: E402


class MainHealthTests(unittest.TestCase):
    def test_health_returns_ok(self) -> None:
        payload = asyncio.run(health())
        self.assertEqual(payload, {"status": "ok"})

    def test_api_health_returns_ok(self) -> None:
        payload = asyncio.run(api_health())
        self.assertEqual(payload, {"status": "ok"})

    def test_root_returns_html(self) -> None:
        body = asyncio.run(root())
        self.assertIn("MyAsset Portfolio Backend", body)

    def test_settings_path_works_without_api_prefix(self) -> None:
        client = TestClient(app)
        response = client.get("/settings")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("target_index_allocations", payload)

    def test_trade_create_succeeds(self) -> None:
        client = TestClient(app)
        asset_response = client.post(
            "/api/assets",
            json={"name": "test-asset", "category": "TEST"},
        )
        self.assertEqual(asset_response.status_code, 200)
        asset_id = asset_response.json()["id"]

        trade_response = client.post(
            f"/api/assets/{asset_id}/trades",
            json={"type": "BUY", "quantity": 1, "price": 1000},
        )
        self.assertEqual(trade_response.status_code, 200)
        payload = trade_response.json()
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["type"], "BUY")
