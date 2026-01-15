# Replace the entire file: backend/services/alarm/processor.py
import logging
import os
import html
import joblib
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from ...core.models import IncomingAlarm, Expense, SpamAlarm
from .filters import (
    mask_sensitive_info,
    is_spam,
    is_promo_spam,
    is_whitelisted,
    should_ignore,
    is_spam_llm,
    is_review_spam,
)
from .parsers import parse_card_approval
from .sanitizer import escape_html_preserve_urls
from .llm_logic import summarize_with_llm, summarize_expenses_with_llm
from ...integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(BACKEND_DIR, "data")
MODEL_PATH = os.path.join(DATA_DIR, "expense_model.joblib")


def create_spam_alarm(alarm, classification: str, reason: str, masked_text: str) -> SpamAlarm:
    return SpamAlarm(
        raw_text=alarm.raw_text,
        masked_text=masked_text,
        sender=alarm.sender,
        app_name=alarm.app_name,
        package=alarm.package,
        app_title=alarm.app_title,
        conversation=alarm.conversation,
        classification=classification,
        discard_reason=reason,
        rule_version=1,
    )


async def process_alarms_batch(db: Session):
    pending = db.query(IncomingAlarm).filter(IncomingAlarm.status == "pending").all()
    if not pending:
        # 알람이 없어도 10분 간격으로 랜덤 메시지 발송 시도
        summary = await summarize_with_llm([])
        if summary:
            title = ["랜덤 토픽", "잡학사전", "오늘의 TMI", "심심풀이 지식"][datetime.now().minute // 5 % 4]
            await send_telegram_message(f"<b>[{title}]</b>\n\n{escape_html_preserve_urls(summary)}")
        return

    # 중복 제거
    ten_min_ago = datetime.now() - timedelta(minutes=10)
    recent_texts = {
        r[0]
        for r in db.query(IncomingAlarm.raw_text)
        .filter(
            IncomingAlarm.status.in_(["processed", "discarded"]),
            IncomingAlarm.received_at >= ten_min_ago,
        )
        .all()
    }

    deduplicated = []
    seen = set()
    did_work = False
    for alarm in pending:
        if alarm.raw_text in recent_texts or alarm.raw_text in seen:
            alarm.status, alarm.classification = "discarded", "duplicate"
            db.add(create_spam_alarm(alarm, "duplicate", "Duplicate within 10 minutes", mask_sensitive_info(alarm.raw_text)))
            did_work = True
        else:
            seen.add(alarm.raw_text)
            deduplicated.append(alarm)

    if not deduplicated and not did_work:
        return

    if not deduplicated:
        db.commit()
        # 남은 알람은 없지만 10분 단위 랜덤 메시지 시도
        idle_sm = await summarize_with_llm([])
        if idle_sm:
            title = ["랜덤 토픽", "잡학사전", "오늘의 TMI", "심심풀이 지식"][datetime.now().minute // 5 % 4]
            await send_telegram_message(f"<b>[{title}]</b>\n\n{escape_html_preserve_urls(idle_sm)}")
        return

    # 모델 로드
    nb_pipeline = joblib.load(MODEL_PATH) if os.path.exists(MODEL_PATH) else None
    from ..users import get_or_create_single_user

    user = get_or_create_single_user(db)

    summaries, to_summarize_alarms, to_analyze_expenses, senders = [], [], [], set()
    filtered_count, filtered_reasons = 0, {"광고/프로모션": 0, "OTP/보안": 0, "플레이스홀더": 0}

    for alarm in deduplicated:
        original = alarm.raw_text
        masked = alarm.masked_text if alarm.masked_text else mask_sensitive_info(original)

        # 필터링 로직
        discard_reason = None
        if "%antext" in original or "%evtprm" in original:
            discard_reason, classification = "Tasker placeholder", "placeholder"
            filtered_reasons["플레이스홀더"] += 1
        elif should_ignore(original):
            discard_reason, classification = "OTP/Security filter", "ignored"
            filtered_reasons["OTP/보안"] += 1
        else:
            full_check = f"[{alarm.sender or ''}] {alarm.app_title or ''} {original}"
            if not is_whitelisted(full_check):
                if is_review_spam(full_check):
                    discard_reason, classification = "Review/Rating request", "review_spam"
                else:
                    is_s, cl = is_spam(full_check, db)
                    if is_s:
                        discard_reason, classification = "Spam rule match", cl
                    elif is_promo_spam(full_check, db):
                        discard_reason, classification = "Promotion rule match", "promo_rule"
                    else:
                        is_s_l, cl_l = is_spam_llm(full_check)
                        if is_s_l:
                            discard_reason, classification = "LLM spam classification", cl_l

                if discard_reason:
                    filtered_reasons["광고/프로모션"] += 1

        if discard_reason:
            alarm.status, alarm.classification = "discarded", classification
            db.add(create_spam_alarm(alarm, classification, discard_reason, masked))
            filtered_count += 1
            continue

        if alarm.sender:
            senders.add(alarm.sender)

        # 카드 승인 처리
        card = parse_card_approval(original)
        if card:
            cat = nb_pipeline.predict([card["merchant"]])[0] if nb_pipeline and card["merchant"] else "기타"
            db.add(
                Expense(
                    user_id=user.id,
                    date=card["date"],
                    amount=card["amount"],
                    merchant=card["merchant"],
                    method=card["method"],
                    category=cat,
                )
            )
            alarm.status, alarm.classification = "processed", "rule"
            to_analyze_expenses.append({"merchant": card["merchant"], "amount": card["amount"], "category": cat})
            summaries.append(f"💳 <b>결제 승인</b>: {html.escape(card['merchant'])} ({abs(card['amount']):,.0f}원)")
            continue

        alarm.status, alarm.classification = "processed", "llm"
        to_summarize_alarms.append(
            {
                "text": masked,
                "sender": mask_sensitive_info(alarm.sender) if alarm.sender else None,
                "app_title": mask_sensitive_info(alarm.app_title) if alarm.app_title else None,
                "conversation": mask_sensitive_info(alarm.conversation) if alarm.conversation else None,
                "app_name": mask_sensitive_info(alarm.app_name) if alarm.app_name else None,
                "package": alarm.package,
            }
        )

    # 결과 취합 및 전송
    if to_analyze_expenses:
        insight = await summarize_expenses_with_llm(to_analyze_expenses)
        if insight:
            summaries.insert(0, f"💰 <b>지출 분석</b>: {html.escape(insight)}\n")

    # 요약할 알림이 있을 때만 LLM 호출 (빈 목록 호출 시 가짜 알림 생성 버그 방지)
    if to_summarize_alarms:
        llm_sm = await summarize_with_llm(to_summarize_alarms)
        if llm_sm:
            safe_sm = escape_html_preserve_urls(llm_sm)
            summaries.append("\n<b>[주요 알림 요약]</b>\n" + safe_sm)
    elif not to_analyze_expenses:
        # 알림도 없고 가계부도 없으면 (다 필터링된 경우) 랜덤 메시지 시도
        idle_sm = await summarize_with_llm([])
        if idle_sm:
            summaries.append(escape_html_preserve_urls(idle_sm))

    db.commit()
    if summaries:
        title = "알림 리포트"
        if to_analyze_expenses:
            title = "알림 및 가계부 리포트" if to_summarize_alarms else "가계부 리포트"
        elif not to_summarize_alarms:
            title = ["랜덤 토픽", "잡학사전", "오늘의 TMI", "심심풀이 지식"][datetime.now().minute // 5 % 4]

        header = f"<b>[{title}]</b>\n\n"
        if filtered_count > 0 and (to_summarize_alarms or to_analyze_expenses):
            header += f"🗑️ <i>필터링됨: {', '.join(f'{k} {v}개' for k, v in filtered_reasons.items() if v > 0)}</i>\n\n"
        await send_telegram_message(header + "\n".join(summaries))
