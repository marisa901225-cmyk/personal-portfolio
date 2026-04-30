from __future__ import annotations

import csv
import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


_SUMMARY_EVENT_LABELS = {
    "DAY_CHART_REVIEW": "단타 차트 LLM 검토",
    "DAY_CANDIDATE_FILTERED": "단타 후보 제외",
    "DAY_OVERNIGHT_CARRY_REVIEW": "단타 오버나잇 LLM 검토",
    "ENTER": "진입",
    "ENTRY_FILL": "진입 체결",
    "ERROR": "오류",
    "EXIT": "청산",
    "EXIT_FILL": "청산 체결",
    "EXIT_ORDER_ACCEPTED": "청산 주문 접수",
    "FORCE_EXIT": "강제 청산",
    "HOLD_MATCH": "기보유 유지",
    "NEWS_SENTIMENT": "뉴스 심리",
    "OPEN_ORDERS": "미체결 처리",
    "PASS": "패스",
    "RUN_METRICS": "실행 계측",
    "STATE_RECONCILE_ADD": "상태 동기화 신규 반영",
    "STATE_RECONCILE_DROP": "상태 동기화 정리",
    "STATE_RECONCILE_UPDATE": "상태 동기화 보정",
    "SWING_CHART_REVIEW": "스윙 차트 LLM 검토",
}


@dataclass(slots=True)
class TradeJournal:
    output_dir: str
    asof_date: str
    write_csv: bool = False
    jsonl_path: str = field(init=False)
    csv_path: str | None = field(init=False, default=None)
    total_events: int = 0
    event_counts: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        self.jsonl_path = os.path.join(self.output_dir, f"trade_journal_{self.asof_date}.jsonl")
        if self.write_csv:
            self.csv_path = os.path.join(self.output_dir, f"trade_journal_{self.asof_date}.csv")

    def log(self, event: str, **fields: Any) -> None:
        row = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": event,
            **fields,
        }
        with open(self.jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

        if self.csv_path:
            self._append_csv_row(row)
        self.total_events += 1
        self.event_counts[event] = self.event_counts.get(event, 0) + 1

    def _append_csv_row(self, row: dict[str, Any]) -> None:
        assert self.csv_path
        exists = os.path.exists(self.csv_path)
        with open(self.csv_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(row.keys()))
            if not exists:
                writer.writeheader()
            writer.writerow(row)

    def summary(self) -> str:
        """이벤트별 카운트 요약 문자열 반환"""
        counts = self._load_event_counts_from_file() or dict(self.event_counts)
        # 알림에서 노이즈인 내부 이벤트는 제외
        skip = {"RUN_START", "RUN_END", "SCAN_DONE"}
        lines = []
        scan = counts.get("SCAN_DONE", 0)
        if scan:
            lines.append(f"스캔: {scan}회")
        for event, count in sorted(counts.items()):
            if event in skip:
                continue
            label = _SUMMARY_EVENT_LABELS.get(event, event)
            lines.append(f"{label}: {count}회")
        return " | ".join(lines) if lines else "이벤트 없음"

    def _load_event_counts_from_file(self) -> dict[str, int]:
        if not os.path.exists(self.jsonl_path):
            return {}

        counts: dict[str, int] = {}
        try:
            with open(self.jsonl_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    event = str(row.get("event") or "").strip()
                    if not event:
                        continue
                    counts[event] = counts.get(event, 0) + 1
        except OSError:
            return {}

        return counts

    def make_backup_zip(
        self,
        *,
        state_file: str | None = None,
        runlog_file: str | None = None,
        extra_files: list[str] | None = None,
    ) -> str:
        zip_path = os.path.join(self.output_dir, f"trade_backup_{self.asof_date}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            if os.path.exists(self.jsonl_path):
                zf.write(self.jsonl_path, arcname=os.path.basename(self.jsonl_path))
            if self.csv_path and os.path.exists(self.csv_path):
                zf.write(self.csv_path, arcname=os.path.basename(self.csv_path))
            if state_file and os.path.exists(state_file):
                zf.write(state_file, arcname=os.path.basename(state_file))
            if runlog_file and os.path.exists(runlog_file):
                zf.write(runlog_file, arcname=os.path.basename(runlog_file))
            for p in extra_files or []:
                if os.path.exists(p):
                    zf.write(p, arcname=os.path.basename(p))
        return zip_path
