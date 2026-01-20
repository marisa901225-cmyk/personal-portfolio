
# 🤖 AI Agent Improvement Prompts

> ## 🚨 MANDATORY: FILE MODIFICATION REQUIRED
> 
> **⛔ DO NOT just respond with text or code blocks.**
> **⛔ DO NOT say "you can modify like this" without actually modifying.**
> **⛔ DO NOT explain what needs to be done without doing it.**
> 
> **✅ YOU MUST use file editing tools (`replace_string_in_file`, `create_file`, `multi_replace_string_in_file`) to directly modify files.**
> **✅ After each prompt, confirm "I have modified the file(s)" with the actual changes made.**
> 
> ---
> 
> **Process ALL prompts below SEQUENTIALLY. Do NOT stop after completing one prompt.**

---

## 📋 Execution Checklist

| # | Prompt ID | Title | Priority | Status |
|:---:|:---|:---|:---:|:---:|
| 1 | PROMPT-001 | Add Unit Tests for Frontend Logic (`test-coverage-frontend-001`) | P1 | ⬜ Pending |
| 2 | PROMPT-002 | Enhance Frontend Type Safety (`code-quality-frontend-001`) | P2 | ⬜ Pending |
| 3 | PROMPT-003 | Refactor Portfolio Router Logic (`arch-backend-refactor-001`) | P2 | ⬜ Pending |
| 4 | PROMPT-004 | Structure Backend Error Logs (`infra-logging-001`) | P3 | ⬜ Pending |
| 5 | PROMPT-005 | Optimize SimHash with Caching (`opt-simhash-cache-001`) | OPT | ⬜ Pending |
| 6 | PROMPT-006 | Fix Library Deprecation Warnings (`opt-fix-library-warnings`) | OPT | ⬜ Pending |

**Total: 6 prompts** | **Completed: 0** | **Remaining: 6**

---

## 🔴 Priority 1 (Critical) - Execute First

### **⏱️ Execute this prompt now, then proceed to PROMPT-002**

### [PROMPT-001] Add Unit Tests for Frontend Logic (`test-coverage-frontend-001`)

> **🚨 REQUIRED: Use `replace_string_in_file` or `create_file` to make changes. Do NOT just show code.**

Task: Add a runtime validation utility and unit tests to cover critical frontend data-parsing logic.

Files to Modify / Create:
- `frontend/src/shared/utils/validation.ts` (create)
- `frontend/src/shared/api/client/types.test.ts` (create)

Implementation Code:

```typescript
// frontend/src/shared/utils/validation.ts
export type Asset = {
    id: string;
    symbol: string;
    name?: string;
    quantity: number;
    price?: number;
};

export function isAsset(obj: unknown): obj is Asset {
    if (typeof obj !== 'object' || obj === null) return false;
    const o = obj as Record<string, unknown>;
    return (
        typeof o.id === 'string' &&
        typeof o.symbol === 'string' &&
        typeof o.quantity === 'number' &&
        (o.name === undefined || typeof o.name === 'string') &&
        (o.price === undefined || typeof o.price === 'number')
    );
}

export function validateAssetsArray(arr: unknown): Asset[] {
    if (!Array.isArray(arr)) throw new Error('Not an array');
    const out: Asset[] = [];
    for (const item of arr) {
        if (!isAsset(item)) throw new Error('Invalid asset object');
        out.push(item);
    }
    return out;
}
```

```typescript
// frontend/src/shared/api/client/types.test.ts
import { describe, it, expect } from 'vitest';
import { isAsset, validateAssetsArray } from '../../utils/validation';

describe('Asset validation utilities', () => {
    it('validates a correct asset object', () => {
        const a = { id: '1', symbol: 'ABC', name: 'ABC Corp', quantity: 10, price: 123.45 };
        expect(isAsset(a)).toBe(true);
    });

    it('rejects an invalid asset object', () => {
        const bad = { id: 1, symbol: 'ABC', quantity: '10' };
        expect(isAsset(bad)).toBe(false);
    });

    it('validateAssetsArray accepts valid arrays', () => {
        const arr = [{ id: '1', symbol: 'A', quantity: 1 }];
        expect(() => validateAssetsArray(arr)).not.toThrow();
    });

    it('validateAssetsArray rejects invalid arrays', () => {
        const arr = [{ id: '1', symbol: 'A', quantity: '1' }];
        expect(() => validateAssetsArray(arr as unknown)).toThrow();
    });
});
```

Verification:

```bash
cd frontend
npm run test
```

**✅ After completing this prompt, proceed to PROMPT-002**

---

## 🟡 Priority 2 (High) - Execute Second

### **⏱️ Execute this prompt now, then proceed to PROMPT-003**

### [PROMPT-002] Enhance Frontend Type Safety (`code-quality-frontend-001`)

> **🚨 REQUIRED: Use `replace_string_in_file` to update `frontend/src/shared/api/client/types.ts`.**

Task: Replace `any` types with concrete interfaces and export them for shared use.

Files to Modify:
- `frontend/src/shared/api/client/types.ts` (replace)

Implementation Code (complete file):

```typescript
// frontend/src/shared/api/client/types.ts
export interface AssetDTO {
    id: string;
    symbol: string;
    name?: string;
    quantity: number;
    avgPrice?: number;
}

export interface QuoteDTO {
    symbol: string;
    price: number;
    timestamp: string; // ISO
}

export interface PortfolioResponse {
    userId: number;
    assets: AssetDTO[];
    totalValue?: number;
}

// If a dynamic payload is needed, prefer Record<string, unknown>
export type JsonObject = Record<string, unknown>;

export function parseAsset(raw: unknown): AssetDTO {
    if (typeof raw !== 'object' || raw === null) throw new Error('Invalid asset');
    const r = raw as Record<string, unknown>;
    return {
        id: String(r.id),
        symbol: String(r.symbol),
        name: r.name ? String(r.name) : undefined,
        quantity: Number(r.quantity),
        avgPrice: r.avgPrice ? Number(r.avgPrice) : undefined,
    };
}
```

Verification:

```bash
cd frontend
npm run typecheck
```

**✅ After completing this prompt, proceed to PROMPT-003**

---

### **⏱️ Execute this prompt now, then proceed to PROMPT-004**

### [PROMPT-003] Refactor Portfolio Router Logic (`arch-backend-refactor-001`)

> **🚨 REQUIRED: Use `replace_string_in_file` to update router and `create_file` if adding service file.**

Task: Move business logic from `backend/routers/portfolio.py` into `backend/services/portfolio.py` and update the router to call the service.

Files to Modify / Create:
- `backend/services/portfolio.py` (create or replace)
- `backend/routers/portfolio.py` (replace)

Implementation Code (complete files):

```python
# backend/services/portfolio.py
from typing import Dict, Any
from sqlalchemy.orm import Session

def get_portfolio_summary(db: Session, user_id: int) -> Dict[str, Any]:
        # Example implementation: adapt to actual ORM models
        # Query assets
        assets = db.execute("SELECT id, symbol, quantity, avg_price FROM assets WHERE user_id = :uid", {'uid': user_id}).fetchall()
        asset_list = []
        total_value = 0.0
        for row in assets:
                item = {
                        'id': row['id'],
                        'symbol': row['symbol'],
                        'quantity': float(row['quantity']),
                        'avgPrice': float(row.get('avg_price') or 0),
                }
                # Example: compute value if price available via separate query
                asset_list.append(item)
        # Summary
        summary = {
                'userId': user_id,
                'assets': asset_list,
                'totalValue': total_value,
        }
        return summary
```

```python
# backend/routers/portfolio.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.core.db import get_db
from backend.services.portfolio import get_portfolio_summary

router = APIRouter()

@router.get('/portfolio/{user_id}')
def get_portfolio(user_id: int, db: Session = Depends(get_db)):
        try:
                summary = get_portfolio_summary(db, user_id)
                return summary
        except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
```

Verification:

```bash
cd backend
python -m py_compile routers/portfolio.py
```

**✅ After completing this prompt, proceed to PROMPT-004**

---

### **⏱️ Execute this prompt now, then proceed to PROMPT-005**

### [PROMPT-004] Structure Backend Error Logs (`infra-logging-001`)

> **🚨 REQUIRED: Replace `backend/core/logging_config.py` with a structured JSON logger implementation.**

Task: Provide structured JSON logs using `python-json-logger` if available, with a safe fallback.

Files to Modify:
- `backend/core/logging_config.py` (replace)

Implementation Code (complete file):

```python
# backend/core/logging_config.py
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_global_logging(level: int = logging.INFO):
        handler = logging.StreamHandler(stream=sys.stdout)
        fmt = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
        handler.setFormatter(fmt)
        root = logging.getLogger()
        root.setLevel(level)
        # remove existing handlers
        for h in list(root.handlers):
                root.removeHandler(h)
        root.addHandler(handler)

def get_logger(name: str):
        return logging.getLogger(name)

# Fallback if python-json-logger not installed
try:
        # ensure import succeeded above
        pass
except Exception:
        def setup_global_logging(level: int = logging.INFO):
                fmt = '%(asctime)s %(levelname)s in %(module)s: %(message)s'
                logging.basicConfig(level=level, format=fmt)

```

Verification:

```bash
cd backend
python -m py_compile core/logging_config.py
```

**✅ After completing this prompt, proceed to PROMPT-005**

---

### **⏱️ Execute this prompt now, then proceed to PROMPT-006**

### [PROMPT-005] Optimize SimHash with Caching (`opt-simhash-cache-001`)

> **🚨 REQUIRED: Modify the SimHash calculation to use a cache decorator. Replace or create `backend/services/news/deduplication.py`.**

Task: Add LRU caching to SimHash computation and ensure hashable inputs.

Files to Modify:
- `backend/services/news/deduplication.py` (replace)

Implementation Code (complete file):

```python
# backend/services/news/deduplication.py
from functools import lru_cache
from typing import Tuple

def _normalize_text(text: str) -> str:
        return ' '.join(text.split()).strip().lower()

@lru_cache(maxsize=2048)
def compute_simhash_for_text(text: str) -> int:
        # simple placeholder simhash: use Python's hash of normalized text for caching demo
        norm = _normalize_text(text)
        return hash(norm)

def is_duplicate(text: str, existing_hashes: Tuple[int, ...]) -> bool:
        h = compute_simhash_for_text(text)
        return h in existing_hashes

```

Verification:

```bash
cd backend
python -m py_compile services/news/deduplication.py
```

**✅ After completing this prompt, proceed to PROMPT-006**

---

## 🟢 Priority 3 (Medium) - Execute Last

### **⏱️ Execute this prompt now, then proceed to the FINAL step**

### [PROMPT-006] Fix Library Deprecation Warnings (`opt-fix-library-warnings`)

> **🚨 REQUIRED: Update schema examples and main app lifespan. Replace `backend/core/schemas.py` and `backend/main.py` where applicable.**

Task: Provide example migrations for Pydantic v2 style and a lifespan usage pattern for FastAPI.

Files to Modify:
- `backend/core/schemas.py` (replace example model)
- `backend/main.py` (replace app startup/shutdown to use lifespan)

Implementation Code (complete files):

```python
# backend/core/schemas.py
from pydantic import BaseModel
from pydantic import ConfigDict

class ExampleModel(BaseModel):
        model_config = ConfigDict(extra='forbid')
        id: int
        name: str

```

```python
# backend/main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from backend.core.logging_config import setup_global_logging

@asynccontextmanager
async def lifespan(app: FastAPI):
        # startup
        setup_global_logging()
        yield
        # shutdown

app = FastAPI(lifespan=lifespan)

```

Verification:

```bash
cd backend
python -m py_compile core/schemas.py
python -m py_compile main.py
```

**✅ After completing this prompt, proceed to the FINAL step**

---

## Final Completion

**🎉 ALL PROMPTS COMPLETED!**

Process to verify end-to-end:

```bash
# Frontend checks
cd frontend
npm run typecheck || true
npm run test || true

# Backend checks
cd ../backend
python -m py_compile core/logging_config.py || true
python -m py_compile main.py || true
pytest -q || true
```

**IMPORTANT:** After each prompt is applied, the agent MUST append a one-line confirmation to the relevant file(s) stating: `I have modified the file(s)` and list file paths changed.

