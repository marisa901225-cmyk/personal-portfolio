import sys
from pathlib import Path
from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import Session

# 프로젝트 루트 설정
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.models import Expense

# 삭제 대상 키워드 (통장에서 나가는 카드 대금 등)
SKIP_KEYWORDS = [
    '체크우리', '우리카드결제', '우리카드_펌뱅킹', '우리카드-오픈뱅킹',
    '신한카드', '삼성카드', '국민카드', '현대카드', '롯데카드', 'BC카드',
    '네이버파이낸셜', '이창후'
]

# 현금 결제(소액현금결제) 간주 키워드
CASH_PAY_KEYWORDS = ['네이버파이낸셜', '이창후', '네이버페이']

def cleanup_duplicates(db_path: str, dry_run: bool = True):
    engine = create_engine(f"sqlite:///{db_path}")
    
    with Session(engine) as session:
        print(f"🔍 중복 데이터 논리적 분석 중... (Dry Run: {dry_run})")
        
        # 1. 모든 지출 데이터 가져오기 (삭제되지 않은 건들)
        stmt = select(Expense).where(Expense.deleted_at == None)
        all_expenses = session.execute(stmt).scalars().all()
        
        # (date, amount) -> list of Expense
        buckets = {}
        for exp in all_expenses:
            # 보람상조는 분석 대상에서 아예 제외 (절대 건드리지 않음)
            if '보람상조' in exp.merchant:
                continue
            
            key = (exp.date, exp.amount)
            buckets.setdefault(key, []).append(exp)
        
        # 2. 삭제 대상 식별 (날짜가 정확히 일치하지 않아도 금액이 같거나 사용자가 명시한 카드사 건들)
        to_delete_ids = []
        
        # 사용자가 명시적으로 언급한 건들 (날짜, 금액 기반)
        target_patterns = [
            ('2026-01-06', -506340.0), # 신한카드
            ('2026-01-07', -231429.0), # 네이버파이낸셜
            ('2026-01-02', -204708.0), # 네이버파이낸셜
            ('2026-01-06', -63600.0),  # 우리카드결제
            ('2026-01-12', -19000.0),  # 체크우리
        ]

        for exp in all_expenses:
            # 패턴 매칭 (사용자가 언급한 특정 건들)
            for t_date, t_amt in target_patterns:
                if str(exp.date) == t_date and abs(exp.amount - t_amt) < 1.0:
                    if any(kw in exp.merchant for kw in SKIP_KEYWORDS):
                        # 보람상조 금액과 겹치더라도 가맹점명에 카드사 키워드가 있으면 삭제
                        print(f"   🎯 사용자 요청 항목 식별: {exp.date} | {exp.merchant} ({exp.amount}원, ID: {exp.id})")
                        to_delete_ids.append(exp.id)
                        break

        # 단순 중복 (완전 동일 날짜/금액/가맹점) 처리
        buckets = {}
        for exp in all_expenses:
            if exp.id in to_delete_ids: continue
            
            # 같은 날짜/금액의 건들을 모음
            key = (exp.date, exp.amount)
            buckets.setdefault(key, []).append(exp)
        
        for key, items in buckets.items():
            if len(items) > 1:
                # 보람상조 거래들만 추림
                boram_items = [i for i in items if '보람상조' in i.merchant]
                # 카드 대금 거래들만 추림
                debt_items = [i for i in items if any(kw in i.merchant for kw in SKIP_KEYWORDS)]
                
                # 규칙 1: 보람상조는 가맹점명이 같을 때 2건까지 허용
                if boram_items:
                    # 가맹점명별로 그룹화
                    boram_by_name = {}
                    for b in boram_items:
                        boram_by_name.setdefault(b.merchant, []).append(b)
                    
                    for name, b_list in boram_by_name.items():
                        if len(b_list) > 2:
                            b_list.sort(key=lambda x: x.created_at)
                            for b in b_list[2:]:
                                print(f"   ❌ 보람상조 단순 중복(3건이상) 삭제: {b.merchant} (ID: {b.id})")
                                to_delete_ids.append(b.id)

                # 규칙 2: 보람상조와 겹치는 카드 대금 항목(체크우리 등)은 무조건 한쪽(카드대금)을 삭제
                if boram_items and debt_items:
                    for d in debt_items:
                        print(f"   ❌ 보람상조와 겹치는 카드 대금 삭제: {d.merchant} (ID: {d.id})")
                        to_delete_ids.append(d.id)
                
                # 규칙 3: 일반적인 단순 중복 (완전 동일 정보)
                # (보람상조/카드대금 제외한 나머지 중복 처리)
                remaining = [i for i in items if i.id not in to_delete_ids and i not in boram_items]
                if len(remaining) > 1:
                    # 가맹점명까지 같으면 단순 중복
                    rem_by_name = {}
                    for r in remaining:
                        rem_by_name.setdefault(r.merchant, []).append(r)
                    for name, r_list in rem_by_name.items():
                        if len(r_list) > 1:
                            r_list.sort(key=lambda x: x.created_at)
                            for r in r_list[1:]:
                                print(f"   ❌ 일반 단순 중복 삭제: {r.merchant} (ID: {r.id})")
                                to_delete_ids.append(r.id)

        if not to_delete_ids:
            print("✅ 정리할 중복 데이터가 발견되지 않았습니다. (패턴 확인 필요)")
            return

        print(f"\n총 {len(to_delete_ids)}건의 중복 데이터를 정리합니다.")
        
        if not dry_run:
            stmt_del = delete(Expense).where(Expense.id.in_(to_delete_ids))
            session.execute(stmt_del)
            session.commit()
            print("🚀 정리 완료!")
        else:
            print("🔍 DRY RUN 완료 (실제 삭제되지 않음. --apply 인자를 주어 실행하세요.)")

if __name__ == "__main__":
    db_path = REPO_ROOT / "backend" / "storage" / "db" / "portfolio.db"
    dry_run = "--apply" not in sys.argv
    cleanup_duplicates(str(db_path), dry_run=dry_run)
