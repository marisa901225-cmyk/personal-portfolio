from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime
import hashlib
import json
from math import ceil
from pathlib import Path
from typing import Any, Iterator, Mapping, Protocol
from uuid import uuid4

import fcntl

from backend.services.pension_momentum import pension_index_family
from backend.services.pension_rebalancing import PensionAsset, PensionHolding, PensionOrderPlan
from backend.services.trading_engine.utils import is_excluded_etf


MIN_CASH_BUFFER_PCT = 0.05
DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT = 0.60
_SAFE_CASH_LIKE_KEYWORDS = (
    "머니마켓",
    "단기채",
    "초단기",
    "국고채",
    "미국채",
    "채권",
    "kofr",
    "cd금리",
    "금리액티브",
)
_UNSAFE_ETF_KEYWORDS = (
    "곱버스",
    "합성",
    "테마",
    "커버드콜",
)


class BuyCapacityClient(Protocol):
    def buy_order_capacity(self, code: str, *, price: int, order_type: str) -> dict[str, int]: ...


@dataclass(frozen=True)
class PensionSellSafetyResult:
    orders: list[PensionOrderPlan]
    max_qty_by_code: dict[str, int]


def resolve_pension_product(*, account: str, product: str) -> str:
    normalized_account = str(account or "").strip()
    configured_product = str(product or "").strip()
    embedded_product = normalized_account[8:10] if len(normalized_account) >= 10 else ""
    if embedded_product and configured_product and embedded_product != configured_product:
        raise RuntimeError("pension account product mismatch between account and KIS_MY_PROD2")
    resolved = embedded_product or configured_product
    if not resolved:
        raise RuntimeError("missing pension KIS env: KIS_MY_PROD2")
    if len(resolved) != 2 or not resolved.isdigit():
        raise RuntimeError("invalid pension product code; expected two digits")
    if resolved == "01":
        raise RuntimeError("general stock product 01 is forbidden for pension trading")
    return resolved


def normalized_price_history(prices: list[tuple[str, int]]) -> list[tuple[str, int]]:
    by_date: dict[str, int] = {}
    for raw_date, raw_price in prices:
        date_key = "".join(character for character in str(raw_date) if character.isdigit())[:8]
        price = int(raw_price)
        if len(date_key) == 8 and price > 0:
            by_date[date_key] = price
    return sorted(by_date.items())


def orderable_cash_for_buys(*, cash: int, cash_buffer_pct: float) -> int:
    normalized_buffer = max(MIN_CASH_BUFFER_PCT, min(0.50, float(cash_buffer_pct)))
    return int(max(0, int(cash)) * (1.0 - normalized_buffer))


def _master_value(info: object, name: str, default: object = None) -> object:
    if isinstance(info, Mapping):
        return info.get(name, default)
    return getattr(info, name, default)


def _valid_family_for_bucket(bucket: str, name: str) -> bool:
    compact = str(name or "").strip().lower().replace(" ", "")
    if bucket == "sp500":
        return "s&p500" in compact or "snp500" in compact
    if bucket == "momentum":
        return bool(pension_index_family(name))
    if bucket in {"bond", "parking"}:
        return any(keyword in compact for keyword in _SAFE_CASH_LIKE_KEYWORDS)
    return False


def validate_buyable_pension_assets(
    *,
    assets: list[PensionAsset],
    master_by_code: Mapping[str, object],
    avg_value_20d_by_code: Mapping[str, float],
    min_avg_value_20d: float,
) -> list[PensionAsset]:
    validated: list[PensionAsset] = []
    seen_codes: set[str] = set()
    for asset in assets:
        if asset.code in seen_codes:
            raise RuntimeError(f"duplicate pension asset code: {asset.code}")
        seen_codes.add(asset.code)
        if not asset.buyable:
            validated.append(asset)
            continue

        info = master_by_code.get(asset.code)
        if info is None:
            raise RuntimeError(f"buyable pension asset missing from stock master: {asset.code}")
        name = str(_master_value(info, "name", "") or "").strip()
        is_etf = bool(_master_value(info, "is_etf", False))
        if not is_etf:
            raise RuntimeError(f"buyable pension asset is not ETF: {asset.code} {name}")
        compact = name.lower().replace(" ", "")
        if is_excluded_etf({"name": name, "is_etf": True}) or any(
            keyword in compact for keyword in _UNSAFE_ETF_KEYWORDS
        ):
            raise RuntimeError(f"unsafe pension ETF is forbidden: {asset.code} {name}")
        if not _valid_family_for_bucket(asset.bucket, name):
            raise RuntimeError(
                f"pension ETF family mismatch: {asset.code} bucket={asset.bucket} name={name}"
            )
        avg_value_20d = float(avg_value_20d_by_code.get(asset.code, 0.0) or 0.0)
        if avg_value_20d < max(0.0, float(min_avg_value_20d)):
            raise RuntimeError(
                f"pension ETF liquidity below minimum: {asset.code} avg_value_20d={int(avg_value_20d)}"
            )
        validated.append(replace(asset, name=name))
    return validated


def apply_buy_capacity(
    *,
    client: BuyCapacityClient,
    orders: list[PensionOrderPlan],
    orderable_cash: int,
    holdings: list[PensionHolding] | None = None,
    total_value: int | None = None,
    max_single_asset_weight_pct: float = DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT,
) -> list[PensionOrderPlan]:
    remaining_orderable_cash = max(0, int(orderable_cash))
    holding_value_by_code = {
        holding.code: max(0, int(holding.value)) for holding in (holdings or [])
    }
    normalized_total_value = max(0, int(total_value or 0))
    normalized_max_weight = max(0.05, min(0.60, float(max_single_asset_weight_pct)))
    adjusted_orders: list[PensionOrderPlan] = []
    for order in orders:
        if order.side != "BUY":
            adjusted_orders.append(order)
            continue
        limit_price = max(1, int(order.price))
        capacity = client.buy_order_capacity(order.code, price=0, order_type="01")
        capacity_qty = int(capacity.get("nrcvb_buy_qty", 0) or 0)
        capacity_amount = int(capacity.get("nrcvb_buy_amt", 0) or 0)
        if capacity_qty <= 0 or capacity_amount <= 0:
            raise RuntimeError(f"buy capacity unavailable; refusing order: {order.code}")

        qty_candidates = [
            int(order.qty),
            remaining_orderable_cash // limit_price,
            capacity_amount // limit_price,
            capacity_qty,
        ]
        if normalized_total_value > 0:
            max_position_value = int(normalized_total_value * normalized_max_weight)
            remaining_position_value = max(
                0,
                max_position_value - holding_value_by_code.get(order.code, 0),
            )
            qty_candidates.append(remaining_position_value // limit_price)
        adjusted_qty = min(qty_candidates)
        if adjusted_qty <= 0:
            continue
        adjusted_amount = adjusted_qty * limit_price
        adjusted_orders.append(replace(order, qty=adjusted_qty, amount=adjusted_amount))
        holding_value_by_code[order.code] = (
            holding_value_by_code.get(order.code, 0) + adjusted_amount
        )
        remaining_orderable_cash -= adjusted_amount
    return adjusted_orders


def aggregate_and_validate_sell_orders(
    *,
    orders: list[PensionOrderPlan],
    holdings: list[PensionHolding],
    split_count: int,
    sellable_qty_by_code: Mapping[str, int] | None = None,
) -> PensionSellSafetyResult:
    holding_by_code = {holding.code: holding for holding in holdings}
    grouped: dict[str, list[PensionOrderPlan]] = {}
    for order in orders:
        if order.side != "SELL":
            raise RuntimeError(f"non-sell order reached sell safety boundary: {order.code}")
        grouped.setdefault(order.code, []).append(order)

    normalized_split_count = max(2, int(split_count))
    validated: list[PensionOrderPlan] = []
    max_qty_by_code: dict[str, int] = {}
    for code, code_orders in grouped.items():
        holding = holding_by_code.get(code)
        if holding is None or holding.qty <= 1:
            raise RuntimeError(f"sell would fully liquidate or lacks holding: {code}")
        total_qty = sum(max(0, int(order.qty)) for order in code_orders)
        max_partial_qty = min(holding.qty - 1, ceil(holding.qty / normalized_split_count))
        if sellable_qty_by_code is not None:
            sellable_qty = int(sellable_qty_by_code.get(code, 0) or 0)
            if sellable_qty <= 0:
                raise RuntimeError(f"sell capacity unavailable; refusing order: {code}")
            max_partial_qty = min(max_partial_qty, sellable_qty)
        max_qty_by_code[code] = max_partial_qty
        if total_qty <= 0 or total_qty > max_partial_qty:
            raise RuntimeError(
                f"sell absolute cap exceeded: {code} qty={total_qty} max={max_partial_qty}"
            )
        first = code_orders[0]
        reasons = list(dict.fromkeys(order.reason for order in code_orders if order.reason))
        validated.append(
            replace(
                first,
                qty=total_qty,
                price=int(holding.price),
                amount=total_qty * int(holding.price),
                reason=" / ".join(reasons),
            )
        )
    return PensionSellSafetyResult(validated, max_qty_by_code)


def active_open_orders(open_orders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active: list[dict[str, Any]] = []
    for order in open_orders:
        status = str(order.get("status") or order.get("ord_stat") or "").strip().upper()
        remaining_qty = int(order.get("remaining_qty") or order.get("psbl_qty") or 0)
        if status in {"FILLED", "DONE", "CANCELED", "CANCELLED"} or remaining_qty <= 0:
            continue
        active.append(order)
    return active


def assert_no_open_orders(open_orders: list[dict[str, Any]]) -> None:
    active = active_open_orders(open_orders)
    if not active:
        return
    identifiers = [
        f"{order.get('order_id', '')}:{order.get('code', '')}:{order.get('remaining_qty', '')}"
        for order in active
    ]
    raise RuntimeError(f"open pension orders exist; refusing duplicate execution: {','.join(identifiers)}")


def pension_plan_hash(*, signal_key: str, orders: list[PensionOrderPlan]) -> str:
    payload = {
        "signal_key": signal_key,
        "orders": [asdict(order) for order in orders],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def pension_signal_key(
    *,
    asof_date: str,
    job: str,
    regime: str,
    selected_momentum_code: str,
    trend_exit_codes: tuple[str, ...],
) -> str:
    quarter = f"{asof_date[:4]}Q{((int(asof_date[4:6]) - 1) // 3) + 1}"
    exits = ",".join(sorted(set(trend_exit_codes)))
    return "|".join((quarter, job, regime, selected_momentum_code, exits))


class PensionExecutionJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.state = self._read()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "runs": {}, "signals": {}}
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"invalid pension execution state: {self.path}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"invalid pension execution state: {self.path}")
        parsed.setdefault("version", 1)
        parsed.setdefault("runs", {})
        parsed.setdefault("signals", {})
        return parsed

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def begin(self, *, signal_key: str, sell_orders: list[PensionOrderPlan]) -> tuple[str, str]:
        previous_signal = self.state["signals"].get(signal_key, {})
        previous_sells = previous_signal.get("submitted_sell_qty_by_code", {})
        repeated_codes = sorted(
            order.code for order in sell_orders if int(previous_sells.get(order.code, 0) or 0) > 0
        )
        if repeated_codes:
            raise RuntimeError(
                f"same pension signal already sold codes: {','.join(repeated_codes)}"
            )
        execution_id = uuid4().hex
        plan_hash = pension_plan_hash(signal_key=signal_key, orders=sell_orders)
        self.state["runs"][execution_id] = {
            "status": "PLANNED",
            "signal_key": signal_key,
            "sell_plan_hash": plan_hash,
            "sell_orders": [asdict(order) for order in sell_orders],
            "submitted_sell_qty_by_code": {},
            "completed_sell_qty_by_code": {},
            "submitted_buy_qty_by_code": {},
            "created_at": datetime.now().astimezone().isoformat(),
        }
        self._write()
        return execution_id, plan_hash

    def mark_sell_submitted(self, *, execution_id: str, code: str, qty: int) -> None:
        run = self.state["runs"][execution_id]
        signal_key = str(run["signal_key"])
        run["status"] = "SELL_SUBMITTED"
        run["submitted_sell_qty_by_code"][code] = (
            int(run["submitted_sell_qty_by_code"].get(code, 0) or 0) + int(qty)
        )
        signal = self.state["signals"].setdefault(
            signal_key,
            {"submitted_sell_qty_by_code": {}, "completed_sell_qty_by_code": {}},
        )
        signal["submitted_sell_qty_by_code"][code] = (
            int(signal["submitted_sell_qty_by_code"].get(code, 0) or 0) + int(qty)
        )
        self._write()

    def mark_sells_filled(self, *, execution_id: str) -> None:
        run = self.state["runs"][execution_id]
        if run.get("sells_recorded"):
            return
        signal = self.state["signals"].setdefault(
            str(run["signal_key"]),
            {"submitted_sell_qty_by_code": {}, "completed_sell_qty_by_code": {}},
        )
        for code, qty in run["submitted_sell_qty_by_code"].items():
            normalized_qty = int(qty)
            run["completed_sell_qty_by_code"][code] = normalized_qty
            signal["completed_sell_qty_by_code"][code] = (
                int(signal["completed_sell_qty_by_code"].get(code, 0) or 0)
                + normalized_qty
            )
        run["sells_recorded"] = True
        run["status"] = "SELL_FILLED"
        run["sells_filled_at"] = datetime.now().astimezone().isoformat()
        self._write()

    def record_buy_plan(
        self,
        *,
        execution_id: str,
        signal_key: str,
        buy_orders: list[PensionOrderPlan],
    ) -> str:
        plan_hash = pension_plan_hash(signal_key=signal_key, orders=buy_orders)
        run = self.state["runs"][execution_id]
        run["buy_plan_hash"] = plan_hash
        run["buy_orders"] = [asdict(order) for order in buy_orders]
        self._write()
        return plan_hash

    def has_buy_submitted_on_date(
        self,
        *,
        signal_key: str,
        code: str,
        date_key: str,
    ) -> bool:
        signal = self.state["signals"].get(signal_key, {})
        return str(signal.get("last_buy_date_by_code", {}).get(code) or "") == date_key

    def mark_buy_submitted(
        self,
        *,
        execution_id: str,
        code: str,
        qty: int,
        date_key: str,
    ) -> None:
        run = self.state["runs"][execution_id]
        signal_key = str(run["signal_key"])
        run["status"] = "BUY_SUBMITTED"
        submitted_by_code = run.setdefault("submitted_buy_qty_by_code", {})
        submitted_by_code[code] = int(submitted_by_code.get(code, 0) or 0) + int(qty)
        signal = self.state["signals"].setdefault(signal_key, {})
        signal_submitted = signal.setdefault("submitted_buy_qty_by_code", {})
        signal_submitted[code] = int(signal_submitted.get(code, 0) or 0) + int(qty)
        signal.setdefault("last_buy_date_by_code", {})[code] = date_key
        self._write()

    def mark_success(self, *, execution_id: str) -> None:
        completed_at = datetime.now().astimezone().isoformat()
        run = self.state["runs"][execution_id]
        run["status"] = "SUCCESS"
        run["completed_at"] = completed_at
        signal = self.state["signals"].setdefault(
            str(run["signal_key"]),
            {"submitted_sell_qty_by_code": {}, "completed_sell_qty_by_code": {}},
        )
        signal["last_success_at"] = completed_at
        self.state["last_success_at"] = completed_at
        self.state["last_success_execution_id"] = execution_id
        self._write()

    def mark_failed(self, *, execution_id: str, reason: str) -> None:
        run = self.state["runs"].get(execution_id)
        if not isinstance(run, dict):
            return
        run["status"] = "FAILED"
        run["failure_reason"] = str(reason)
        run["failed_at"] = datetime.now().astimezone().isoformat()
        self._write()


@contextmanager
def pension_execution_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another pension rebalance execution is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


__all__ = [
    "DEFAULT_MAX_SINGLE_ASSET_WEIGHT_PCT",
    "MIN_CASH_BUFFER_PCT",
    "PensionExecutionJournal",
    "PensionSellSafetyResult",
    "active_open_orders",
    "aggregate_and_validate_sell_orders",
    "apply_buy_capacity",
    "assert_no_open_orders",
    "normalized_price_history",
    "orderable_cash_for_buys",
    "pension_execution_lock",
    "pension_plan_hash",
    "pension_signal_key",
    "resolve_pension_product",
    "validate_buyable_pension_assets",
]
