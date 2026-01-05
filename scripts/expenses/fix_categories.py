#!/usr/bin/env python3
"""
지출 데이터 카테고리 수동 조정 헬퍼 스크립트
잘못 분류된 항목들을 쉽게 찾아서 수정
"""
import argparse
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def find_suspicious_items(db_path: str, category: str = None):
    """의심스러운 분류 항목 찾기"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("🔍 의심스러운 분류 항목 검색\n")
    
    # 1. 투자 카테고리 중 50만원 미만 (너무 작음)
    if not category or category == "투자":
        print("💰 투자 카테고리 중 의심 항목 (50만원 미만):")
        cursor.execute("""
            SELECT id, date, merchant, ABS(amount) as amount, category
            FROM expenses
            WHERE category = '투자' AND amount > -500000
            ORDER BY date DESC
            LIMIT 20
        """)
        
        rows = cursor.fetchall()
        if rows:
            print(f"{'ID':<6} {'날짜':<12} {'가맹점':<30} {'금액':>12} {'카테고리':<10}")
            print("-" * 80)
            for row in rows:
                print(f"{row[0]:<6} {row[1]:<12} {row[2]:<30} ₩{row[3]:>10,.0f} {row[4]:<10}")
        else:
            print("  ✅ 없음")
        print()
    
    # 2. 이체 카테고리 중 50만원 이상 (투자일 가능성)
    if not category or category == "이체":
        print("🏦 이체 카테고리 중 의심 항목 (50만원 이상):")
        cursor.execute("""
            SELECT id, date, merchant, ABS(amount) as amount, category
            FROM expenses
            WHERE category = '이체' AND amount <= -500000
            ORDER BY date DESC
            LIMIT 20
        """)
        
        rows = cursor.fetchall()
        if rows:
            print(f"{'ID':<6} {'날짜':<12} {'가맹점':<30} {'금액':>12} {'카테고리':<10}")
            print("-" * 80)
            for row in rows:
                print(f"{row[0]:<6} {row[1]:<12} {row[2]:<30} ₩{row[3]:>10,.0f} {row[4]:<10}")
        else:
            print("  ✅ 없음")
        print()
    
    # 3. 쇼핑 카테고리 중 증권 관련 키워드
    if not category or category == "쇼핑":
        print("🛒 쇼핑 카테고리 중 의심 항목 (증권/네이버파이낸셜):")
        cursor.execute("""
            SELECT id, date, merchant, ABS(amount) as amount, category
            FROM expenses
            WHERE category = '쇼핑' 
            AND (merchant LIKE '%증권%' OR merchant LIKE '%네이버파이낸셜%')
            ORDER BY date DESC
            LIMIT 20
        """)
        
        rows = cursor.fetchall()
        if rows:
            print(f"{'ID':<6} {'날짜':<12} {'가맹점':<30} {'금액':>12} {'카테고리':<10}")
            print("-" * 80)
            for row in rows:
                print(f"{row[0]:<6} {row[1]:<12} {row[2]:<30} ₩{row[3]:>10,.0f} {row[4]:<10}")
        else:
            print("  ✅ 없음")
        print()
    
    conn.close()


def update_category(db_path: str, expense_id: int, new_category: str):
    """카테고리 수동 변경"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 기존 정보 확인
    cursor.execute("SELECT date, merchant, amount, category FROM expenses WHERE id = ?", (expense_id,))
    row = cursor.fetchone()
    
    if not row:
        print(f"❌ ID {expense_id}를 찾을 수 없습니다.")
        return
    
    date, merchant, amount, old_category = row
    
    print(f"\n📝 카테고리 변경:")
    print(f"  ID: {expense_id}")
    print(f"  날짜: {date}")
    print(f"  가맹점: {merchant}")
    print(f"  금액: ₩{abs(amount):,.0f}")
    print(f"  {old_category} → {new_category}")
    
    # 변경
    cursor.execute("""
        UPDATE expenses 
        SET category = ? 
        WHERE id = ?
    """, (new_category, expense_id))
    
    conn.commit()
    conn.close()
    
    print(f"\n✅ 카테고리 변경 완료!")


def main():
    parser = argparse.ArgumentParser(
        description='지출 카테고리 수동 조정 도구',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 의심스러운 항목 찾기
  python scripts/expenses/fix_categories.py --find
  
  # 특정 카테고리만 검사
  python scripts/expenses/fix_categories.py --find --category 투자
  
  # 카테고리 변경
  python scripts/expenses/fix_categories.py --update 123 --to 쇼핑
        """
    )
    
    parser.add_argument('--db', default=str(REPO_ROOT / 'backend' / 'portfolio.db'), help='DB 경로')
    parser.add_argument('--find', action='store_true', help='의심 항목 찾기')
    parser.add_argument('--category', help='검사할 카테고리 (투자, 이체, 쇼핑)')
    parser.add_argument('--update', type=int, help='변경할 expense ID')
    parser.add_argument('--to', help='새 카테고리')
    
    args = parser.parse_args()
    
    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ DB를 찾을 수 없습니다: {db_path}")
        return
    
    if args.find:
        find_suspicious_items(str(db_path), args.category)
    
    elif args.update and args.to:
        update_category(str(db_path), args.update, args.to)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
