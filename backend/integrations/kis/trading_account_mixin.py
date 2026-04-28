from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class KISAccountTradingMixin:
    def positions(self) -> list[dict[str, Any]]:
        """
        주식 잔고 조회 [v1_국내주식-006].
        GET /uapi/domestic-stock/v1/trading/inquire-balance
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            "TTTC8434R",
            params,
        )
        output1 = data.get("output1", [])
        result = []
        for r in output1:
            qty = int(r.get("hldg_qty", 0))
            if qty <= 0:
                continue
            result.append(
                {
                    "code": r.get("pdno", ""),
                    "name": r.get("prdt_name", ""),
                    "qty": qty,
                    "avg_price": float(r.get("pchs_avg_pric", 0)),
                    "current_price": int(r.get("prpr", 0)),
                    "pnl": int(r.get("evlu_pfls_amt", 0)),
                    "pnl_rate": float(r.get("evlu_pfls_rt", 0)),
                    "orderable_qty": int(r.get("ord_psbl_qty", 0)),
                }
            )
        return result

    def cash_available(self) -> int:
        """
        주문 가능 현금(예수금) 조회.
        잔고 조회 API의 output2에서 D+2 예수금(prvs_rcdl_excc_amt)을 사용한다.
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            "TTTC8434R",
            params,
        )
        output2 = data.get("output2", [])
        if output2:
            row = output2[0] if isinstance(output2, list) else output2
            return int(row.get("prvs_rcdl_excc_amt", 0))
        return 0

    def buy_order_capacity(
        self,
        code: str,
        order_type: str,
        price: int | None,
    ) -> dict[str, Any]:
        """
        종목별 매수가능조회.

        잔고조회 예수금이 아니라 KIS의 주문 심사 기준에 맞춘
        주문가능현금/미수없는매수금액/매수수량을 반환한다.
        """
        cano, acnt_prdt_cd = self._account()
        query_price = self._to_int(price)
        ord_dvsn = self._order_division_code(order_type)
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": code,
            "ORD_UNPR": str(query_price),
            "ORD_DVSN": ord_dvsn,
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-order",
            "TTTC8908R",
            params,
        )
        output = data.get("output", {})
        row = output[0] if isinstance(output, list) and output else output
        if not isinstance(row, dict):
            row = {}

        result = {
            "ord_psbl_cash": self._to_int(row.get("ord_psbl_cash")),
            "nrcvb_buy_amt": self._to_int(row.get("nrcvb_buy_amt")),
            "nrcvb_buy_qty": self._to_int(row.get("nrcvb_buy_qty")),
            "max_buy_amt": self._to_int(row.get("max_buy_amt")),
            "max_buy_qty": self._to_int(row.get("max_buy_qty")),
            "psbl_qty_calc_unpr": self._to_int(row.get("psbl_qty_calc_unpr")),
        }
        logger.info(
            "[KIS 매수가능조회] code=%s type=%s price=%s cash=%s nrcvb_amt=%s nrcvb_qty=%s calc_price=%s",
            code,
            order_type,
            query_price,
            result["ord_psbl_cash"],
            result["nrcvb_buy_amt"],
            result["nrcvb_buy_qty"],
            result["psbl_qty_calc_unpr"],
        )
        return result

    def sell_order_capacity(self, code: str) -> dict[str, Any]:
        """
        종목별 매도가능수량조회.

        보유수량과 별개로 현재 주문 가능한 실제 매도 수량을 반환한다.
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": code,
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-sell",
            "TTTC8408R",
            params,
        )
        output = data.get("output", {})
        row = output[0] if isinstance(output, list) and output else output
        if not isinstance(row, dict):
            row = {}

        result = {
            "ord_psbl_qty": self._to_int(row.get("ord_psbl_qty")),
            "hldg_qty": self._to_int(row.get("hldg_qty")),
        }
        logger.info(
            "[KIS 매도가능조회] code=%s sellable_qty=%s holding_qty=%s",
            code,
            result["ord_psbl_qty"],
            result["hldg_qty"],
        )
        return result

    def place_order(
        self,
        side: str,
        code: str,
        qty: int,
        order_type: str,
        price: int | None,
    ) -> dict[str, Any]:
        """
        주식 주문(현금) [v1_국내주식-001].
        POST /uapi/domestic-stock/v1/trading/order-cash
        """
        cano, acnt_prdt_cd = self._account()
        if side.lower() in ("sell", "매도"):
            tr_id = "TTTC0011U"
        else:
            tr_id = "TTTC0012U"

        ord_dvsn = self._order_division_code(order_type)
        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "PDNO": code,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(price or 0),
        }

        logger.info(
            "[KIS 주문] side=%s code=%s qty=%d type=%s price=%s",
            side, code, qty, order_type, price,
        )
        data = self._post(
            "/uapi/domestic-stock/v1/trading/order-cash",
            tr_id,
            body,
        )
        output = data.get("output", {})
        success = data.get("rt_cd") == "0"
        result = {
            "success": success,
            "order_id": output.get("ODNO", ""),
            "order_time": output.get("ORD_TMD", ""),
            "exchange": output.get("KRX_FWDG_ORD_ORGNO", ""),
            "msg": data.get("msg1", ""),
        }
        if success:
            logger.info("[KIS 주문 성공] %s", result)
        else:
            logger.error("[KIS 주문 실패] %s", result)
        return result

    def open_orders(self) -> list[dict[str, Any]]:
        """
        미체결 주문 조회 [v1_국내주식-004].
        GET /uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "0",
            "INQR_DVSN_2": "0",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl",
            "TTTC8036R",
            params,
        )
        output = data.get("output", [])
        result = []
        for r in output:
            result.append(
                {
                    "order_id": r.get("odno", ""),
                    "code": r.get("pdno", ""),
                    "name": r.get("prdt_name", ""),
                    "side": "buy" if r.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "qty": int(r.get("ord_qty", 0)),
                    "price": int(r.get("ord_unpr", 0)),
                    "filled_qty": int(r.get("tot_ccld_qty", 0)),
                    "remaining_qty": int(r.get("psbl_qty", 0)),
                    "order_time": r.get("ord_tmd", ""),
                }
            )
        return result

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        """
        주식 주문 취소 [v1_국내주식-003].
        POST /uapi/domestic-stock/v1/trading/order-rvsecncl
        """
        cano, acnt_prdt_cd = self._account()
        body = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_id,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": "0",
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }
        logger.info("[KIS 주문취소] order_id=%s", order_id)
        data = self._post(
            "/uapi/domestic-stock/v1/trading/order-rvsecncl",
            "TTTC0013U",
            body,
        )
        success = data.get("rt_cd") == "0"
        result = {
            "success": success,
            "order_id": order_id,
            "msg": data.get("msg1", ""),
        }
        if success:
            logger.info("[KIS 주문취소 성공] %s", result)
        else:
            logger.error("[KIS 주문취소 실패] %s", result)
        return result

    def inquire_realized_pnl(self) -> dict[str, Any]:
        """
        주식잔고조회_실현손익 [v1_국내주식-041].
        GET /uapi/domestic-stock/v1/trading/inquire-balance-rlz-pl
        """
        cano, acnt_prdt_cd = self._account()
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "00",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "COST_ICLD_YN": "Y",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        data = self._get(
            "/uapi/domestic-stock/v1/trading/inquire-balance-rlz-pl",
            "TTTC8494R",
            params,
        )
        if data.get("rt_cd") != "0":
            logger.warning("[KIS 실현손익 조회 실패] msg=%s", data.get("msg1"))
        return data

    def get_today_sell_avg_price(self, code: str) -> float | None:
        """
        오늘 매도한 특정 종목의 KIS 체결기준 실제 평균단가를 조회한다.
        """
        try:
            data = self.inquire_realized_pnl()
            for row in data.get("output1", []):
                if row.get("pdno", "").strip() != code.strip():
                    continue
                sll_qty = int(row.get("thdt_sll_qty", 0) or 0)
                if sll_qty <= 0:
                    continue
                avg = float(row.get("pchs_avg_pric", 0) or 0)
                if avg > 0:
                    logger.info(
                        "[KIS 실현손익] %s 오늘 매도 체결 평단가: %.0f (qty=%d)",
                        code, avg, sll_qty,
                    )
                    return avg
        except Exception as exc:
            logger.warning("[KIS 실현손익 조회 예외] code=%s err=%s", code, exc)
        return None
