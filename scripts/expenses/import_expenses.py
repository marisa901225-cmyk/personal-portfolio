#!/usr/bin/env python3
"""
카드사 및 통장 거래내역 자동 임포트 스크립트
지원: Excel (.xlsx), CSV 파일
자동 카테고리 분류 + 중복 제거
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

import pandas as pd
import re
import joblib
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

# Backend 모듈 임포트를 위한 경로 추가
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backend.models import Expense, User, MerchantPattern
from backend.services.users import get_or_create_single_user

KEYWORD_CONFIG_PATH = REPO_ROOT / "backend" / "expense_category_keywords.json"


def load_category_keywords() -> dict[str, list[str]]:
    try:
        with KEYWORD_CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, list)}


CATEGORY_KEYWORDS = load_category_keywords()

GENERIC_METHODS = {"creditcard", "checkcard", "banktransfer"}


def is_generic_method(method: str) -> bool:
    return method.strip().lower() in GENERIC_METHODS


def classify_category(merchant: str, amount: float, learned_patterns: dict[str, str] = None, model: any = None) -> str:
    """
    상점명과 금액을 기반으로 카테고리 자동 분류
    
    Args:
        merchant: 가맹점명
        amount: 금액 (양수: 수입, 음수: 지출)
        learned_patterns: DB에서 가져온 가맹점-카테고리 매핑 사전
    
    Returns:
        카테고리명 (식비, 교통, 쇼핑, 통신, 구독, 이체, 기타)
    """
    # 0. DB에서 학습된 패턴 우선 사용 (가장 정확)
    if learned_patterns and merchant in learned_patterns:
        return learned_patterns[merchant]

    # 1. 학습된 모델(AI) 사용
    if model and amount < 0:
        try:
            return model.predict([merchant])[0]
        except Exception:
            pass

    # 2. 학습된 패턴(파일 기반) 사용
    try:
        from backend.learned_merchant_rules import classify_with_learned_patterns
        learned_category = classify_with_learned_patterns(merchant)
        if learned_category:
            return learned_category
    except (ImportError, ModuleNotFoundError):
        # learned_merchant_rules.py가 없으면 스킵
        pass
    
    merchant_lower = merchant.lower()
    
    # 수입 관련
    if amount >= 0:
        if any(x in merchant_lower for x in ['급여', 'salary', '월급', '입금']):
            return '급여'
        if any(x in merchant_lower for x in ['캐시백', '포인트', '이자', '환급']):
            return '기타수입'
        return '기타수입'
    
    # 지출 카테고리 분류
    merchant_kr = merchant  # 한글 검색용
    
    # 1. 식비 (마트, 편의점, 음식점, 카페)
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('식비', [])):
        return '식비'
    
    # 2. 교통
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('교통', [])):
        return '교통'
    
    # 3. 통신 (아파트 관리비 포함)
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('통신', [])):
        return '통신'
    
    # 4. 구독
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('구독', [])):
        return '구독'
    
    # 5. 쇼핑
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('쇼핑', [])):
        return '쇼핑'
    
    # 6. 투자 (증권사 입금, ISA 등 - 대형 이체만)
    # 네이버파이낸셜 50만원 이상 = 투자용 이체 (ISA, 증권계좌)
    if '네이버파이낸셜' in merchant_kr and amount <= -500000:
        return '투자'
    
    # 다른 증권사 직접 입금도 투자로 분류
    if any(kw in merchant_kr for kw in [
        '증권', '한국투자', '삼성증권', '키움증권', '미래에셋',
        'NH투자증권', '신한투자증권', 'KB증권', 'ISA'
    ]) and amount <= -100000:  # 10만원 이상
        return '투자'
    
    # 7. 이체 (일반 계좌이체, 소액 증권 이체 등)
    if any(kw in merchant_kr for kw in CATEGORY_KEYWORDS.get('이체', [])) and not any(x in merchant_kr for x in ['카드', '할부', '결제']):
        return '이체'
    
    # 개인 이름처럼 보이는 경우 (한글 2-4자, 숫자/영문 없음)
    merchant_clean = merchant_kr.replace(' ', '').replace('　', '')
    if (len(merchant_clean) >= 2 and len(merchant_clean) <= 4 and 
        all('\uac00' <= c <= '\ud7a3' for c in merchant_clean)):  # 모두 한글인 경우
        return '이체'
    
    # 7. 기타 (분류 불가)
    return '기타'


def generate_hash(date: datetime, merchant: str, amount: float, method: str) -> str:
    """거래 고유 해시 생성 (중복 체크용)"""
    key = f"{date.isoformat()}|{merchant}|{amount}|{method}"
    return hashlib.md5(key.encode('utf-8')).hexdigest()


def build_dedup_key(date: datetime, merchant: str, amount: float, method: str) -> str:
    """DB에 이미 있는 거래 중복 체크용 키"""
    if isinstance(date, datetime):
        date_key = date.date().isoformat()
    else:
        date_key = date.isoformat()
    return f"{date_key}|{merchant}|{amount}|{method}"


def build_core_key(date: datetime, merchant: str, method: str) -> str:
    """금액을 제외한 중복 체크용 키 (일자/가맹점/결제수단)"""
    if isinstance(date, datetime):
        date_key = date.date().isoformat()
    else:
        date_key = date.isoformat()
    return f"{date_key}|{merchant}|{method}"


def build_methodless_key(date: datetime, merchant: str, amount: float) -> str:
    """결제수단을 제외한 중복 체크용 키 (일자/가맹점/금액)"""
    if isinstance(date, datetime):
        date_key = date.date().isoformat()
    else:
        date_key = date.isoformat()
    return f"{date_key}|{merchant}|{amount}"


def build_abs_dedup_key(date: datetime, merchant: str, amount: float, method: str) -> str:
    """카드 사용 내역 등 부호 차이를 보정한 중복 체크용 키"""
    return build_dedup_key(date, merchant, abs(amount), method)


def parse_excel_or_csv(file_path: Path) -> pd.DataFrame:
    """
    Excel 또는 CSV 파일을 읽어서 표준 형식으로 변환
    
    필수 컬럼:
    - date (거래일): YYYY-MM-DD 또는 YYYYMMDD
    - merchant (가맹점): 상점명
    - amount (금액): 숫자 (음수: 지출, 양수: 수입)
    - method (결제수단): 카드명 또는 계좌명
    
    Returns:
        표준화된 DataFrame
    """
    if file_path.suffix in ['.xlsx', '.xls']:
        df = pd.read_excel(file_path)
    elif file_path.suffix == '.csv':
        # CSV 인코딩 자동 감지
        try:
            df = pd.read_csv(file_path, encoding='utf-8')
        except UnicodeDecodeError:
            df = pd.read_csv(file_path, encoding='cp949')
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {file_path.suffix}")
    
    def normalize_col(col: str) -> str:
        return re.sub(r"\s+", "", str(col).strip().lower())

    # 컬럼명 정규화 (대소문자, 공백 제거)
    df.columns = [normalize_col(c) for c in df.columns]
    
    # 컬럼 매핑 (다양한 형식 지원)
    column_mapping = {
        # 날짜
        'date': [
            'date', '일자', '거래일', '거래일자', '날짜', '승인일자', '이용일', '거래일시',
        ],
        # 시간
        'time': ['time', '이용시간', '거래시각'],
        # 가맹점
        'merchant': [
            'merchant', '가맹점', '가맹점명', '상호', '적요', '내역', '거래처', '사용처',
            '이용가맹점(은행)명', '이용하신곳',
        ],
        # 금액
        'amount': [
            'amount', '금액', '거래금액', '이용금액', '승인금액', '출금', '입금',
            '이용금액(원)', '국내이용금액(원)', '해외이용금액($)', '출금액', '입금액',
        ],
        # 입금/출금 분리형
        'withdrawal': ['withdrawal', '출금', '출금액'],
        'deposit': ['deposit', '입금', '입금액'],
        # 결제수단
        'method': ['method', '결제수단', '카드', '카드명', '계좌', '은행', '수단', '이용카드', '이용카드명'],
    }

    # report.xls 계열 카드내역 전용 파서
    if file_path.suffix == '.xls' and file_path.stem.startswith('report'):
        df_raw = pd.read_excel(file_path, header=None)
        df_report = pd.read_excel(file_path, header=1)
        df_report.columns = [normalize_col(c) for c in df_report.columns]
        mapped_df = pd.DataFrame()
        col_map = {normalize_col(c): c for c in df_report.columns}
        for standard_col, possible_names in column_mapping.items():
            for col_name in possible_names:
                normalized_name = normalize_col(col_name)
                if normalized_name in col_map:
                    mapped_df[standard_col] = df_report[col_map[normalized_name]]
                    break
        required = ['date', 'merchant', 'amount']
        missing = [col for col in required if col not in mapped_df.columns]
        if missing:
            raise ValueError(f"필수 컬럼이 없습니다: {missing}\n현재 컬럼: {list(df_report.columns)}")
        if 'method' not in mapped_df.columns:
            mapped_df['method'] = file_path.stem
        raw_dates = mapped_df['date'].astype(str)
        header_text = " ".join(df_raw.astype(str).head(5).fillna("").values.flatten())
        year_match = re.search(r"(20\\d{2})\\.\\d{2}\\.\\d{2}", header_text)
        if year_match:
            year = year_match.group(1)
            date_str = year + "." + raw_dates
            mapped_df['date'] = pd.to_datetime(date_str, format="%Y.%m.%d %H:%M:%S", errors='coerce')
        mapped_df['amount'] = mapped_df['amount'].astype(str).str.replace(',', '').str.replace(' ', '')
        mapped_df['amount'] = pd.to_numeric(mapped_df['amount'], errors='coerce')
        mapped_df['amount'] = -mapped_df['amount'].abs()
        mapped_df['merchant'] = mapped_df['merchant'].astype('string').str.strip()
        mapped_df.loc[mapped_df['merchant'] == '', 'merchant'] = pd.NA
        invalid_date_count = mapped_df['date'].isna().sum()
        invalid_amount_count = mapped_df['amount'].isna().sum()
        invalid_merchant_count = mapped_df['merchant'].isna().sum()
        before_drop = len(mapped_df)
        mapped_df = mapped_df.dropna(subset=['date', 'merchant', 'amount'])
        dropped = before_drop - len(mapped_df)
        if dropped:
            print(
                f"⚠️ 유효하지 않은 {dropped}행을 제외했습니다. "
                f"(날짜 {invalid_date_count} / 금액 {invalid_amount_count} / 가맹점 {invalid_merchant_count})"
            )
        if mapped_df.empty:
            raise ValueError("유효한 거래를 찾지 못했습니다. 날짜/금액/가맹점 컬럼을 확인해주세요.")
        return mapped_df
    
    # 컬럼 자동 매핑
    mapped_df = pd.DataFrame()
    mapped_from = {}
    col_map = {normalize_col(c): c for c in df.columns}
    for standard_col, possible_names in column_mapping.items():
        for col_name in possible_names:
            normalized_name = normalize_col(col_name)
            if normalized_name in col_map:
                original_col = col_map[normalized_name]
                mapped_df[standard_col] = df[original_col]
                mapped_from[standard_col] = normalized_name
                break

    header_text_source = df

    # 헤더가 위에 있는 특수 엑셀 형식 대응
    if 'date' not in mapped_df.columns or 'merchant' not in mapped_df.columns or 'amount' not in mapped_df.columns:
        df_raw = pd.read_excel(file_path, header=None) if file_path.suffix in ['.xlsx', '.xls'] else df
        header_text_source = df_raw
        header_row = None
        header_candidates = {normalize_col(n) for names in column_mapping.values() for n in names}
        max_scan = min(30, len(df_raw))
        for idx in range(max_scan):
            row_values = df_raw.iloc[idx].astype(str).apply(normalize_col)
            hits = sum(1 for v in row_values if v in header_candidates)
            if hits >= 2:
                header_row = idx
                break
        if header_row is not None:
            df = df_raw.iloc[header_row:].copy()
            df.columns = [normalize_col(c) for c in df.iloc[0]]
            df = df.iloc[1:].reset_index(drop=True)
            mapped_df = pd.DataFrame()
            mapped_from = {}
            col_map = {normalize_col(c): c for c in df.columns}
            for standard_col, possible_names in column_mapping.items():
                for col_name in possible_names:
                    normalized_name = normalize_col(col_name)
                    if normalized_name in col_map:
                        original_col = col_map[normalized_name]
                        mapped_df[standard_col] = df[original_col]
                        mapped_from[standard_col] = normalized_name
                        break
    
    # 필수 컬럼 확인
    # 입금/출금 분리형이면 amount 생성
    if 'withdrawal' in mapped_df.columns and 'deposit' in mapped_df.columns:
        mapped_df['withdrawal'] = pd.to_numeric(
            mapped_df['withdrawal'].astype(str).str.replace(',', '').str.replace(' ', ''),
            errors='coerce',
        ).fillna(0)
        mapped_df['deposit'] = pd.to_numeric(
            mapped_df['deposit'].astype(str).str.replace(',', '').str.replace(' ', ''),
            errors='coerce',
        ).fillna(0)
        mapped_df['amount'] = mapped_df['deposit'] - mapped_df['withdrawal']
        mapped_from['amount'] = 'deposit-withdrawal'

    # 날짜 + 시간 컬럼 결합
    if 'date' in mapped_df.columns and 'time' in mapped_df.columns:
        mapped_df['date'] = mapped_df['date'].astype(str).str.strip() + " " + mapped_df['time'].astype(str).str.strip()

    required = ['date', 'merchant', 'amount']
    missing = [col for col in required if col not in mapped_df.columns]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {missing}\n현재 컬럼: {list(df.columns)}")
    
    # method가 없으면 파일명에서 추출
    if 'method' not in mapped_df.columns:
        mapped_df['method'] = file_path.stem  # 파일명을 결제수단으로 사용
    
    # 날짜 형식 변환
    raw_dates = mapped_df['date'].astype(str)
    mapped_df['date'] = pd.to_datetime(mapped_df['date'], errors='coerce')
    if mapped_df['date'].isna().any():
        sample = raw_dates[raw_dates.notna()].head(1)
        if not sample.empty and re.match(r"^\\d{2}\\.\\d{2}(\\s+\\d{2}:\\d{2}:\\d{2})?$", sample.iloc[0]):
            header_text = " ".join(header_text_source.astype(str).head(10).fillna("").values.flatten())
            year_match = re.search(r"(20\\d{2})\\.\\d{2}\\.\\d{2}", header_text)
            if year_match:
                year = year_match.group(1)
                date_str = year + "." + raw_dates
                fmt = "%Y.%m.%d %H:%M:%S" if " " in sample.iloc[0] else "%Y.%m.%d"
                mapped_df['date'] = pd.to_datetime(date_str, format=fmt, errors='coerce')
    
    # 금액 형식 변환 (쉼표 제거)
    mapped_df['amount'] = mapped_df['amount'].astype(str).str.replace(',', '').str.replace(' ', '')
    mapped_df['amount'] = pd.to_numeric(mapped_df['amount'], errors='coerce').astype(float)

    # 해외 사용 내역: 국내 금액이 0이면 해외 금액으로 보정
    overseas_col = None
    for col_name in [normalize_col('해외이용금액($)')]:
        if col_name in col_map:
            overseas_col = col_map[col_name]
            break
    if overseas_col:
        overseas_amount = df[overseas_col].astype(str).str.replace(',', '').str.replace(' ', '')
        overseas_amount = pd.to_numeric(overseas_amount, errors='coerce')
        mask = (mapped_df['amount'].isna() | (mapped_df['amount'] == 0)) & overseas_amount.notna() & (overseas_amount != 0)
        if mask.any():
            mapped_df.loc[mask, 'amount'] = overseas_amount[mask]

    # 카드 이용내역은 지출로 음수 처리
    normalized_cols = set(df.columns)
    if (
        any(x in normalized_cols for x in ['이용금액(원)', '국내이용금액(원)', '이용하신곳', '이용가맹점(은행)명'])
        or '카드' in file_path.stem
    ) and 'deposit' not in mapped_df.columns:
        mapped_df['amount'] = -mapped_df['amount'].abs()
    
    mapped_df['merchant'] = mapped_df['merchant'].astype('string').str.strip()
    mapped_df.loc[mapped_df['merchant'] == '', 'merchant'] = pd.NA
    invalid_date_count = mapped_df['date'].isna().sum()
    invalid_amount_count = mapped_df['amount'].isna().sum()
    invalid_merchant_count = mapped_df['merchant'].isna().sum()
    before_drop = len(mapped_df)
    mapped_df = mapped_df.dropna(subset=['date', 'merchant', 'amount'])
    dropped = before_drop - len(mapped_df)
    if dropped:
        print(
            f"⚠️ 유효하지 않은 {dropped}행을 제외했습니다. "
            f"(날짜 {invalid_date_count} / 금액 {invalid_amount_count} / 가맹점 {invalid_merchant_count})"
        )

    # report.xls 계열 카드내역 특수 포맷 보정
    if mapped_df.empty and file_path.suffix == '.xls' and file_path.stem.startswith('report'):
        df_raw = pd.read_excel(file_path, header=None)
        df = pd.read_excel(file_path, header=1)
        df.columns = [normalize_col(c) for c in df.columns]
        mapped_df = pd.DataFrame()
        col_map = {normalize_col(c): c for c in df.columns}
        for standard_col, possible_names in column_mapping.items():
            for col_name in possible_names:
                normalized_name = normalize_col(col_name)
                if normalized_name in col_map:
                    mapped_df[standard_col] = df[col_map[normalized_name]]
                    break
        required = ['date', 'merchant', 'amount']
        missing = [col for col in required if col not in mapped_df.columns]
        if missing:
            raise ValueError(f"필수 컬럼이 없습니다: {missing}\n현재 컬럼: {list(df.columns)}")

        raw_dates = mapped_df['date'].astype(str)
        header_text = " ".join(df_raw.astype(str).head(5).fillna("").values.flatten())
        year_match = re.search(r"(20\\d{2})\\.\\d{2}\\.\\d{2}", header_text)
        if year_match:
            year = year_match.group(1)
            date_str = year + "." + raw_dates
            mapped_df['date'] = pd.to_datetime(date_str, format="%Y.%m.%d %H:%M:%S", errors='coerce')
        mapped_df['amount'] = mapped_df['amount'].astype(str).str.replace(',', '').str.replace(' ', '')
        mapped_df['amount'] = pd.to_numeric(mapped_df['amount'], errors='coerce')
        mapped_df['amount'] = -mapped_df['amount'].abs()
        if 'method' not in mapped_df.columns:
            mapped_df['method'] = file_path.stem
        mapped_df['merchant'] = mapped_df['merchant'].astype('string').str.strip()
        mapped_df.loc[mapped_df['merchant'] == '', 'merchant'] = pd.NA
        invalid_date_count = mapped_df['date'].isna().sum()
        invalid_amount_count = mapped_df['amount'].isna().sum()
        invalid_merchant_count = mapped_df['merchant'].isna().sum()
        before_drop = len(mapped_df)
        mapped_df = mapped_df.dropna(subset=['date', 'merchant', 'amount'])
        dropped = before_drop - len(mapped_df)
        if dropped:
            print(
                f"⚠️ 유효하지 않은 {dropped}행을 제외했습니다. "
                f"(날짜 {invalid_date_count} / 금액 {invalid_amount_count} / 가맹점 {invalid_merchant_count})"
            )

    if mapped_df.empty:
        raise ValueError("유효한 거래를 찾지 못했습니다. 날짜/금액/가맹점 컬럼을 확인해주세요.")
    
    return mapped_df


def import_expenses_from_file(
    db_path: str,
    file_path: Path,
    dry_run: bool = False,
    auto_category: bool = True
) -> Tuple[int, int, int]:
    """
    파일에서 지출 데이터를 읽어서 DB에 임포트
    
    Args:
        db_path: SQLite DB 경로
        file_path: Excel/CSV 파일 경로
        dry_run: True이면 실제 삽입하지 않고 미리보기만
        auto_category: True이면 자동 카테고리 분류
    
    Returns:
        (총 행수, 새로 추가된 행수, 중복 스킵 행수)
    """
    engine = create_engine(f"sqlite:///{db_path}")
    
    # 파일 파싱
    print(f"📄 파일 읽는 중: {file_path}")
    df = parse_excel_or_csv(file_path)
    print(f"✅ {len(df)}개 거래 발견")
    
    # 미리보기
    if len(df) > 0:
        print("\n📋 데이터 미리보기 (처음 5개):")
        print(df.head().to_string(index=False))
        print()
    
    added_count = 0
    skipped_count = 0
    updated_count = 0
    
    report_year = None
    if file_path.suffix == '.xls' and file_path.stem.startswith('report'):
        try:
            header_text = " ".join(
                pd.read_excel(file_path, header=None).astype(str).head(5).fillna("").values.flatten()
            )
            year_match = re.search(r"(20\\d{2})\\.\\d{2}\\.\\d{2}", header_text)
            if year_match:
                report_year = int(year_match.group(1))
        except Exception:
            report_year = None

    with Session(engine) as session:
        # 사용자 확인
        user = get_or_create_single_user(session)
        
        # AI 모델 로드
        model = None
        model_path = REPO_ROOT / "backend" / "expense_model.joblib"
        if model_path.exists():
            try:
                model = joblib.load(model_path)
            except Exception as e:
                print(f"⚠️ 모델 로드 실패: {e}")

        # DB에서 학습된 패턴 가져오기
        learned_patterns = {}
        pattern_stmt = select(MerchantPattern.merchant, MerchantPattern.category).where(MerchantPattern.user_id == user.id)
        for m, c in session.execute(pattern_stmt):
            learned_patterns[m] = c
        # 기존 해시 조회 (중복 체크용)
        # memo 필드에 해시 저장한다고 가정 (또는 별도 컬럼 추가 가능)
        existing_hashes = set()
        stmt = select(Expense.memo).where(Expense.user_id == user.id, Expense.memo.like('HASH:%'))
        for (memo,) in session.execute(stmt):
            if memo and memo.startswith('HASH:'):
                existing_hashes.add(memo.split('HASH:')[1])

        # 해시 없이 들어온 기존 데이터도 중복으로 감지
        existing_keys = set()
        existing_abs = {}
        existing_core = {}
        existing_methodless = {}
        stmt = select(Expense.id, Expense.date, Expense.merchant, Expense.amount, Expense.method).where(
            Expense.user_id == user.id
        )
        for exp_id, exp_date, exp_merchant, exp_amount, exp_method in session.execute(stmt):
            if exp_date and exp_merchant is not None and exp_amount is not None:
                existing_keys.add(
                    build_dedup_key(exp_date, str(exp_merchant), float(exp_amount), str(exp_method or ""))
                )
                existing_abs[build_abs_dedup_key(
                    exp_date, str(exp_merchant), float(exp_amount), str(exp_method or "")
                )] = (exp_id, float(exp_amount))
                core_key = build_core_key(exp_date, str(exp_merchant), str(exp_method or ""))
                existing_core.setdefault(core_key, []).append((exp_id, float(exp_amount)))
                methodless_key = build_methodless_key(exp_date, str(exp_merchant), float(exp_amount))
                existing_methodless.setdefault(methodless_key, []).append((exp_id, str(exp_method or "")))
        
        for idx, row in df.iterrows():
            raw_date = row['date']
            if isinstance(raw_date, str):
                date_str = raw_date.strip()
                if report_year and re.match(r"^\\d{2}\\.\\d{2}(\\s+\\d{2}:\\d{2}:\\d{2})?$", date_str):
                    date_str = f"{report_year}.{date_str}"
                    parsed = pd.to_datetime(date_str, format="%Y.%m.%d %H:%M:%S", errors='coerce')
                else:
                    parsed = pd.to_datetime(date_str, errors='coerce')
                if pd.isna(parsed):
                    continue
                date = parsed.to_pydatetime()
            else:
                if hasattr(raw_date, "to_pydatetime"):
                    date = raw_date.to_pydatetime()
                else:
                    date = raw_date
            merchant = str(row['merchant']).strip()
            amount = float(row['amount'])
            method = str(row['method']).strip() if pd.notna(row.get('method')) else ''

            # 카테고리 자동 분류
            if auto_category:
                category = classify_category(merchant, amount, learned_patterns=learned_patterns, model=model)
            else:
                category = '기타'
            
            # 해시 생성
            tx_hash = generate_hash(date, merchant, amount, method)
            dedup_key = build_dedup_key(date, merchant, amount, method)
            core_key = build_core_key(date, merchant, method)
            methodless_key = build_methodless_key(date, merchant, amount)

            # 금액이 0으로 들어간 기존 거래가 있으면 동일 키 기준으로 보정
            core_entries = existing_core.get(core_key)
            if amount != 0 and core_entries and len(core_entries) == 1 and core_entries[0][1] == 0:
                updated_count += 1
                if not dry_run:
                    exp_id = core_entries[0][0]
                    session.query(Expense).filter(Expense.id == exp_id).update({"amount": amount})
                existing_keys.add(dedup_key)
                existing_hashes.add(tx_hash)
                existing_core[core_key] = [(core_entries[0][0], amount)]
                continue
            
            # 카드 내역: 부호만 다른 기존 데이터가 있으면 수정
            abs_key = build_abs_dedup_key(date, merchant, amount, method)
            if abs_key in existing_abs and abs(amount) == abs(existing_abs[abs_key][1]) and amount != existing_abs[abs_key][1]:
                updated_count += 1
                if not dry_run:
                    exp_id = existing_abs[abs_key][0]
                    session.query(Expense).filter(Expense.id == exp_id).update(
                        {"amount": amount, "category": category}
                    )
                existing_keys.add(dedup_key)
                existing_hashes.add(tx_hash)
                continue

            # 결제수단이 일반값일 때는 동일 일자/가맹점/금액의 상세 내역을 우선시
            methodless_entries = existing_methodless.get(methodless_key)
            if methodless_entries:
                has_non_generic = any(not is_generic_method(m) for _, m in methodless_entries if m)
                if is_generic_method(method) and has_non_generic:
                    skipped_count += 1
                    continue
                if not is_generic_method(method) and not has_non_generic:
                    updated_count += 1
                    exp_id, old_method = methodless_entries[0]
                    if not dry_run:
                        session.query(Expense).filter(Expense.id == exp_id).update(
                            {"method": method, "category": category}
                        )
                    old_dedup = build_dedup_key(date, merchant, amount, old_method)
                    old_hash = generate_hash(date, merchant, amount, old_method)
                    old_abs_key = build_abs_dedup_key(date, merchant, amount, old_method)
                    old_core_key = build_core_key(date, merchant, old_method)
                    existing_keys.discard(old_dedup)
                    existing_hashes.discard(old_hash)
                    existing_abs.pop(old_abs_key, None)
                    if old_core_key in existing_core:
                        existing_core[old_core_key] = [
                            entry for entry in existing_core[old_core_key] if entry[0] != exp_id
                        ]
                        if not existing_core[old_core_key]:
                            existing_core.pop(old_core_key, None)
                    existing_keys.add(dedup_key)
                    existing_hashes.add(tx_hash)
                    existing_abs[build_abs_dedup_key(date, merchant, amount, method)] = (exp_id, amount)
                    existing_core.setdefault(core_key, []).append((exp_id, amount))
                    existing_methodless[methodless_key] = [(exp_id, method)]
                    continue

            # 중복 체크
            if tx_hash in existing_hashes or dedup_key in existing_keys:
                skipped_count += 1
                continue
            
            # Expense 생성
            expense = Expense(
                user_id=user.id,
                date=date,
                amount=amount,
                category=category,
                merchant=merchant,
                method=method,
                is_fixed=False,
                memo=f'HASH:{tx_hash}'
            )
            
            if not dry_run:
                session.add(expense)
                session.flush()
                existing_hashes.add(tx_hash)
                existing_keys.add(dedup_key)
                existing_methodless.setdefault(methodless_key, []).append((expense.id, method))
            
            added_count += 1
        
        if not dry_run:
            session.commit()
            print(f"✅ DB에 저장 완료")
        else:
            print(f"🔍 DRY RUN - 실제 저장하지 않음")

    if updated_count:
        print(f"🔧 기존 거래 수정 {updated_count}개")

    return len(df), added_count, skipped_count


def main():
    parser = argparse.ArgumentParser(
        description='카드사/통장 거래내역을 DB에 자동 임포트',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 단일 파일 임포트
  python scripts/expenses/import_expenses.py 우리카드_2025.xlsx
  
  # 여러 파일 한번에 임포트
  python scripts/expenses/import_expenses.py 신한카드_2025.xlsx 국민은행_2025.csv
  
  # 미리보기 (실제 저장 안 함)
  python scripts/expenses/import_expenses.py --dry-run 현대카드_2025.xlsx
  
  # 자동 카테고리 분류 비활성화
  python scripts/expenses/import_expenses.py --no-auto-category 토스뱅크_2025.xlsx
        """
    )
    parser.add_argument('files', nargs='+', help='Excel 또는 CSV 파일 경로')
    parser.add_argument(
        '--db',
        default=str(REPO_ROOT / "backend" / "portfolio.db"),
        help='SQLite DB 경로 (기본: backend/portfolio.db)',
    )
    parser.add_argument('--dry-run', action='store_true', help='미리보기만 (실제 저장 안 함)')
    parser.add_argument('--no-auto-category', action='store_true', help='자동 카테고리 분류 비활성화')
    
    args = parser.parse_args()
    
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ DB 파일을 찾을 수 없습니다: {db_path}")
        sys.exit(1)
    
    total_files = len(args.files)
    total_rows = 0
    total_added = 0
    total_skipped = 0
    
    print(f"🚀 거래내역 임포트 시작 ({total_files}개 파일)\n")
    
    for file_path_str in args.files:
        file_path = Path(file_path_str)
        
        if not file_path.exists():
            print(f"⚠️  파일을 찾을 수 없습니다: {file_path}")
            continue
        
        try:
            rows, added, skipped = import_expenses_from_file(
                db_path=str(db_path),
                file_path=file_path,
                dry_run=args.dry_run,
                auto_category=not args.no_auto_category
            )
            
            total_rows += rows
            total_added += added
            total_skipped += skipped
            
            print(f"  • 총 {rows}개 | ✅ 추가 {added}개 | ⏭️  중복 {skipped}개\n")
            
        except Exception as e:
            print(f"❌ 오류 발생: {e}\n")
            import traceback
            traceback.print_exc()
    
    print("=" * 60)
    print(f"📊 전체 요약")
    print(f"  • 처리한 파일: {total_files}개")
    print(f"  • 총 거래: {total_rows}개")
    print(f"  • ✅ 새로 추가: {total_added}개")
    print(f"  • ⏭️  중복 스킵: {total_skipped}개")
    print("=" * 60)
    
    if args.dry_run:
        print("\n💡 실제로 저장하려면 --dry-run 옵션을 제거하고 다시 실행하세요.")


if __name__ == "__main__":
    main()
