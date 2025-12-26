# My Personal Asset Portfolio

A comprehensive personal wealth management application powered by a home server and local data synchronization.

## 🚀 Overview

This project is a full-stack web application designed to track and manage personal investment portfolios. It integrates with real-time trading APIs to provide up-to-date asset valuations, performance tracking, and portfolio rebalancing insights.

## ✨ Key Features

- **Automated Asset Tracking**: Real-time price updates for domestic (KRW) and international (USD) stocks via Korea Investment & Securities (KIS) API.
- **Dynamic Dashboard**: Visualize total assets, 6-month performance trends, portfolio distribution, and rebalancing alerts.
- **Transaction Management**: Easily add, buy, or sell assets. The system automatically calculates average cost basis and realized profit/loss.
- **Comprehensive History**: Searchable and filterable transaction logs with pagination.
- **Security & Reliability**: API token locking mechanism and automated daily backups to ensure data integrity.

## 🛠 Tech Stack

### Frontend
- **Framework**: React 18+
- **Language**: TypeScript
- **Styling**: Vanilla CSS / Tailored UI
- **Build Tool**: Vite
- **Testing**: Vitest

### Backend
- **Framework**: FastAPI (Python)
- **Database**: SQLite
- **API Integration**: KIS Open Trading API
- **Automation**: Bash scripts & Cron jobs

## ⚙️ Quick Start

### Frontend (Local Development)
```bash
npm install
npm run dev
```
Accessible at `http://localhost:5173`.

### Backend
1. **Prepare Environment**:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Configuration**:
   - Create a `.env` file in the `backend/` directory with your `API_TOKEN`.
   - Ensure your KIS API credentials are set up in `~/KIS/config/kis_user.yaml`.
3. **Run Server**:
   ```bash
   uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

## 📦 Maintenance

- **Backups**: Automated database backups are configured via cron.
- **Sync**: Market price synchronization runs on a scheduled basis as defined in the system's crontab.

## 📝 License

This project is for personal use and is not licensed for redistribution.
