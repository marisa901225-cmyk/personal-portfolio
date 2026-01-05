# 📊 My Personal Asset Portfolio

A professional-grade, full-stack wealth management platform designed for sensitive data isolation using a home server environment and Tailscale private networking. This project serves as a centralized hub for tracking stocks, dividends, and cash flows with automated data synchronization.

---

## 🚀 Project Vision & Overview

This application is built to provide personal investors with a high-fidelity dashboard of their financial state without compromising privacy. By hosting the backend on a private home server and utilizing **Tailscale** for secure access, the system ensures that sensitive financial data remains under the user's control while being accessible from anywhere.

### Core Objectives:
- **Data Sovereignty**: Local first, private network access only.
- **Automation**: Hands-free price updates and scheduled data snapshots.
- **Precision**: Realized P&L, XIRR calculations, and historical trend analysis.
- **Extensibility**: Modular API design allowing for AI-driven report generation.

---

## ✨ Key Features

### 1. Automated Asset Tracking
- **KIS API Integration**: Seamless real-time price synchronization for domestic (South Korea) and international (US) tickers.
- **Ticker Search**: Smart ticker discovery using Korea Investment & Securities (KIS) master data.
- **FX Rates**: Automated USD/KRW exchange rate tracking based on market data.

### 2. Advanced Portfolio Management
- **Transaction Atomicity**: DB-level locking (`with_for_update`) ensures data integrity during buy/sell records.
- **Real-time Valuation**: Automatic calculation of average cost basis, current market value, and unrealized/realized profit and loss.
- **Dividend Tracking**: Dedicated module for recording dividend income and visualizing growth trends over time.
- **Target Rebalancing**: Set target asset allocations and receive actionable rebalancing insights.

### 3. Data Synchronization & Import
- **Brokerage Sync**: Support for uploading **Samsung Securities** Excel statements to automatically parse cash flows.
- **XIRR Calculation**: Internal Rate of Return (XIRR) support for precise performance measurement including external cash flows.
- **CSV Backup/Restore**: Comprehensive backup system with zip encryption support.
- **Expense Import**: Automated import of credit card and bank account transactions with intelligent category classification.

### 4. Dashboards & Analytics
- **Dynamic Visualization**: Charts for total assets (6-month performance), asset allocation (by category or index group), and dividend history.
- **Snapshot History**: Backend-driven daily snapshots allow for reliable historical trend visualization.

### 5. DuckDB Analytical Layer (NEW)
- **High-Performance OLAP**: Uses DuckDB's columnar engine to pre-compute complex aggregations directly from SQLite.
- **AI-Optimized Output**: Returns pre-calculated metrics (category/index breakdown, monthly trends, currency exposure) in a flat, AI-friendly JSON structure.
- **Zero-Copy Analysis**: DuckDB reads the SQLite database in-place without data duplication.

---

## 🛠 Tech Stack

### Frontend
- **Framework**: React 18+ (Vite)
- **Language**: TypeScript
- **State Management**: Custom React Hooks with local/session storage persistence.
- **Styling**: Vanilla CSS with modern, responsive principles.
- **Testing**: Vitest for unit and integration testing.

### Backend
- **Framework**: FastAPI (Python)
- **Database**: SQLite with SQLAlchemy ORM.
- **Analytics**: DuckDB for OLAP-style analytical queries.
- **Validation**: Pydantic v2 for robust schema enforcement.
- **Authentication**: API Token-based security (`X-API-Token`).
- **Scheduling**: Integration with systemd and Cron for automated tasks.

---

## ⚙️ API Documentation (v1)

All endpoints require the `X-API-Token` header if `API_TOKEN` is configured in the backend environment.

### Portfolio & Assets
- `GET /api/portfolio`: Retrieve high-level portfolio summary.
- `GET /api/assets`: List all managed assets.
- `POST /api/assets`: Register a new asset (initial buy recorded).
- `PATCH /api/assets/{id}`: Update asset metadata.
- `DELETE /api/assets/{id}`: Soft-delete an asset.
- `POST /api/assets/{id}/trades`: Record a BUY or SELL transaction.

### Market Data (KIS)
- `POST /api/kis/prices`: Fetch KRW-denominated prices for multiple tickers.
- `GET /api/search_ticker?q=...`: Search for ticker symbols in KIS master data.
- `GET /api/kis/fx/usdkrw`: Get the current real-time USD/KRW exchange rate.

### Reports (Optimized for AI Analysis)
- `GET /api/report`: General performance report.
- `GET /api/report/yearly?year=YYYY`: Annual performance breakdown.
- `GET /api/report/monthly?year=YYYY&month=MM`: Detailed monthly statistics.
- `GET /api/report/quarterly?year=YYYY&quarter=Q`: Quarterly summary.
- `GET /api/report/ai?year=YYYY&month=MM`: JSON-optimized output for AI report generation.
- `GET /api/report/ai/text?year=YYYY&month=MM`: LLM-generated narrative report (backend handles AI call).
- `GET /api/report/ai/text?query=...`: Natural language request (e.g., `2025년 2분기 리포트`, `2025년 상반기 리포트`, `올해 연간 리포트`).
- `GET /api/report/refined?year=YYYY&month=MM`: **DuckDB-refined** analytics with pre-computed metrics (recommended for local AI).

#### `/api/report/refined` Response Structure:
```json
{
  "refined_by": "DuckDB",
  "period": { "label": "2025", "year": 2025, ... },
  "portfolio_summary": { "total_value": ..., "total_invested": ..., ... },
  "asset_analytics": [ { "name": "...", "return_pct": ..., ... } ],
  "category_breakdown": [ { "category": "...", "weight_pct": ..., ... } ],
  "index_breakdown": [ { "index_group": "...", "weight_pct": ..., ... } ],
  "trade_activity": [ { "type": "BUY", "trade_count": ..., ... } ],
  "cashflow_summary": { "total_deposits": ..., "net_flow": ..., ... },
  "monthly_trend": [ { "month": "2025-01", "end_value": ..., ... } ],
  "currency_exposure": [ { "currency": "KRW", "weight_pct": ..., ... } ]
}
```

#### AI Report Generation (LLM)
Set these environment variables on the backend server:
- `AI_REPORT_API_KEY`: LLM API key (required).
- `AI_REPORT_BASE_URL`: Base URL for an OpenAI-compatible API (default: `https://api.openai.com/v1`).
- `AI_REPORT_MODEL`: Model name for monthly reports (default: `gpt-5.2`).
- `AI_REPORT_MODEL_YEARLY`: Model name for yearly reports (default: `gpt-5.2-pro`).
- `AI_REPORT_TEMPERATURE`: Sampling temperature (default: `0.3`).
- `AI_REPORT_MAX_TOKENS`: Maximum response tokens (default: `8000`, capped at `10000`).

### Expenses (Consumption Tracking)
- `GET /api/expenses/`: List expenses with optional filters (`year`, `month`, `category`).
- `POST /api/expenses/`: Create a new expense record.
- `PATCH /api/expenses/{id}`: Update an expense.
- `DELETE /api/expenses/{id}`: Delete an expense.
- `GET /api/expenses/summary`: Get category/method breakdown and fixed expense ratio.

#### Expense Record Fields:
| Field | Type | Description |
|-------|------|-------------|
| `date` | date | 결제일 (YYYY-MM-DD) |
| `amount` | float | 금액 (음수: 지출, 양수: 환불/수입) |
| `category` | string | 식비, 교통, 쇼핑, 고정지출 등 |
| `merchant` | string? | 가맹점명 (스타벅스 강남점, 쿠팡 등) |
| `method` | string? | 결제수단 (현대카드, 토스뱅크 등) |
| `is_fixed` | bool | 고정지출 여부 |
| `memo` | string? | AI 비고 |

### System & Settings
- `GET /api/settings`: Retrieve application and rebalancing configurations.
- `POST /api/settings`: Update settings (targets, API keys, etc.).
- `GET /api/health`: Backend reachability check.

---

## 📦 Deployment & Maintenance

### Infrastructure
- **Server**: Ubuntu-based home server.
- **Access**: Private access via [Tailscale](https://tailscale.com/).
- **Service Management**: Managed by `systemd` (`myasset-backend.service`).

### Automation (Cron)
- **Price Sync**: Scheduled updates for US/KR stocks (Tue-Sat).
- **Daily Snapshot**: Midnight capture of total portfolio value.
- **Automated Backups**: Weekly encrypted backups to external storage/Dropbox.

### 💳 Expense Data Import Guide

#### Supported File Formats
- **Excel**: `.xlsx`, `.xls`
- **CSV**: `.csv` (UTF-8 or CP949 encoding)

#### Required Columns
Your card/bank statement file must contain these columns (column names are auto-detected):

| Standard Name | Possible Column Names |
|--------------|----------------------|
| `date` | 일자, 거래일, 거래일자, 날짜, 승인일자, 이용일 |
| `merchant` | 가맹점, 가맹점명, 상호, 적요, 내역, 거래처, 사용처 |
| `amount` | 금액, 거래금액, 이용금액, 승인금액, 출금, 입금 |
| `method` (optional) | 결제수단, 카드, 카드명, 계좌, 은행, 수단 |

> **Note**: If `method` is missing, the script will use the filename as the payment method.

#### Automatic Category Classification
The script automatically classifies transactions into these categories:
- **식비**: Supermarkets, convenience stores, restaurants, cafes
- **교통**: Subway, bus, taxi, parking, gas stations, trains
- **통신**: Mobile carriers (SKT/KT/LG), internet, apartment management fees
- **구독**: Netflix, YouTube Premium, Spotify, app subscriptions
- **쇼핑**: E-commerce (Coupang, 11번가), department stores, electronics
- **이체**: Bank transfers, ATM withdrawals
- **급여**: Salary deposits
- **기타수입**: Cashback, points, interest
- **기타**: Unclassified items

> **Tip**: Keyword rules are managed in `backend/expense_category_keywords.json`. Update the file and re-run the import (or restart the backend) to apply changes.

#### Usage Examples

```bash
# Activate virtual environment first
source backend/.venv/bin/activate

# Import a single file
python3 scripts/expenses/import_expenses.py 우리카드_2025.xlsx

# Import multiple files at once
python3 scripts/expenses/import_expenses.py 신한카드_2025.xlsx 국민은행_2025.csv 토스뱅크_2025.xlsx

# Preview without saving (dry run)
python3 scripts/expenses/import_expenses.py --dry-run 현대카드_2025.xlsx

# Disable automatic category classification
python3 scripts/expenses/import_expenses.py --no-auto-category 카드내역.xlsx

# Custom database path
python3 scripts/expenses/import_expenses.py --db /path/to/custom.db 거래내역.xlsx
```


#### Output Example
```
🚀 거래내역 임포트 시작 (2개 파일)

📄 파일 읽는 중: 우리카드_2025.xlsx
✅ 152개 거래 발견

📋 데이터 미리보기 (처음 5개):
       date         merchant  amount      method
2025-01-15      스타벅스 강남점   -5400  우리체크카드
2025-01-16         홈플러스  -48200  우리체크카드
...

✅ DB에 저장 완료
  • 총 152개 | ✅ 추가 145개 | ⏭️  중복 7개

============================================================
📊 전체 요약
  • 처리한 파일: 2개
  • 총 거래: 304개
  • ✅ 새로 추가: 287개
  • ⏭️  중복 스킵: 17개
============================================================
```

#### Duplicate Detection
The script uses MD5 hashing based on `(date, merchant, amount, method)` to prevent duplicate imports. The hash is stored in the `memo` field as `HASH:xxxxx`.

#### Tips for Best Results
1. **File Naming**: Name files descriptively (e.g., `우리카드_2025년.xlsx`, `국민은행_2025_01.csv`)
2. **Column Order**: Column order doesn't matter - the script auto-detects them
3. **Amount Format**: Negative for expenses, positive for income
4. **Review Classifications**: After import, use `GET /api/expenses/summary` to review category breakdown

### Commands

```bash
# Frontend Build/Test
npm run typecheck
npm run test
npm run build

# Backend Test
source .venv/bin/activate
python -m unittest discover -s backend/tests -p "test_*.py"

# Install DuckDB dependency
pip install duckdb>=1.0.0
```

---

## 📈 Project Status (Latest Evaluation)

| Metric | Score | Grade |
|--------|-------|-------|
| **Code Quality** | 80/100 | B |
| **Architecture** | 78/100 | B |
| **Documentation** | 90/100 | A |
| **Overall Readiness** | 78/100 | B |

*Latest Snapshot: The system is currently in a stable state with core features fully operational. DuckDB analytical layer has been added for high-performance AI report generation.*

## 🧭 현재 상황
- 핵심 기능(자산/거래/배당/지출 추적, 보고서 생성)은 동작 가능한 상태입니다.
- 백엔드는 FastAPI + SQLite 기반으로 안정적으로 운영 가능하며, DuckDB 분석 레이어가 연동되어 AI 보고서에 필요한 집계가 빠르게 생성됩니다.
- Tailscale 기반의 사설 네트워크 접근과 스케줄링(가격 동기화/스냅샷/백업) 운영을 전제로 구성되어 있습니다.

## 🔭 차후 개선사항
- 프론트엔드 상태 표시/에러 처리 UX 개선 및 주요 흐름에 대한 UI 테스트 보강.
- 데이터 임포트(엑셀/CSV) 유효성 검사와 예외 처리 강화.
- 리포트 지표 확장(벤치마크 대비, 카테고리/지수별 변동 원인 분석 등).
- 배포/운영 자동화(CI에서 `typecheck`/`test`/`build` 실행, 릴리즈 노트 정리).
