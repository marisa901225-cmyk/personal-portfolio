"""DB 임포트 로직"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

import pandas as pd
import joblib
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

# 프로젝트 루트 설정 (Docker: /app, 로컬: repo root)
# backend/scripts/expenses/importer.py 기준으로 3단계 상위가 /app
REPO_ROOT = Path(__file__).resolve().parents[3]

import sys
sys.path.insert(0, str(REPO_ROOT))

from backend.core.models import Expense, MerchantPattern
from backend.services.users import get_or_create_single_user

from .parsers import (
    parse_excel_or_csv,
    parse_naver_pay_text,
    generate_hash,
    build_dedup_key,
    build_core_key,
    build_methodless_key,
    build_abs_dedup_key,
    is_generic_method,
)
from .category import classify_category


def parse_file(file_path: Path) -> pd.DataFrame:
    """
    파일 확장자에 따라 적절한 파서 선택
    
    - .txt: 네이버페이 결제내역
    - .xlsx, .xls, .csv: 카드/통장 내역
    """
    if file_path.suffix.lower() == '.txt':
        return parse_naver_pay_text(file_path)
    return parse_excel_or_csv(file_path)


# 중복으로 건너뛸 가맹점 패턴
SKIP_MERCHANT_PATTERNS = {
    'check_card': lambda m: m.startswith('체크'),
    'naver_financial': lambda m: '네이버파이낸셜' in m,
}

CARD_PAYMENT_KEYWORDS = [
    '신한카드', '우리카드결제', '삼성카드', '국민카드', 
    '현대카드', '롯데카드', 'BC카드'
]


def should_skip_merchant(merchant: str, amount: float, is_naverpay_file: bool) -> bool:
    """통장 내역에서 중복될 수 있는 항목 필터링"""
    if is_naverpay_file:
        return False
    
    if amount >= 0:
        return False
    
    # 체크카드 통장 출금건
    if merchant.startswith('체크'):
        return True
    
    # 네이버파이낸셜 통장 출금건
    if '네이버파이낸셜' in merchant:
        return True
    
    # 카드 결제 대금 통장 출금건
    if any(kw in merchant for kw in CARD_PAYMENT_KEYWORDS):
        return True
    
    return False


def import_expenses_from_file(
    db_path: str,
    file_path: Path,
    dry_run: bool = False,
    auto_category: bool = True
) -> Tuple[int, int, int, dict[str, int]]:
    """
    파일에서 지출 데이터를 읽어서 DB에 임포트
    
    Args:
        db_path: SQLite DB 경로
        file_path: Excel/CSV/TXT 파일 경로
        dry_run: True이면 실제 삽입하지 않고 미리보기만
        auto_category: True이면 자동 카테고리 분류
    
    Returns:
        (총 행수, 새로 추가된 행수, 중복 스킵 행수, 스킵 사유 카운트)
    """
    engine = create_engine(f"sqlite:///{db_path}")
    
    # 파일 파싱
    print(f"📄 파일 읽는 중: {file_path}")
    df = parse_file(file_path)
    
    if df.empty:
        print("⚠️ 데이터가 없습니다.")
        return 0, 0, 0
    
    print(f"✅ {len(df)}개 거래 발견")
    
    # 미리보기
    if len(df) > 0:
        print("\n📋 데이터 미리보기 (처음 5개):")
        print(df.head().to_string(index=False))
        print()
    
    added_count = 0
    skipped_count = 0
    updated_count = 0
    skip_breakdown = {
        "skip_merchant": 0,
        "skip_generic_method": 0,
        "duplicate": 0,
    }
    is_naverpay_file = file_path.suffix.lower() == '.txt'

    with Session(engine) as session:
        # 사용자 확인
        user = get_or_create_single_user(session)
        
        # AI 모델 로드
        model = None
        model_path = REPO_ROOT / "backend" / "data" / "expense_model.joblib"
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
        existing_hashes = set()
        stmt = select(Expense.memo).where(Expense.user_id == user.id, Expense.memo.like('HASH:%'))
        for (memo,) in session.execute(stmt):
            if memo and memo.startswith('HASH:'):
                existing_hashes.add(memo.split('HASH:')[1])

        # 기존 데이터 중복 체크용 키 구축
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

        # [NEW] 복구 데이터 매칭용맵 (merchant, amount) -> list of exp_id
        # 오늘 날짜(2026-01-14) 부근이거나 [복구] 메모가 있는 건들
        recovery_candidates = {}
        stmt_recovery = select(Expense.id, Expense.merchant, Expense.amount).where(
            Expense.user_id == user.id,
            Expense.memo.like('[복구]%')
        )
        for r_id, r_mer, r_amt in session.execute(stmt_recovery):
            key = (str(r_mer).strip(), float(r_amt))
            recovery_candidates.setdefault(key, []).append(r_id)
        
        for idx, row in df.iterrows():
            # 날짜 파싱
            raw_date = row['date']
            if hasattr(raw_date, "to_pydatetime"):
                date = raw_date.to_pydatetime()
            elif isinstance(raw_date, str):
                parsed = pd.to_datetime(raw_date.strip(), errors='coerce')
                if pd.isna(parsed):
                    continue
                date = parsed.to_pydatetime()
            else:
                date = raw_date
            
            merchant = str(row['merchant']).strip()
            amount = float(row['amount'])
            method = str(row['method']).strip() if pd.notna(row.get('method')) else ''

            # 중복 가능 항목 건너뛰기
            if should_skip_merchant(merchant, amount, is_naverpay_file):
                skipped_count += 1
                skip_breakdown["skip_merchant"] += 1
                continue

            # 카테고리 자동 분류
            if auto_category:
                category = classify_category(merchant, amount, learned_patterns=learned_patterns, model=model)
            else:
                category = '기타'
            
            # 해시 및 중복 키 생성
            tx_hash = generate_hash(date, merchant, amount, method)
            dedup_key = build_dedup_key(date, merchant, amount, method)
            core_key = build_core_key(date, merchant, method)
            methodless_key = build_methodless_key(date, merchant, amount)

            # 금액이 0으로 들어간 기존 거래 보정
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
            
            # 부호만 다른 기존 데이터 수정
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

            # 결제수단 우선순위 처리
            methodless_entries = existing_methodless.get(methodless_key)
            if methodless_entries:
                has_non_generic = any(not is_generic_method(m) for _, m in methodless_entries if m)
                if is_generic_method(method) and has_non_generic:
                    skipped_count += 1
                    skip_breakdown["skip_generic_method"] += 1
                    continue
                if not is_generic_method(method) and not has_non_generic:
                    updated_count += 1
                    exp_id, old_method = methodless_entries[0]
                    if not dry_run:
                        session.query(Expense).filter(Expense.id == exp_id).update(
                            {"method": method, "category": category}
                        )
                    existing_keys.add(dedup_key)
                    existing_hashes.add(tx_hash)
                    continue

            # 중복 체크
            if tx_hash in existing_hashes or dedup_key in existing_keys:
                skipped_count += 1
                skip_breakdown["duplicate"] += 1
                continue
            
            # [NEW] [복구] 데이터 보정 로직
            # 엑셀 날짜는 정확한데, DB에는 오늘 날짜로 들어간 [복구] 데이터가 있는 경우
            m_a_key = (merchant, amount)
            if m_a_key in recovery_candidates:
                r_ids = recovery_candidates[m_a_key]
                if r_ids:
                    r_id = r_ids.pop(0) # 하나씩 소진
                    updated_count += 1
                    if not dry_run:
                        session.query(Expense).filter(Expense.id == r_id).update({
                            "date": date,
                            "method": method,
                            "memo": f'HASH:{tx_hash}' # 정상 해시로 교체
                        })
                    existing_hashes.add(tx_hash)
                    existing_keys.add(dedup_key)
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

    return len(df), added_count, skipped_count, skip_breakdown
