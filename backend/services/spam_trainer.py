"""
Spam AI Model Training Service.
DB 데이터를 기반으로 Naive Bayes 스팸 분류 모델 학습.
"""
from __future__ import annotations

import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_DB_PATH = BASE_DIR / "storage" / "db" / "portfolio.db"
_DEFAULT_MODEL_PATH = BASE_DIR / "data" / "spam_model.joblib"


def train_spam_model(db_path: str | None = None, model_path: str | None = None) -> bool:
    try:
        import pandas as pd
        import joblib
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.naive_bayes import MultinomialNB
        from sklearn.pipeline import Pipeline
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import classification_report
    except ImportError as e:
        logger.error(f"ML dependencies not installed: {e}")
        return False

    db_path = db_path or str(_DEFAULT_DB_PATH)
    model_path = model_path or str(_DEFAULT_MODEL_PATH)

    logger.info(f"Loading alarm data from {db_path}...")

    try:
        conn = sqlite3.connect(db_path)

        # ✅ 학습 입력을 추론 입력(full_check_text)과 최대한 동일하게 맞춤
        # ✅ discarded라도 placeholder/ignored는 스팸 학습에서 제외(라벨 노이즈 감소)
        query = """
        SELECT
            COALESCE(sender, '')      AS sender,
            COALESCE(app_title, '')   AS app_title,
            COALESCE(conversation, '') AS conversation,
            COALESCE(raw_text, '')    AS raw_text,
            status,
            COALESCE(classification, '') AS classification,
            CASE
              WHEN status = 'discarded' AND classification NOT IN ('placeholder', 'ignored')
                THEN 1
              WHEN status = 'processed' AND classification = 'llm'
                THEN 0
              ELSE NULL
            END AS is_spam
        FROM incoming_alarms
        WHERE raw_text IS NOT NULL AND raw_text != ''
          AND (
                (status = 'discarded' AND classification NOT IN ('placeholder', 'ignored'))
             OR (status = 'processed' AND classification = 'llm')
          )
        """
        df = pd.read_sql_query(query, conn)
        conn.close()

        # is_spam NULL 방어
        df = df[df["is_spam"].notna()].copy()
        df["is_spam"] = df["is_spam"].astype(int)

        if len(df) < 100:
            logger.warning("도라의 조언 💖: 데이터가 너무 적으면 편향이 생길 수 있어요! (현재 %d건 / 최소 100건 필요). 학습을 건너뜁니다.", len(df))
            return False

        counts = df["is_spam"].value_counts()
        if len(counts) < 2:
            logger.warning("Only one class found in data. Training impossible.")
            return False

        # ✅ 학습 텍스트 구성: 추론 때처럼 합친다
        df["text"] = (
            "[" + df["sender"].astype(str).str.strip() + "] "
            + df["app_title"].astype(str).str.strip() + " "
            + df["conversation"].astype(str).str.strip() + " "
            + df["raw_text"].astype(str).str.strip()
        ).str.replace(r"\s+", " ", regex=True).str.strip()

        logger.info(
            "Training spam model with %s records (Spam: %s, Ham: %s)",
            len(df), counts.get(1, 0), counts.get(0, 0)
        )

        pipeline = Pipeline([
            # 한글 특화: char_wb n-gram (2, 6) - 도라의 신의 한 수 💖
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 6), min_df=2)),
            ("clf", MultinomialNB(alpha=0.01)),
        ])

        # ✅ 홀드아웃 평가 (정밀도(Precision) 확인이 핵심 - 도라 제안 💖)
        X_train, X_test, y_train, y_test = train_test_split(
            df["text"],
            df["is_spam"],
            test_size=0.2,
            random_state=42,
            stratify=df["is_spam"],
        )

        pipeline.fit(X_train, y_train)

        y_pred = pipeline.predict(X_test)
        report = classification_report(y_test, y_pred, digits=3)
        logger.info("Spam model evaluation (Precision priority 💖):\n%s", report)

        # 저장
        Path(model_path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(pipeline, model_path)
        logger.info(f"Spam model saved to {model_path}")

        return True

    except Exception:
        logger.exception("Spam training failed")
        return False


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    success = train_spam_model()
    sys.exit(0 if success else 1)
