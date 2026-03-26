from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


SMALL_PROFIT_LEVELS = (0.10, 0.25, 0.50)


@dataclass(slots=True)
class BacktestResult:
    equity_curve: pd.DataFrame
    trade_log: pd.DataFrame
    tax_log: pd.DataFrame
    final_equity: float
    liquidation_value_after_tax: float
    pending_tax_liability: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    annual_vol_pct: float
    exposure_pct: float
    total_commission_paid: float
    total_slippage_paid: float
    total_tax_paid: float
    total_paid_in: float
    net_profit: float
    paid_in_multiple: float
    xirr_pct: float
    contribution_count: int


def load_sheet(path: str | Path, *, tqqq_source: str = "sheet") -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="환산 주가")
    frame = df[
        [
            "날짜",
            "DEF",
            "S&P 500 (Stooq ^SPX)",
            "나스닥 100 (Stooq ^NDX)",
            "TQQQ (YF+수수료 미반영)",
            "TQQQ (YF+SS 1%, ER 0.95%)",
        ]
    ].copy()
    frame.columns = ["date", "dff", "spx", "ndx", "tqqq_raw", "tqqq_sheet"]
    frame["date"] = pd.to_datetime(frame["date"])
    for col in ["dff", "spx", "ndx", "tqqq_raw", "tqqq_sheet"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    if tqqq_source == "sheet":
        # The workbook's synthetic TQQQ series already reflects funding cost (DFF/DEF),
        # expense ratio, and spread/slippage assumptions embedded in the sheet formulas.
        frame["tqqq"] = frame["tqqq_sheet"].combine_first(frame["tqqq_raw"])
    elif tqqq_source == "raw":
        frame["tqqq"] = frame["tqqq_raw"].combine_first(frame["tqqq_sheet"])
    else:
        raise ValueError(f"Unsupported tqqq_source: {tqqq_source}")
    frame = frame.dropna(subset=["date", "dff", "spx", "ndx", "tqqq"]).sort_values("date").reset_index(drop=True)
    frame["ma200"] = frame["ndx"].rolling(200).mean()
    frame["above_ma200"] = frame["ndx"] > frame["ma200"]
    frame["above_ma200_3d"] = (
        frame["above_ma200"]
        & frame["above_ma200"].shift(1, fill_value=False)
        & frame["above_ma200"].shift(2, fill_value=False)
    )
    return frame


def accrue_cash(cash: float, dff_pct: float, days: int) -> float:
    if cash <= 0 or days <= 0:
        return cash
    return cash * (1.0 + max(dff_pct, 0.0) / 100.0 * days / 360.0)


def max_drawdown_pct(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    rolling_max = equity.cummax()
    drawdown = equity / rolling_max - 1.0
    return float(drawdown.min() * 100.0)


def annual_vol_pct(returns: pd.Series) -> float:
    clean = returns.dropna()
    if clean.empty:
        return 0.0
    return float(clean.std(ddof=0) * math.sqrt(252.0) * 100.0)


def cagr_pct(start_equity: float, end_equity: float, start_date: pd.Timestamp, end_date: pd.Timestamp) -> float:
    if start_equity <= 0 or end_equity <= 0 or end_date <= start_date:
        return 0.0
    years = (end_date - start_date).days / 365.25
    if years <= 0:
        return 0.0
    return float(((end_equity / start_equity) ** (1.0 / years) - 1.0) * 100.0)


def xirr_pct(cashflows: list[tuple[pd.Timestamp, float]]) -> float:
    if len(cashflows) < 2:
        return 0.0
    amounts = [float(amount) for _, amount in cashflows]
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        return 0.0

    base_date = cashflows[0][0]
    years = [((date - base_date).days / 365.25) for date, _ in cashflows]

    def npv(rate: float) -> float:
        return sum(amount / ((1.0 + rate) ** year) for amount, year in zip(amounts, years))

    low, high = -0.9999, 1.0
    f_low, f_high = npv(low), npv(high)
    expand_count = 0
    while f_low * f_high > 0 and expand_count < 30:
        high *= 2.0
        f_high = npv(high)
        expand_count += 1

    if f_low * f_high > 0:
        return 0.0

    for _ in range(200):
        mid = (low + high) / 2.0
        f_mid = npv(mid)
        if abs(f_mid) < 1e-12:
            return mid * 100.0
        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return ((low + high) / 2.0) * 100.0


def buy_with_cash(
    cash: float,
    price: float,
    *,
    commission_rate: float,
    slippage_rate: float,
) -> tuple[float, float, float, float, float]:
    if cash <= 0 or price <= 0:
        return 0.0, 0.0, 0.0, 0.0, cash
    exec_price = price * (1.0 + slippage_rate)
    shares = cash / (exec_price * (1.0 + commission_rate))
    gross = shares * exec_price
    commission = gross * commission_rate
    slip_cost = shares * price * slippage_rate
    total_cost = gross + commission
    residual_cash = cash - total_cost
    return shares, total_cost, commission, slip_cost, residual_cash


def sell_shares(
    shares: float,
    price: float,
    *,
    cost_basis_alloc: float,
    commission_rate: float,
    slippage_rate: float,
) -> tuple[float, float, float, float]:
    if shares <= 0 or price <= 0:
        return 0.0, 0.0, 0.0, 0.0
    exec_price = price * (1.0 - slippage_rate)
    gross = shares * exec_price
    commission = gross * commission_rate
    slip_cost = shares * price * slippage_rate
    net_proceeds = gross - commission
    realized_pnl = net_proceeds - cost_basis_alloc
    return net_proceeds, realized_pnl, commission, slip_cost


def shares_needed_for_net_proceeds(
    net_needed: float,
    price: float,
    *,
    commission_rate: float,
    slippage_rate: float,
) -> float:
    if net_needed <= 0 or price <= 0:
        return 0.0
    net_per_share = price * (1.0 - slippage_rate) * (1.0 - commission_rate)
    if net_per_share <= 0:
        return 0.0
    return net_needed / net_per_share


def estimate_liquidation_value_after_tax(
    *,
    cash: float,
    tqqq_shares: float,
    tqqq_cost_basis: float,
    spym_shares: float,
    spym_cost_basis: float,
    tqqq_price: float,
    spx_price: float,
    current_year_realized_pnl: float,
    tax_rate: float,
    commission_rate: float,
    slippage_rate: float,
) -> tuple[float, float]:
    liquidation_cash = cash
    liquidation_realized = current_year_realized_pnl

    if tqqq_shares > 0 and tqqq_price > 0:
        proceeds, realized, _, _ = sell_shares(
            tqqq_shares,
            tqqq_price,
            cost_basis_alloc=tqqq_cost_basis,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
        )
        liquidation_cash += proceeds
        liquidation_realized += realized

    if spym_shares > 0 and spx_price > 0:
        proceeds, realized, _, _ = sell_shares(
            spym_shares,
            spx_price,
            cost_basis_alloc=spym_cost_basis,
            commission_rate=commission_rate,
            slippage_rate=slippage_rate,
        )
        liquidation_cash += proceeds
        liquidation_realized += realized

    final_year_tax = max(liquidation_realized, 0.0) * tax_rate
    return liquidation_cash - final_year_tax, final_year_tax


def run_backtest(
    frame: pd.DataFrame,
    *,
    initial_capital: float = 1.0,
    monthly_contribution: float = 0.0,
    tax_rate: float = 0.22,
    commission_rate: float = 0.0005,
    slippage_rate: float = 0.0010,
) -> BacktestResult:
    cash = initial_capital
    tqqq_shares = 0.0
    tqqq_cost_basis = 0.0
    spym_shares = 0.0
    spym_cost_basis = 0.0
    entry_ref_price = 0.0
    entry_date: pd.Timestamp | None = None
    triggered_small: set[float] = set()
    triggered_large: set[int] = set()

    total_commission_paid = 0.0
    total_slippage_paid = 0.0
    total_tax_paid = 0.0

    equity_rows: list[dict[str, float | pd.Timestamp | int]] = []
    trade_rows: list[dict[str, object]] = []
    tax_rows: list[dict[str, object]] = []

    start_idx = int(frame["ma200"].first_valid_index() or 0)
    active_days = 0
    total_paid_in = initial_capital
    contribution_count = 0
    cashflows: list[tuple[pd.Timestamp, float]] = []
    if initial_capital > 0:
        cashflows.append((pd.Timestamp(frame.iloc[start_idx]["date"]), -initial_capital))

    current_tax_year = int(frame.iloc[start_idx]["date"].year)
    current_year_realized_pnl = 0.0
    cycle_realized_pnl = 0.0
    cycle_commission = 0.0
    cycle_slippage = 0.0
    cycle_tax = 0.0
    last_contribution_period: pd.Period | None = None

    def raise_cash_for_tax(shortfall: float, tqqq_price: float, spx_price: float) -> float:
        nonlocal cash
        nonlocal tqqq_shares
        nonlocal tqqq_cost_basis
        nonlocal spym_shares
        nonlocal spym_cost_basis
        nonlocal current_year_realized_pnl
        nonlocal cycle_realized_pnl
        nonlocal total_commission_paid
        nonlocal total_slippage_paid
        nonlocal cycle_commission
        nonlocal cycle_slippage

        remaining = max(shortfall, 0.0)
        if remaining <= 0:
            return 0.0

        def sell_from_position(kind: str, price: float) -> None:
            nonlocal remaining
            nonlocal cash
            nonlocal tqqq_shares
            nonlocal tqqq_cost_basis
            nonlocal spym_shares
            nonlocal spym_cost_basis
            nonlocal current_year_realized_pnl
            nonlocal cycle_realized_pnl
            nonlocal total_commission_paid
            nonlocal total_slippage_paid
            nonlocal cycle_commission
            nonlocal cycle_slippage

            if remaining <= 0 or price <= 0:
                return

            if kind == "spym":
                shares_held = spym_shares
                cost_basis_total = spym_cost_basis
            else:
                shares_held = tqqq_shares
                cost_basis_total = tqqq_cost_basis

            if shares_held <= 0:
                return

            sell_qty = min(
                shares_held,
                shares_needed_for_net_proceeds(
                    remaining,
                    price,
                    commission_rate=commission_rate,
                    slippage_rate=slippage_rate,
                ),
            )
            if sell_qty <= 0:
                return

            basis_alloc = cost_basis_total * (sell_qty / shares_held)
            proceeds, realized, commission, slip = sell_shares(
                sell_qty,
                price,
                cost_basis_alloc=basis_alloc,
                commission_rate=commission_rate,
                slippage_rate=slippage_rate,
            )
            cash += proceeds
            current_year_realized_pnl += realized
            cycle_realized_pnl += realized
            total_commission_paid += commission
            total_slippage_paid += slip
            cycle_commission += commission
            cycle_slippage += slip
            remaining = max(remaining - proceeds, 0.0)

            if kind == "spym":
                spym_shares -= sell_qty
                spym_cost_basis -= basis_alloc
            else:
                tqqq_shares -= sell_qty
                tqqq_cost_basis -= basis_alloc

        # Tax funding prefers selling the lower-volatility SPY proxy first.
        sell_from_position("spym", spx_price)
        sell_from_position("tqqq", tqqq_price)
        return remaining

    def deploy_cash_to_current_allocation(tqqq_price: float, spx_price: float) -> None:
        nonlocal cash
        nonlocal tqqq_shares
        nonlocal tqqq_cost_basis
        nonlocal spym_shares
        nonlocal spym_cost_basis
        nonlocal entry_ref_price
        nonlocal total_commission_paid
        nonlocal total_slippage_paid
        nonlocal cycle_commission
        nonlocal cycle_slippage

        if cash <= 0:
            return

        tqqq_value = tqqq_shares * tqqq_price
        spym_value = spym_shares * spx_price
        total_risk_value = tqqq_value + spym_value
        if total_risk_value <= 0:
            return

        available_cash = cash
        cash = 0.0

        tqqq_budget = 0.0
        spym_budget = 0.0
        if tqqq_value > 0 and spym_value > 0:
            tqqq_budget = available_cash * (tqqq_value / total_risk_value)
            spym_budget = available_cash - tqqq_budget
        elif tqqq_value > 0:
            tqqq_budget = available_cash
        else:
            spym_budget = available_cash

        if tqqq_budget > 0:
            shares, cost_basis, commission, slip, residual = buy_with_cash(
                tqqq_budget,
                tqqq_price,
                commission_rate=commission_rate,
                slippage_rate=slippage_rate,
            )
            tqqq_shares += shares
            tqqq_cost_basis += cost_basis
            total_commission_paid += commission
            total_slippage_paid += slip
            cycle_commission += commission
            cycle_slippage += slip
            cash += residual
            if tqqq_shares > 0:
                entry_ref_price = tqqq_cost_basis / tqqq_shares

        if spym_budget > 0:
            shares, cost_basis, commission, slip, residual = buy_with_cash(
                spym_budget,
                spx_price,
                commission_rate=commission_rate,
                slippage_rate=slippage_rate,
            )
            spym_shares += shares
            spym_cost_basis += cost_basis
            total_commission_paid += commission
            total_slippage_paid += slip
            cycle_commission += commission
            cycle_slippage += slip
            cash += residual

    for idx in range(start_idx, len(frame)):
        row = frame.iloc[idx]
        date = row["date"]
        dff = float(row["dff"])
        spx = float(row["spx"])
        ndx = float(row["ndx"])
        ma200 = float(row["ma200"]) if pd.notna(row["ma200"]) else float("nan")
        tqqq = float(row["tqqq"])

        if idx > start_idx:
            prev_date = frame.iloc[idx - 1]["date"]
            delta_days = int((date - prev_date).days)
            cash = accrue_cash(cash, float(frame.iloc[idx - 1]["dff"]), delta_days)

        row_year = int(date.year)
        if row_year != current_tax_year:
            prior_year_realized_pnl = current_year_realized_pnl
            tax_due = max(prior_year_realized_pnl, 0.0) * tax_rate
            current_tax_year = row_year
            current_year_realized_pnl = 0.0
            if tax_due > 0:
                tax_shortfall = max(tax_due - cash, 0.0)
                if tax_shortfall > 0:
                    raise_cash_for_tax(tax_shortfall, tqqq, spx)
                cash -= tax_due
                total_tax_paid += tax_due
                cycle_tax += tax_due
            tax_rows.append(
                {
                    "tax_year": row_year - 1,
                    "realized_pnl": prior_year_realized_pnl,
                    "tax_paid": tax_due,
                    "cash_after_tax": cash,
                }
            )

        contribution_period = date.to_period("M")
        if monthly_contribution > 0 and contribution_period != last_contribution_period:
            cash += monthly_contribution
            total_paid_in += monthly_contribution
            contribution_count += 1
            cashflows.append((date, -monthly_contribution))
            last_contribution_period = contribution_period
            if tqqq_shares > 0 or spym_shares > 0:
                deploy_cash_to_current_allocation(tqqq, spx)

        risk_on = tqqq_shares > 0 or spym_shares > 0
        if risk_on:
            active_days += 1

        if risk_on and ndx < ma200:
            if tqqq_shares > 0:
                proceeds, realized, commission, slip = sell_shares(
                    tqqq_shares,
                    tqqq,
                    cost_basis_alloc=tqqq_cost_basis,
                    commission_rate=commission_rate,
                    slippage_rate=slippage_rate,
                )
                cash += proceeds
                current_year_realized_pnl += realized
                cycle_realized_pnl += realized
                total_commission_paid += commission
                total_slippage_paid += slip
                cycle_commission += commission
                cycle_slippage += slip
                tqqq_shares = 0.0
                tqqq_cost_basis = 0.0

            if spym_shares > 0:
                proceeds, realized, commission, slip = sell_shares(
                    spym_shares,
                    spx,
                    cost_basis_alloc=spym_cost_basis,
                    commission_rate=commission_rate,
                    slippage_rate=slippage_rate,
                )
                cash += proceeds
                current_year_realized_pnl += realized
                cycle_realized_pnl += realized
                total_commission_paid += commission
                total_slippage_paid += slip
                cycle_commission += commission
                cycle_slippage += slip
                spym_shares = 0.0
                spym_cost_basis = 0.0

            trade_rows.append(
                {
                    "entry_date": entry_date,
                    "exit_date": date,
                    "entry_ref_price": entry_ref_price,
                    "exit_price": tqqq,
                    "cycle_realized_pnl": cycle_realized_pnl,
                    "cycle_return_pct": (cycle_realized_pnl / total_paid_in) * 100.0 if total_paid_in > 0 else 0.0,
                    "small_hits": len(triggered_small),
                    "large_hits": len(triggered_large),
                    "cycle_commission": cycle_commission,
                    "cycle_slippage": cycle_slippage,
                    "cycle_tax_paid_prior_years": cycle_tax,
                    "cash_after_exit": cash,
                }
            )

            entry_ref_price = 0.0
            entry_date = None
            triggered_small.clear()
            triggered_large.clear()
            cycle_realized_pnl = 0.0
            cycle_commission = 0.0
            cycle_slippage = 0.0
            cycle_tax = 0.0
            risk_on = False

        if tqqq_shares > 0 and entry_ref_price > 0:
            gain = tqqq / entry_ref_price - 1.0

            for level in SMALL_PROFIT_LEVELS:
                if gain >= level and level not in triggered_small:
                    shares_before = tqqq_shares
                    sell_qty = shares_before * 0.10
                    basis_alloc = tqqq_cost_basis * (sell_qty / shares_before)
                    proceeds, realized, commission, slip = sell_shares(
                        sell_qty,
                        tqqq,
                        cost_basis_alloc=basis_alloc,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                    tqqq_shares -= sell_qty
                    tqqq_cost_basis -= basis_alloc
                    current_year_realized_pnl += realized
                    cycle_realized_pnl += realized
                    total_commission_paid += commission
                    total_slippage_paid += slip
                    cycle_commission += commission
                    cycle_slippage += slip

                    buy_shares, buy_cost, buy_commission, buy_slip, residual = buy_with_cash(
                        proceeds,
                        spx,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                    spym_shares += buy_shares
                    spym_cost_basis += buy_cost
                    cash += residual
                    total_commission_paid += buy_commission
                    total_slippage_paid += buy_slip
                    cycle_commission += buy_commission
                    cycle_slippage += buy_slip
                    triggered_small.add(level)

            if gain >= 1.0:
                max_large = int(gain // 1.0)
                for multiple in range(1, max_large + 1):
                    if multiple in triggered_large:
                        continue
                    shares_before = tqqq_shares
                    sell_qty = shares_before * 0.50
                    basis_alloc = tqqq_cost_basis * (sell_qty / shares_before)
                    proceeds, realized, commission, slip = sell_shares(
                        sell_qty,
                        tqqq,
                        cost_basis_alloc=basis_alloc,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                    tqqq_shares -= sell_qty
                    tqqq_cost_basis -= basis_alloc
                    current_year_realized_pnl += realized
                    cycle_realized_pnl += realized
                    total_commission_paid += commission
                    total_slippage_paid += slip
                    cycle_commission += commission
                    cycle_slippage += slip

                    buy_shares, buy_cost, buy_commission, buy_slip, residual = buy_with_cash(
                        proceeds,
                        spx,
                        commission_rate=commission_rate,
                        slippage_rate=slippage_rate,
                    )
                    spym_shares += buy_shares
                    spym_cost_basis += buy_cost
                    cash += residual
                    total_commission_paid += buy_commission
                    total_slippage_paid += buy_slip
                    cycle_commission += buy_commission
                    cycle_slippage += buy_slip
                    triggered_large.add(multiple)

        if (tqqq_shares <= 0 and spym_shares <= 0) and bool(row["above_ma200_3d"]) and cash > 0:
            shares, cost_basis, commission, slip, residual = buy_with_cash(
                cash,
                tqqq,
                commission_rate=commission_rate,
                slippage_rate=slippage_rate,
            )
            tqqq_shares = shares
            tqqq_cost_basis = cost_basis
            cash = residual
            total_commission_paid += commission
            total_slippage_paid += slip
            cycle_commission += commission
            cycle_slippage += slip
            entry_ref_price = cost_basis / shares if shares > 0 else 0.0
            entry_date = date
            triggered_small.clear()
            triggered_large.clear()

        pending_tax = max(current_year_realized_pnl, 0.0) * tax_rate
        equity = cash + tqqq_shares * tqqq + spym_shares * spx - pending_tax
        equity_rows.append(
            {
                "date": date,
                "equity": equity,
                "cash": cash,
                "tqqq_value": tqqq_shares * tqqq,
                "spym_value": spym_shares * spx,
                "pending_tax": pending_tax,
                "ndx": ndx,
                "ma200": ma200,
                "risk_on": int(tqqq_shares > 0 or spym_shares > 0),
            }
        )

    curve = pd.DataFrame(equity_rows)
    trades = pd.DataFrame(trade_rows)
    taxes = pd.DataFrame(tax_rows)
    curve["daily_return"] = curve["equity"].pct_change().fillna(0.0)

    last_row = frame.iloc[-1]
    pending_tax_liability = max(current_year_realized_pnl, 0.0) * tax_rate
    liquidation_value_after_tax, liquidation_year_tax = estimate_liquidation_value_after_tax(
        cash=cash,
        tqqq_shares=tqqq_shares,
        tqqq_cost_basis=tqqq_cost_basis,
        spym_shares=spym_shares,
        spym_cost_basis=spym_cost_basis,
        tqqq_price=float(last_row["tqqq"]),
        spx_price=float(last_row["spx"]),
        current_year_realized_pnl=current_year_realized_pnl,
        tax_rate=tax_rate,
        commission_rate=commission_rate,
        slippage_rate=slippage_rate,
    )
    cashflows.append((pd.Timestamp(last_row["date"]), float(liquidation_value_after_tax)))

    final_equity = float(curve["equity"].iloc[-1]) if not curve.empty else initial_capital
    base_capital = total_paid_in if total_paid_in > 0 else initial_capital
    total_return_pct = (final_equity / base_capital - 1.0) * 100.0 if base_capital > 0 else 0.0
    exposure_pct = active_days / len(curve) * 100.0 if len(curve) else 0.0
    net_profit = float(liquidation_value_after_tax - total_paid_in)
    paid_in_multiple = float(liquidation_value_after_tax / total_paid_in) if total_paid_in > 0 else 0.0
    money_weighted_return = xirr_pct(cashflows)
    cagr_value = (
        cagr_pct(initial_capital, final_equity, curve["date"].iloc[0], curve["date"].iloc[-1])
        if (not curve.empty and monthly_contribution <= 0 and initial_capital > 0)
        else float("nan")
    )

    return BacktestResult(
        equity_curve=curve,
        trade_log=trades,
        tax_log=taxes,
        final_equity=final_equity,
        liquidation_value_after_tax=float(liquidation_value_after_tax),
        pending_tax_liability=float(pending_tax_liability),
        total_return_pct=float(total_return_pct),
        cagr_pct=float(cagr_value),
        max_drawdown_pct=max_drawdown_pct(curve["equity"]) if not curve.empty else 0.0,
        annual_vol_pct=annual_vol_pct(curve["daily_return"]) if not curve.empty else 0.0,
        exposure_pct=float(exposure_pct),
        total_commission_paid=float(total_commission_paid),
        total_slippage_paid=float(total_slippage_paid),
        total_tax_paid=float(total_tax_paid),
        total_paid_in=float(total_paid_in),
        net_profit=net_profit,
        paid_in_multiple=paid_in_multiple,
        xirr_pct=float(money_weighted_return),
        contribution_count=int(contribution_count),
    )


def print_summary(
    result: BacktestResult,
    *,
    tax_rate: float,
    commission_rate: float,
    slippage_rate: float,
) -> None:
    start_date = result.equity_curve["date"].iloc[0]
    end_date = result.equity_curve["date"].iloc[-1]
    print(f"기간: {start_date:%Y-%m-%d} ~ {end_date:%Y-%m-%d}")
    print(
        f"가정: 연도별 실현손익에 22% 세금, one-way 수수료 {commission_rate*100:.3f}%, "
        f"one-way 슬리피지 {slippage_rate*100:.3f}%"
    )
    print(f"총 납입원금: {result.total_paid_in:.4f}x")
    print(f"최종자산(미실현 평가, 당해연도 미납세 반영): {result.final_equity:.4f}x")
    print(f"오늘 전량 청산 기준 추정 순자산: {result.liquidation_value_after_tax:.4f}x")
    print(f"세후 순이익: {result.net_profit:+.4f}x")
    print(f"납입원금 대비 배수: {result.paid_in_multiple:.4f}x")
    print(f"XIRR: {result.xirr_pct:+.2f}%")
    print(f"총수익률: {result.total_return_pct:+.2f}%")
    if math.isnan(result.cagr_pct):
        print("CAGR: n/a (적립식은 XIRR 기준으로 해석)")
    else:
        print(f"CAGR: {result.cagr_pct:+.2f}%")
    print(f"최대낙폭: {result.max_drawdown_pct:+.2f}%")
    print(f"연율 변동성: {result.annual_vol_pct:.2f}%")
    print(f"위험자산 보유비중(일수 기준): {result.exposure_pct:.2f}%")
    print(f"누적 세금 납부액: {result.total_tax_paid:.4f}x")
    print(f"누적 수수료: {result.total_commission_paid:.4f}x")
    print(f"누적 슬리피지 비용: {result.total_slippage_paid:.4f}x")
    print(f"당해연도 미납 예상세: {result.pending_tax_liability:.4f}x")
    print(f"매매 사이클 수: {len(result.trade_log)}")

    if not result.tax_log.empty:
        print("최근 5개 납세 연도:")
        print(result.tax_log.tail(5).to_string(index=False))

    if not result.trade_log.empty:
        print("최근 5개 종료 사이클:")
        print(
            result.trade_log.tail(5)[
                [
                    "entry_date",
                    "exit_date",
                    "cycle_realized_pnl",
                    "small_hits",
                    "large_hits",
                    "cash_after_exit",
                ]
            ].to_string(index=False)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the TQQQ 200DMA strategy from the shared Google Sheet.")
    parser.add_argument("xlsx_path", help="Path to the downloaded workbook")
    parser.add_argument("--initial-capital", type=float, default=1.0, help="Initial capital in backtest units")
    parser.add_argument("--monthly-contribution", type=float, default=0.0, help="Contribution added on the first trading day of each month")
    parser.add_argument("--tax-rate", type=float, default=0.22, help="Annual capital gains tax rate")
    parser.add_argument("--commission-rate", type=float, default=0.0005, help="One-way commission rate")
    parser.add_argument("--slippage-rate", type=float, default=0.0010, help="One-way slippage rate")
    parser.add_argument(
        "--tqqq-source",
        choices=("sheet", "raw"),
        default="sheet",
        help="Use the sheet's synthetic TQQQ series (includes funding/ER/spread) or the fee-unadjusted raw series",
    )
    parser.add_argument("--csv-out", help="Optional path to save the daily equity curve as CSV")
    parser.add_argument("--trades-out", help="Optional path to save the trade log as CSV")
    parser.add_argument("--tax-out", help="Optional path to save the annual tax log as CSV")
    args = parser.parse_args()

    frame = load_sheet(args.xlsx_path, tqqq_source=args.tqqq_source)
    result = run_backtest(
        frame,
        initial_capital=args.initial_capital,
        monthly_contribution=args.monthly_contribution,
        tax_rate=args.tax_rate,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
    )
    print_summary(
        result,
        tax_rate=args.tax_rate,
        commission_rate=args.commission_rate,
        slippage_rate=args.slippage_rate,
    )

    if args.csv_out:
        result.equity_curve.to_csv(args.csv_out, index=False)
    if args.trades_out:
        result.trade_log.to_csv(args.trades_out, index=False)
    if args.tax_out:
        result.tax_log.to_csv(args.tax_out, index=False)


if __name__ == "__main__":
    main()
