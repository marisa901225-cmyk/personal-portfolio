import asyncio
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

# DATABASE_URL is managed by conftest.py
os.environ["API_TOKEN"] = "test-token"

from backend.main import api_health, app, health, root  # noqa: E402
from backend.core.db_migrations import ensure_schema # noqa: E402


class MainHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        ensure_schema()
        os.environ["API_TOKEN"] = "test-token"
        self.headers = {"X-API-Token": os.environ["API_TOKEN"]}

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
        response = client.get("/settings", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("target_index_allocations", payload)

    def test_trade_create_succeeds(self) -> None:
        client = TestClient(app)
        asset_response = client.post(
            "/api/assets",
            headers=self.headers,
            json={"name": "test-asset", "category": "TEST"},
        )
        self.assertEqual(asset_response.status_code, 200)
        asset_id = asset_response.json()["id"]

        trade_response = client.post(
            f"/api/assets/{asset_id}/trades",
            headers=self.headers,
            json={"type": "BUY", "quantity": 1, "price": 1000},
        )
        self.assertEqual(trade_response.status_code, 200)
        payload = trade_response.json()
        self.assertEqual(payload["asset_id"], asset_id)
        self.assertEqual(payload["type"], "BUY")

    def test_portfolio_excludes_soft_deleted_assets(self) -> None:
        client = TestClient(app)

        create_res = client.post(
            "/api/assets",
            headers=self.headers,
            json={"name": "delete-me", "category": "TEST"},
        )
        self.assertEqual(create_res.status_code, 200)
        asset_id = create_res.json()["id"]

        delete_res = client.delete(f"/api/assets/{asset_id}", headers=self.headers)
        self.assertEqual(delete_res.status_code, 200)

        portfolio_res = client.get("/api/portfolio", headers=self.headers)
        self.assertEqual(portfolio_res.status_code, 200)
        payload = portfolio_res.json()
        asset_ids = {asset["id"] for asset in payload["assets"]}
        self.assertNotIn(asset_id, asset_ids)
