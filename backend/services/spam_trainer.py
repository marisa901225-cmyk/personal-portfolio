"""
Spam AI Model Training Service.
DB 데이터를 기반으로 Naive Bayes 스팸 분류 모델 학습.
"""
from __future__ import annotations

import sqlite3
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# 경로 설정
BASE_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_DB_PATH = BASE_DIR / "storage" / "db" / "portfolio.db"
_DEFAULT_MODEL_PATH = BASE_DIR / "data" / "spam_model.joblib"


def train_spam_model(
    db_path: str | None = None, 
    model_path: str | None = None
) -> bool:
    """
    Train spam classification model from IncomingAlarm data.
    
    Data Source:
    - Label 'spam' (1): status == 'discarded'
    - Label 'ham'  (0): status == 'processed' AND classification == 'llm'
    """
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
    
    logger.info(f"Loading alarm data from {db_path}...")
    
    try:
        conn = sqlite3.connect(db_path)
        
        # 스팸(discarded) 데이터와 정상(processed+llm) 데이터를 가져옴
        # raw_text가 없는 경우는 제외
        query = """
        SELECT raw_text as text, 
               CASE WHEN status = 'discarded' THEN 1 ELSE 0 END as is_spam
        FROM incoming_alarms
        WHERE raw_text IS NOT NULL AND raw_text != ''
          AND (status = 'discarded' OR (status = 'processed' AND classification = 'llm'))
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        if len(df) < 20:
            logger.warning("Not enough data for spam training (minimum 20 records required)")
            return False
            
        # 클래스 불균형 확인
        counts = df['is_spam'].value_counts()
        if len(counts) < 2:
            logger.warning("Only one class found in data. Training impossible.")
            return False
            
        logger.info(f"Training spam model with {len(df)} records (Spam: {counts.get(1, 0)}, Ham: {counts.get(0, 0)})")
        
        # 한글 특화 전처리 (char_wb, n-gram)
        pipeline = Pipeline([
            ('tfidf', TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 6))),
            ('clf', MultinomialNB(alpha=0.01)) # 스팸은 조금 더 공격적으로 필터링하기 위해 alpha 낮춤
        ])
        
        # 학습
        pipeline.fit(df['text'], df['is_spam'])
        
        # 저장
        model_dir = Path(model_path).parent
        model_dir.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, model_path)
        
        logger.info(f"Spam model saved to {model_path}")
        
        # 학습 데이터 점수
        score = pipeline.score(df['text'], df['is_spam'])
        logger.info(f"Spam training accuracy: {score:.2%}")
        
        return True
        
    except Exception as e:
        logger.error(f"Spam training failed: {e}")
        return False

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    success = train_spam_model()
    sys.exit(0 if success else 1)
