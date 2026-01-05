# 📂 데이터 복구 참조 가이드 (Reference Data)

이 폴더는 포트폴리오 데이터가 손상되거나 수치가 이상할 때, 원본 데이터를 대조하고 복구하기 위한 용도로 생성되었습니다.

## 📄 파일 목록 및 용도

1. **consolidated_financial_data.xlsx**
   - **용도**: 증권사, 은행(KB), 카드사(우리, 국민)의 모든 내역을 하나로 통합한 파일입니다.
   - **생성일**: 2025-12-31
   - **참조**: 특정 월의 지출액이 이상하거나, 자산 수량이 안 맞을 때 시트별로 대조해 보세요.

2. **combined_statements_valuation.xlsx**
   - **용도**: 증권사 거래 내역의 최종 통합본입니다.
   - **특징**: `scripts/portfolio/import_2025_data.py`를 통해 DB에 입력된 원본 데이터 소스입니다.

3. **portfolio_2025-12-31.db**
   - **용도**: 2025년 12월 31일 기준의 최종 안정화된 데이터베이스 백업입니다.
   - **참조**: 자산 수량(KODEX 미국나스닥100 등)이 음수로 나오거나 계산이 꼬였을 때 이 파일을 사용하여 `assets` 테이블을 복구했습니다.

## 🛠 주요 복구 스크립트 (`scripts/portfolio`)

만약 미래에 데이터가 다시 뒤틀린다면 아래 스크립트들을 활용하세요:

- `scripts/portfolio/restore_assets_from_backup.py`: 백업 DB로부터 자산 상태를 강제 복구합니다.
- `scripts/portfolio/calculate_trade_realized_delta.py`: 거래 내역(trades)을 바탕으로 실현손익을 전수 재계산합니다.
- `scripts/portfolio/recalculate_realized_profit.py`: 전체 자산의 실현손익 합계를 재정렬합니다.

4. **raw_sources/**
   - **용도**: 은행 및 카드사에서 다운로드한 가공 전 원본 엑셀 파일들을 모아둔 폴더입니다.
   - **내용**: 
     - 은행: KB국민은행 거래내역, 우리은행(WOORI.xls)
     - 카드: 우리카드(report.xls 시리즈), 국민카드(국민카드.xls)
   - **참조**: 통합 엑셀(`consolidated_financial_data.xlsx`)의 기초 데이터입니다. 수동으로 입력된 항목의 정확성을 검증할 때 사용하세요.
