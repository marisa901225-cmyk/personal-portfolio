import hashlib
import logging
import os
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import joblib
import numpy as np

logger = logging.getLogger(__name__)

# 데이터 저장 경로
DATA_DIR = os.path.join(os.path.dirname(__file__), "../data")
INDEX_PATH = os.path.join(DATA_DIR, "news_index.faiss")
ID_MAP_PATH = os.path.join(DATA_DIR, "news_id_map.joblib")
_ECONOMY_CATEGORY_TAGS = {"Market", "Macro", "FX/Rates", "Crypto", "Tech/Semicon", "EV/Auto"}
_ECONOMY_SOURCE_PREFIXES = ("Naver", "Google", "GoogleNews", "FRED", "ECOS", "BOK")


class LightweightHashEmbedder:
    """개인용 뉴스 검색에 맞춘 저비용 해시 임베더."""

    _WORD_RE = re.compile(r"[0-9a-zA-Z가-힣]+")

    def __init__(self, dimension: int = 384, max_chars: int = 4000):
        self.dimension = max(64, int(dimension))
        self.max_chars = max(256, int(max_chars))

    def _iter_features(self, text: str):
        normalized = re.sub(r"\s+", " ", str(text or "").lower()).strip()
        if not normalized:
            return

        for token in self._WORD_RE.findall(normalized):
            if len(token) >= 2:
                yield f"w:{token}"

        compact = normalized.replace(" ", "")[: self.max_chars]
        for n in (2, 3, 4):
            if len(compact) < n:
                continue
            for idx in range(len(compact) - n + 1):
                yield f"c{n}:{compact[idx:idx+n]}"

    def _encode_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for feature in self._iter_features(text) or ():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if (digest[4] & 1) else -1.0
            vector[index] += sign

        if not np.any(vector):
            vector[0] = 1.0
        return vector

    def encode(self, texts: list[str], convert_to_numpy: bool = True):
        matrix = np.vstack([self._encode_one(text) for text in texts]).astype(np.float32, copy=False)
        if convert_to_numpy:
            return matrix
        return matrix.tolist()

class VectorStore:
    _instance = None
    
    def __init__(self):
        if VectorStore._instance is not None:
            raise Exception("Singleton!")
        
        self.model_name = os.environ.get(
            "VECTOR_STORE_MODEL_NAME",
            "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        )
        self.backend = os.environ.get("VECTOR_STORE_BACKEND", "hash").strip().lower()
        self.dimension = max(64, int(os.environ.get("VECTOR_STORE_DIM", "384")))
        self.max_vectors = max(1000, int(os.environ.get("VECTOR_STORE_MAX_VECTORS", "20000")))
        self.game_retention_days = max(7, int(os.environ.get("VECTOR_STORE_GAME_RETENTION_DAYS", "90")))
        self.economy_retention_quarters = max(
            1,
            int(os.environ.get("VECTOR_STORE_ECONOMY_RETENTION_QUARTERS", "8")),
        )
        self._embedder = None
        self._index = None
        self._faiss = None
        self._id_map = {} # FAISS ID -> DB ID (or inverse if needed, usually direct mapping) (idx -> db_id)
        
        # Load resources
        self._load_embedder()
        self._load_index()

        VectorStore._instance = self

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = VectorStore()
        return cls._instance

    @staticmethod
    def _parse_hf_hub_url(url: str) -> tuple[str, str | None, str]:
        parsed = urlparse(str(url or ""))
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if "resolve" not in parts:
            raise ValueError(f"Unsupported Hugging Face Hub URL: {url}")

        resolve_idx = parts.index("resolve")
        if resolve_idx < 1 or resolve_idx + 2 >= len(parts):
            raise ValueError(f"Malformed Hugging Face Hub URL: {url}")

        repo_id = "/".join(parts[:resolve_idx])
        revision = parts[resolve_idx + 1]
        filename = "/".join(parts[resolve_idx + 2 :])
        return repo_id, revision, filename

    @classmethod
    def _ensure_huggingface_hub_compat(cls):
        try:
            import huggingface_hub
        except ImportError:
            return

        if hasattr(huggingface_hub, "cached_download"):
            return

        hf_hub_download = getattr(huggingface_hub, "hf_hub_download", None)
        if hf_hub_download is None:
            logger.warning("huggingface_hub has no hf_hub_download; cached_download shim not installed")
            return

        def cached_download(*, url, cache_dir=None, force_filename=None, library_name=None, library_version=None, user_agent=None, use_auth_token=None, token=None, **kwargs):
            repo_id, revision, filename = cls._parse_hf_hub_url(url)
            resolved_token = token if token is not None else use_auth_token
            downloaded_path = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                revision=revision,
                cache_dir=cache_dir,
                library_name=library_name,
                library_version=library_version,
                user_agent=user_agent,
                token=resolved_token,
                force_download=bool(kwargs.get("force_download", False)),
                local_files_only=bool(kwargs.get("local_files_only", False)),
                proxies=kwargs.get("proxies"),
                etag_timeout=kwargs.get("etag_timeout", 10),
                headers=kwargs.get("headers"),
                endpoint=kwargs.get("endpoint"),
                resume_download=kwargs.get("resume_download"),
            )

            if force_filename:
                if not cache_dir:
                    raise ValueError("cache_dir is required when force_filename is set")
                target_path = Path(cache_dir) / force_filename
                target_path.parent.mkdir(parents=True, exist_ok=True)
                if Path(downloaded_path).resolve() != target_path.resolve():
                    shutil.copy2(downloaded_path, target_path)
                return str(target_path)

            return downloaded_path

        huggingface_hub.cached_download = cached_download
        logger.info("Installed huggingface_hub.cached_download compatibility shim")

    def _load_faiss(self):
        if self._faiss is not None:
            return

        try:
            import faiss
        except ImportError as exc:
            logger.error("Failed to import faiss: %s", exc)
            self._faiss = None
            return

        self._faiss = faiss

    def _load_embedder(self):
        if self.backend in {"hash", "lightweight"}:
            logger.info("Using lightweight hash embedder for vector store (dim=%d)", self.dimension)
            self._embedder = LightweightHashEmbedder(dimension=self.dimension)
            return

        try:
            self._ensure_huggingface_hub_compat()
            from sentence_transformers import SentenceTransformer

            logger.info(f"Loading embedding model: {self.model_name}...")
            self._embedder = SentenceTransformer(self.model_name)
        except Exception as e:
            logger.error("Failed to load embedding model '%s': %s", self.model_name, e)
            logger.info("Falling back to lightweight hash embedder (dim=%d)", self.dimension)
            self._embedder = LightweightHashEmbedder(dimension=self.dimension)

    def _create_empty_index(self):
        index = self._faiss.IndexHNSWFlat(self.dimension, 32)
        index.hnsw.efConstruction = 40
        return index

    @staticmethod
    def _normalize_datetime(value) -> datetime:
        if isinstance(value, datetime):
            dt = value
        elif value:
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                dt = datetime.min.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _quarter_index(dt: datetime) -> int:
        return dt.year * 4 + ((dt.month - 1) // 3)

    @classmethod
    def _is_economy_row(cls, row) -> bool:
        source_name = str(getattr(row, "source_name", "") or "")
        game_tag = str(getattr(row, "game_tag", "") or "")
        category_tag = str(getattr(row, "category_tag", "") or "")
        return (
            game_tag == "Economy"
            or category_tag in _ECONOMY_CATEGORY_TAGS
            or source_name.startswith(_ECONOMY_SOURCE_PREFIXES)
        )

    @classmethod
    def _row_to_text(cls, row) -> str:
        label = str(getattr(row, "game_tag", "") or getattr(row, "category_tag", "") or "General")
        title = str(getattr(row, "title", "") or "")
        body = str(
            getattr(row, "summary", "")
            or getattr(row, "chunk_content", "")
            or getattr(row, "full_content", "")
            or ""
        )
        return f"[{label}] {title}\n{body}".strip()

    @classmethod
    def _retention_sort_key(
        cls,
        row,
        *,
        now: datetime,
        game_retention_days: int,
        economy_retention_quarters: int,
    ) -> tuple[int, int, float, int]:
        published_at = cls._normalize_datetime(getattr(row, "published_at", None))
        is_economy = cls._is_economy_row(row)
        quarter_index = cls._quarter_index(published_at)
        current_quarter = cls._quarter_index(now)
        economy_cutoff = current_quarter - max(0, economy_retention_quarters - 1)
        game_cutoff = now - timedelta(days=game_retention_days)

        if is_economy and quarter_index >= economy_cutoff:
            bucket = 0
        elif not is_economy and published_at >= game_cutoff:
            bucket = 1
        elif is_economy:
            bucket = 2
        else:
            bucket = 3

        return (
            bucket,
            -quarter_index,
            -published_at.timestamp(),
            -int(getattr(row, "id", 0) or 0),
        )

    @classmethod
    def _select_rows_for_retention(
        cls,
        rows,
        *,
        now: datetime | None = None,
        max_vectors: int = 20000,
        game_retention_days: int = 90,
        economy_retention_quarters: int = 8,
    ):
        base_now = now or datetime.now(timezone.utc)
        if base_now.tzinfo is None:
            base_now = base_now.replace(tzinfo=timezone.utc)
        else:
            base_now = base_now.astimezone(timezone.utc)

        ordered = sorted(
            rows,
            key=lambda row: cls._retention_sort_key(
                row,
                now=base_now,
                game_retention_days=game_retention_days,
                economy_retention_quarters=economy_retention_quarters,
            ),
        )
        return ordered[: max(1, int(max_vectors))]

    def _load_rows_for_db_ids(self, db_ids: list[int]):
        if not db_ids:
            return []

        from ..core.db import SessionLocal
        from ..core.models import GameNews

        with SessionLocal() as db:
            rows = db.query(GameNews).filter(GameNews.id.in_(db_ids)).all()
        return rows

    def _rebuild_index_from_rows(self, rows):
        self._index = self._create_empty_index()
        self._id_map = {}

        batch_size = 256
        for start in range(0, len(rows), batch_size):
            chunk = rows[start : start + batch_size]
            texts = [self._row_to_text(row) for row in chunk]
            db_ids = [int(row.id) for row in chunk]
            embeddings = self._embedder.encode(texts, convert_to_numpy=True)
            self._faiss.normalize_L2(embeddings)

            offset = self._index.ntotal
            self._index.add(embeddings)
            for idx, db_id in enumerate(db_ids):
                self._id_map[offset + idx] = db_id

    def _compact_index_if_needed(self):
        if self._index is None or self._index.ntotal <= self.max_vectors:
            return

        db_ids = list(dict.fromkeys(int(db_id) for db_id in self._id_map.values()))
        rows = self._load_rows_for_db_ids(db_ids)
        if not rows:
            logger.warning("Vector store compaction skipped because no DB rows were found")
            return

        retained_rows = self._select_rows_for_retention(
            rows,
            max_vectors=self.max_vectors,
            game_retention_days=self.game_retention_days,
            economy_retention_quarters=self.economy_retention_quarters,
        )

        if len(retained_rows) >= len(rows):
            return

        logger.info(
            "Compacting vector store from %d to %d rows (max=%d, game_days=%d, econ_quarters=%d)",
            len(rows),
            len(retained_rows),
            self.max_vectors,
            self.game_retention_days,
            self.economy_retention_quarters,
        )
        self._rebuild_index_from_rows(retained_rows)

    def _load_index(self):
        self._load_faiss()
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)

        if self._faiss is None:
            self._index = None
            return

        if os.path.exists(INDEX_PATH):
            logger.info(f"Loading FAISS index from {INDEX_PATH}...")
            self._index = self._faiss.read_index(INDEX_PATH)
            if os.path.exists(ID_MAP_PATH):
                self._id_map = joblib.load(ID_MAP_PATH)
        else:
            logger.info("Creating new FAISS HNSW index (O(log N) optimized 💖)...")
            # 개인용 뉴스 DB 기준으로 차원 수를 낮게 유지한다.
            # M=32: 연결성, efConstruction=40: 탐색 경로 최적화 (도라의 부하 걱정 해소!)
            self._index = self._create_empty_index()
            self._id_map = {}

    def save_index(self):
        if self._index is not None and self._faiss is not None:
            try:
                self._faiss.write_index(self._index, INDEX_PATH)
                joblib.dump(self._id_map, ID_MAP_PATH)
                logger.info("FAISS index saved.")
            except Exception as e:
                logger.error(f"Failed to save index: {e}")

    def add_texts(self, texts: list[str], db_ids: list[int]):
        """
        텍스트를 임베딩하여 인덱스에 추가 (Retention Policy 적용 💖)
        """
        if not self._embedder or not self._index:
            logger.error("Embedder or Index not initialized")
            return

        try:
            embeddings = self._embedder.encode(texts, convert_to_numpy=True)
            self._faiss.normalize_L2(embeddings)
            
            start_idx = self._index.ntotal
            self._index.add(embeddings)
            
            for i, db_id in enumerate(db_ids):
                self._id_map[start_idx + i] = db_id
                
            self._compact_index_if_needed()
            self.save_index()
            logger.info(f"Added {len(texts)} documents to vector index. Total: {self._index.ntotal}")
        except Exception as e:
            logger.error(f"Failed to add texts to index: {e}")

    def search(self, query: str, k: int = 3) -> list[tuple[int, float]]:
        """
        유사 문서 검색
        Returns: [(db_id, score), ...]
        """
        if not self._embedder or not self._index or self._index.ntotal == 0:
            return []

        try:
            query_vector = self._embedder.encode([query], convert_to_numpy=True)
            self._faiss.normalize_L2(query_vector)
            
            distances, indices = self._index.search(query_vector, k)
            
            results = []
            for i in range(k):
                idx = indices[0][i]
                score = distances[0][i]
                if idx != -1 and idx in self._id_map:
                    results.append((self._id_map[idx], float(score)))
            
            return results
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []
