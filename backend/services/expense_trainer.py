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
        # 데이터 로드 (With 문맥 매니저로 자동 Close)
        with sqlite3.connect(db_path) as conn:
            # SQL 단에서 정규화: TRIM() 사용, amount < 0 지출만 대상
            query = """
            SELECT TRIM(merchant) as merchant, TRIM(category) as category 
            FROM expenses 
            WHERE amount < 0
              AND merchant IS NOT NULL 
              AND TRIM(merchant) != ''
              AND category IS NOT NULL 
              AND TRIM(category) != ''
            """
            df = pd.read_sql_query(query, conn)
        
        # Pandas 단에서 추가 정규화
        df["merchant"] = df["merchant"].astype(str).str.strip()
        df = df[df["merchant"] != ""]
        
        # 데이터 건수 체크
        if len(df) < 10:
            logger.warning("Not enough data for training (minimum 10 records required)")
            return False
            
        # 카테고리 다양성 체크
        if df["category"].nunique() < 2:
            logger.warning("Not enough category diversity (at least 2 categories required)")
            return False
            
        logger.info(f"Training with {len(df)} records ({df['category'].nunique()} categories)...")
        
        # 0.5 홀드아웃 검증 (데이터가 충분할 때만)
        do_split = len(df) >= 20
        if do_split:
            from sklearn.model_selection import train_test_split
            X_train, X_test, y_train, y_test = train_test_split(
                df["merchant"], df["category"], 
                test_size=0.2, 
                random_state=42, 
                stratify=df["category"]
            )
        else:
            X_train, y_train = df["merchant"], df["category"]
            X_test, y_test = X_train, y_train

        # 텍스트 전처리 및 모델 파이프라인 구성
        pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 5))),
            ('clf', MultinomialNB(alpha=0.1))
        ])
        
        # 학습
        pipeline.fit(X_train, y_train)
        
        # 원자적(Atomic) 저장: 임시 파일에 쓰고 교체하여 동시 읽기 안전 확보
        model_path_obj = Path(model_path)
        model_path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        tmp_path = model_path_obj.with_suffix(".joblib.tmp")
        joblib.dump(pipeline, str(tmp_path))
        tmp_path.replace(model_path_obj)
        
        logger.info(f"Model saved atomically to {model_path}")
        
        # 정확도 확인
        score = pipeline.score(X_test, y_test)
        score_type = "Validation" if do_split else "Training-set"
        logger.info(f"{score_type} accuracy: {score:.2%}")
        
        return True
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        return False


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    success = train_model()
    sys.exit(0 if success else 1)
