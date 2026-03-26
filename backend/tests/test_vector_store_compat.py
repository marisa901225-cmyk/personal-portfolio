import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.vector_store import LightweightHashEmbedder, VectorStore


class VectorStoreCompatTests(unittest.TestCase):
    def test_lightweight_hash_embedder_returns_fixed_shape(self):
        embedder = LightweightHashEmbedder(dimension=384)

        matrix = embedder.encode(["한글 뉴스 요약 테스트", "Steam ranking digest"], convert_to_numpy=True)

        self.assertEqual(matrix.shape, (2, 384))

    def test_parse_hf_hub_url(self):
        repo_id, revision, filename = VectorStore._parse_hf_hub_url(
            "https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2/resolve/main/modules.json"
        )

        self.assertEqual(repo_id, "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        self.assertEqual(revision, "main")
        self.assertEqual(filename, "modules.json")

    def test_install_cached_download_compat_shim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            calls: list[dict] = []
            source_path = Path(tmpdir) / "downloaded.bin"
            source_path.write_text("vector-store", encoding="utf-8")

            def fake_hf_hub_download(**kwargs):
                calls.append(kwargs)
                return str(source_path)

            fake_module = types.SimpleNamespace(
                __version__="0.36.0",
                hf_hub_download=fake_hf_hub_download,
            )

            with patch.dict(sys.modules, {"huggingface_hub": fake_module}):
                VectorStore._ensure_huggingface_hub_compat()

                target = fake_module.cached_download(
                    url="https://huggingface.co/org/model/resolve/rev-123/subdir/config.json",
                    cache_dir=tmpdir,
                    force_filename="org_model/subdir/config.json",
                    library_name="sentence-transformers",
                    library_version="2.2.2",
                    use_auth_token="token-abc",
                )

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["repo_id"], "org/model")
            self.assertEqual(calls[0]["revision"], "rev-123")
            self.assertEqual(calls[0]["filename"], "subdir/config.json")
            self.assertEqual(calls[0]["token"], "token-abc")

            target_path = Path(target)
            self.assertTrue(target_path.exists())
            self.assertEqual(target_path.read_text(encoding="utf-8"), "vector-store")

    def test_retention_prefers_recent_economy_quarters(self):
        now = datetime(2026, 3, 18, tzinfo=timezone.utc)
        rows = [
            SimpleNamespace(
                id=1,
                source_name="Naver",
                game_tag="Economy",
                category_tag="Market",
                title="경제 최근",
                full_content="a",
                published_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id=2,
                source_name="GoogleNews",
                game_tag="Economy",
                category_tag="Macro",
                title="경제 이전 분기",
                full_content="b",
                published_at=datetime(2025, 12, 15, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id=3,
                source_name="SteamSpy",
                game_tag="Steam",
                category_tag=None,
                title="게임 최근",
                full_content="c",
                published_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id=4,
                source_name="SteamSpy",
                game_tag="Steam",
                category_tag=None,
                title="게임 오래됨",
                full_content="d",
                published_at=datetime(2025, 8, 1, tzinfo=timezone.utc),
            ),
        ]

        selected = VectorStore._select_rows_for_retention(
            rows,
            now=now,
            max_vectors=3,
            game_retention_days=90,
            economy_retention_quarters=2,
        )

        self.assertEqual([row.id for row in selected], [1, 2, 3])

    def test_retention_truncates_games_before_recent_economy(self):
        now = datetime(2026, 3, 18, tzinfo=timezone.utc)
        rows = [
            SimpleNamespace(
                id=1,
                source_name="Naver",
                game_tag="Economy",
                category_tag="Market",
                title="경제 A",
                full_content="a",
                published_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id=2,
                source_name="GoogleNews",
                game_tag="Economy",
                category_tag="Macro",
                title="경제 B",
                full_content="b",
                published_at=datetime(2026, 2, 10, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id=3,
                source_name="SteamSpy",
                game_tag="Steam",
                category_tag=None,
                title="게임 A",
                full_content="c",
                published_at=datetime(2026, 3, 15, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                id=4,
                source_name="Inven Game Review",
                game_tag="Gaming",
                category_tag="Review",
                title="게임 B",
                full_content="d",
                published_at=datetime(2026, 3, 14, tzinfo=timezone.utc),
            ),
        ]

        selected = VectorStore._select_rows_for_retention(
            rows,
            now=now,
            max_vectors=2,
            game_retention_days=90,
            economy_retention_quarters=8,
        )

        self.assertEqual([row.id for row in selected], [1, 2])


if __name__ == "__main__":
    unittest.main()
