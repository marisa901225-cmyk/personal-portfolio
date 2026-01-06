"""
Expense AI Model Training Service.

DB 데이터를 기반으로 Naive Bayes 내역 분류 모델 학습.
Migrated from scripts/expenses/train_expense_ai.py for proper import handling.
"""
from __future__ import annotations

import sqlite3
import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

# Default paths
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "storage" / "db" / "portfolio.db"
_DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "data" / "expense_model.joblib"


def train_model(
    db_path: str | None = None, 
    model_path: str | None = None
) -> bool:
    """
    Train expense classification model from database.
    
    Args:
        db_path: Path to SQLite database. Defaults to backend/storage/db/portfolio.db
        model_path: Path to save model. Defaults to backend/data/expense_model.joblib
        
    Returns:
        True if training succeeded, False otherwise
    """
    # Lazy imports to avoid loading heavy ML libraries at module load time
    try:
        import pandas as pd
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.naive_bayes import MultinomialNB
        from sklearn.pipeline import Pipeline
    except ImportError as e:
        logger.error(f"ML dependencies not installed: {e}")
        return False
    
    db_path = db_path or str(_DEFAULT_DB_PATH)
    model_path = model_path or str(_DEFAULT_MODEL_PATH)
    
    logger.info(f"Loading data from {db_path}...")
    
    try:
        conn = sqlite3.connect(db_path)
        
        # 충분한 데이터가 있는 카테고리만 학습 (최소 2건 이상)
        query = """
        SELECT merchant, category 
        FROM expenses 
        WHERE (amount < 0 OR amount = 1.0)
          AND merchant IS NOT NULL 
          AND merchant != ''
          AND category IS NOT NULL 
          AND category != ''
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if len(df) < 10:
            logger.warning("Not enough data for training (minimum 10 records required)")
            return False
            
        logger.info(f"Training with {len(df)} records...")
        
        # 텍스트 전처리 및 모델 파이프라인 구성
        # analyzer='char_wb'와 ngram_range=(2, 5)를 사용하여 한글 단어 일부만으로도 매칭되게 함
        pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 5))),
            ('clf', MultinomialNB(alpha=0.1))  # alpha를 낮춰서 조금 더 민감하게 반응하게 함
        ])
        
        # 학습
        pipeline.fit(df['merchant'], df['category'])
        
        # 저장
        model_dir = Path(model_path).parent
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, model_path)
        
        logger.info(f"Model saved to {model_path}")
        
        # 정확도 대략 확인 (학습 데이터에 대해서만)
        score = pipeline.score(df['merchant'], df['category'])
        logger.info(f"Training accuracy: {score:.2%}")
        
        return True
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        return False


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    success = train_model()
    sys.exit(0 if success else 1)
