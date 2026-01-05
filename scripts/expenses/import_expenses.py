#!/usr/bin/env python3
"""
카드사, 통장 거래내역 및 네이버페이 텍스트 자동 임포트 스크립트
지원: Excel (.xlsx, .xls), CSV (.csv), 네이버페이 텍스트 (.txt)
자동 카테고리 분류 + 중복 제거

네이버페이 사용법:
  1. 네이버페이 앱 > 결제내역에서 원하는 내역 복사
  2. 텍스트 파일(.txt)로 저장
  3. python import_expenses.py naverpay.txt 실행
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 프로젝트 루트 설정
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.expenses.importer import import_expenses_from_file


def main():
    parser = argparse.ArgumentParser(
        description='카드사/통장/네이버페이 거래내역을 DB에 자동 임포트',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  # 단일 파일 임포트
  python -m scripts.expenses.import_expenses 우리카드_2025.xlsx
  
  # 여러 파일 한번에 임포트
  python -m scripts.expenses.import_expenses 신한카드_2025.xlsx 국민은행_2025.csv
  
  # 네이버페이 결제내역 임포트 (복사한 텍스트 파일)
  python -m scripts.expenses.import_expenses naverpay_2025_12.txt
  
  # 미리보기 (실제 저장 안 함)
  python -m scripts.expenses.import_expenses --dry-run 현대카드_2025.xlsx
  
  # 자동 카테고리 분류 비활성화
  python -m scripts.expenses.import_expenses --no-auto-category 토스뱅크_2025.xlsx
        """
    )
    parser.add_argument('files', nargs='+', help='Excel, CSV 또는 TXT 파일 경로')
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
