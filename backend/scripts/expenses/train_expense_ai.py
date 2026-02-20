#!/usr/bin/env python3
"""
DB 데이터를 기반으로 Naive Bayes 내역 분류 모델 학습
"""
import sqlite3
import pandas as pd
import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

def train_model(db_path: str, model_path: str):
    print(f"📊 {db_path}에서 데이터 로드 중...")
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
        print("❌ 학습할 데이터가 너무 부족합니다. (최소 10건 필요)")
        return False
        
    print(f"📈 {len(df)}건의 데이터로 학습 시작...")
    
    # 텍스트 전처리 및 모델 파이프라인 구성
    # analyzer='char_wb'와 ngram_range=(2, 5)를 사용하여 한글 단어 일부만으로도 매칭되게 함
    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 5))),
        ('clf', MultinomialNB(alpha=0.1)) # alpha를 낮춰서 조금 더 민감하게 반응하게 함
    ])
    
    # 학습
    pipeline.fit(df['merchant'], df['category'])
    
    # 저장
    model_dir = Path(model_path).parent
    model_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, model_path)
    
    print(f"✅ 모델 저장 완료: {model_path}")
    
    # 정확도 대략 확인 (학습 데이터에 대해서만)
    score = pipeline.score(df['merchant'], df['category'])
    print(f"🎯 학습 데이터 정확도: {score:.2%}")
    return True

if __name__ == "__main__":
    train_model(
        str(REPO_ROOT / "backend" / "storage" / "db" / "portfolio.db"),
        str(REPO_ROOT / "backend" / "data" / "expense_model.joblib"),
    )
