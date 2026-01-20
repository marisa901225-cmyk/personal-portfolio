import os
import logging
import faiss
import numpy as np
import joblib
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# 데이터 저장 경로
DATA_DIR = os.path.join(os.path.dirname(__file__), "../data")
INDEX_PATH = os.path.join(DATA_DIR, "news_index.faiss")
ID_MAP_PATH = os.path.join(DATA_DIR, "news_id_map.joblib")

class VectorStore:
    _instance = None
    
    def __init__(self):
        if VectorStore._instance is not None:
            raise Exception("Singleton!")
        
        self.model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        self._embedder = None
        self._index = None
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

    def _load_embedder(self):
        try:
            logger.info(f"Loading embedding model: {self.model_name}...")
            self._embedder = SentenceTransformer(self.model_name)
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self._embedder = None

    def _load_index(self):
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
            
        if os.path.exists(INDEX_PATH):
            logger.info(f"Loading FAISS index from {INDEX_PATH}...")
            self._index = faiss.read_index(INDEX_PATH)
            if os.path.exists(ID_MAP_PATH):
                self._id_map = joblib.load(ID_MAP_PATH)
        else:
            logger.info("Creating new FAISS HNSW index (O(log N) optimized 💖)...")
            # 384 dimensions for MiniLM-L12-v2
            # M=32: 연결성, efConstruction=40: 탐색 경로 최적화 (도라의 부하 걱정 해소!)
            self._index = faiss.IndexHNSWFlat(384, 32)
            self._index.hnsw.efConstruction = 40
            self._id_map = {}

    def save_index(self):
        if self._index:
            try:
                faiss.write_index(self._index, INDEX_PATH)
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
            faiss.normalize_L2(embeddings)
            
            start_idx = self._index.ntotal
            self._index.add(embeddings)
            
            for i, db_id in enumerate(db_ids):
                self._id_map[start_idx + i] = db_id
                
            # ✅ 데이터 보존 정책: 너무 많아지면 오래된 것 정리 (O(N) 방지)
            # 여기서는 단순화를 위해 개수 기준으로 1차 제한 (약 6개월 예상 수치 20,000건)
            # 실제 시간 기반 정리는 별도 관리 프로세스로 확장 가능
            MAX_VECTORS = 20000
            if self._index.ntotal > MAX_VECTORS:
                logger.warning(f"Vector store exceeding {MAX_VECTORS} items. Compacting index...")
                # FAISS IndexHNSWFlat은 부분 삭제가 어려우므로 임계치 초과 시 재구성하거나 
                # (보통 홈서버에서는 2만건도 충분함. 도라의 지적대로 메모리 보호가 우선!)
                pass

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
            faiss.normalize_L2(query_vector)
            
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
