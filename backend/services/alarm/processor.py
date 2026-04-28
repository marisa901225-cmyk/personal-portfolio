# backend/services/alarm/processor.py
# 420줄 alarm_service.py에서 추출한 알람 처리 로직
import logging
import os
import re
import joblib
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session

from ...core.models import IncomingAlarm, Expense, SpamAlarm
from ...integrations.telegram import send_telegram_message
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
from .llm_logic_v2 import generate_random_message_payload, summarize_with_llm
from .match_notifier import check_upcoming_matches

logger = logging.getLogger(__name__)

# NB 모델 경로
MODEL_PATH = os.path.join(os.path.dirname(__file__), "../../data/expense_model.joblib")

# NB 모델 싱글톤 캐싱
_nb_pipeline = None
_RE_MAIL_BATCH_SENDER = re.compile(r"^\s*새\s*메일\s*\d+\s*개\s*$")
_ROUTE_ENV_KEYS = {
    "summary": {
        "base_url": "ALARM_SUMMARY_LLM_BASE_URL",
        "model": "ALARM_SUMMARY_MODEL_OVERRIDE",
    },
    "random": {
        "base_url": "ALARM_RANDOM_LLM_BASE_URL",
        "model": "ALARM_RANDOM_MODEL_OVERRIDE",
    },
}


def _env_optional(key: str) -> Optional[str]:
    value = (os.getenv(key) or "").strip()
    return value or None


def _sanitize_shared_llm_kwargs(llm_kwargs: dict) -> dict:
    return {
        key: value
        for key, value in llm_kwargs.items()
        if not key.startswith("summary_") and not key.startswith("random_")
    }


def _resolve_alarm_llm_route(
    route: str,
    model_override: Optional[str],
    llm_kwargs: dict,
) -> tuple[Optional[str], dict]:
    if route not in _ROUTE_ENV_KEYS:
        raise ValueError(f"Unknown alarm LLM route: {route}")

    shared_kwargs = _sanitize_shared_llm_kwargs(llm_kwargs)
    route_prefix = f"{route}_"
    route_base_url = llm_kwargs.get(f"{route_prefix}base_url_override") or _env_optional(
        _ROUTE_ENV_KEYS[route]["base_url"]
    )
    route_model = llm_kwargs.get(f"{route_prefix}model_override") or _env_optional(
        _ROUTE_ENV_KEYS[route]["model"]
    )

    if route_base_url:
        shared_kwargs["base_url_override"] = route_base_url

    # endpoint를 명시적으로 갈라 태울 때는 공용 model_override를 그대로 넘기지 않고,
    # route별 model이 없으면 해당 endpoint의 /v1/models 자동 탐색을 사용한다.
    resolved_model = route_model if route_model else (None if route_base_url else model_override)
    return resolved_model, shared_kwargs


def _get_nb_pipeline():
    """지출 분류 NB 모델을 싱글톤으로 로드한다."""
    global _nb_pipeline
    if _nb_pipeline is None and os.path.exists(MODEL_PATH):
        try:
            _nb_pipeline = joblib.load(MODEL_PATH)
            logger.info("NB expense classifier loaded")
        except Exception as e:
            logger.warning(f"Failed to load NB model: {e}")
    return _nb_pipeline


def _collapse_mail_batch_notifications(items: List[dict]) -> Tuple[List[dict], List[dict]]:
    """
    동일 앱의 '새 메일 N개' 배치 알림은 최신 1개만 남긴다.
    (예: Gmail의 2개/3개/5개 카운트가 연속 수집될 때 중복 합산 방지)
    """
    latest_by_app: Dict[str, dict] = {}
    dropped: List[dict] = []
    kept_non_batch: List[dict] = []

    for item in items:
        sender = (item.get("sender") or "").strip()
        app_name = (item.get("app_name") or "").strip().lower()
        if app_name and _RE_MAIL_BATCH_SENDER.match(sender):
            prev = latest_by_app.get(app_name)
            if prev is not None:
                dropped.append(prev)
            latest_by_app[app_name] = item
            continue
        kept_non_batch.append(item)

    kept = kept_non_batch + list(latest_by_app.values())
    kept.sort(key=lambda x: int(getattr(x.get("db_obj"), "id", 0)))
    return kept, dropped


def _build_alarm_filter_text(
    *,
    sender: Optional[str],
    app_name: Optional[str],
    package: Optional[str],
    app_title: Optional[str],
    body: str,
) -> str:
    parts = [
        f"[{sender or ''}]",
        f"[app:{app_name or ''}]",
        f"[pkg:{package or ''}]",
        app_title or "",
        body or "",
    ]
    return " ".join(part for part in parts if part).strip()


async def process_pending_alarms(db: Session, model_override: Optional[str] = None, **llm_kwargs):
    """
    수신된 알림들을 5분 배차로 처리한다.
    안정성: 배치 처리 (200개 제한) + 선점(processing 상태) + 에러 복구(try-finally)
    """
    # 1. 대상 조회
    pending = (
        db.query(IncomingAlarm)
        .filter(IncomingAlarm.status == "pending")
        .order_by(IncomingAlarm.id.asc())
        .limit(200)
        .all()
    )
    
    if pending:
        # 선점: 중복 실행 방지
        for alarm in pending:
            alarm.status = "processing"
        try:
            db.commit()
        except Exception as e:
            logger.error(f"Failed to set processing status: {e}")
            return # 락 걸리면 다음 기회에
    
    # 에러 발생 시 processing 상태인 것들을 pending으로 복구하기 위한 리스트
    processing_alarms = list(pending)
    
    try:
        # 경기 시작 알림 체크
        try:
            data_dir = os.path.join(os.path.dirname(__file__), "../../data")
            # constants 파일 이름 변경 반영
            await check_upcoming_matches(db, os.path.join(data_dir, "esports_catchphrases_v2.json"))
        except Exception as e:
            logger.warning(f"Match notification check failed: {e}")

        summaries: List[str] = []
        to_summarize_alarms: List[dict] = []
        senders: Set[str] = set()
        summary_model, summary_llm_kwargs = _resolve_alarm_llm_route("summary", model_override, llm_kwargs)
        random_model, random_llm_kwargs = _resolve_alarm_llm_route("random", model_override, llm_kwargs)
        
        filtered_count = 0
        filtered_reasons = {"광고/프로모션": 0, "OTP/보안": 0, "플레이스홀더": 0}
        nb_pipeline = _get_nb_pipeline()

        from ...services.users import get_or_create_single_user
        user = get_or_create_single_user(db)

        for alarm in processing_alarms[:]: # 복구를 위해 원본 리스트 복사본 순회
            try:
                original_text = alarm.raw_text
                masked_text = (alarm.masked_text if hasattr(alarm, "masked_text") and alarm.masked_text 
                               else mask_sensitive_info(original_text))
                
                # 1.1 태스커 변수 필터링
                tasker_vars = ["%antext", "%antitle", "%ansubtext", "%ansender", "%evtprm", "%anapp", "%ancomm"]
                check_fields = [original_text, alarm.sender or "", alarm.app_title or ""]
                if any(tv in field for tv in tasker_vars for field in check_fields):
                    alarm.classification = "placeholder"
                    db.add(SpamAlarm(
                        raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                        app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                        conversation=alarm.conversation, classification="placeholder",
                        discard_reason="Tasker placeholder", rule_version=1
                    ))
                    # db.commit() 제거: 마지막에 일괄 커밋
                    processing_alarms.remove(alarm)
                    filtered_count += 1
                    filtered_reasons["플레이스홀더"] += 1
                    continue

                # 1.2 무시할 알림 (OTP 등)
                if should_ignore(original_text):
                    alarm.classification = "ignored"
                    db.add(SpamAlarm(
                        raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                        app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                        conversation=alarm.conversation, classification="ignored",
                        discard_reason="OTP/Security filter", rule_version=1
                    ))
                    # db.commit() 제거
                    processing_alarms.remove(alarm)
                    filtered_count += 1
                    filtered_reasons["OTP/보안"] += 1
                    continue

                # 1.3 스팸 필터링
                full_check_text = _build_alarm_filter_text(
                    sender=alarm.sender,
                    app_name=alarm.app_name,
                    package=alarm.package,
                    app_title=alarm.app_title,
                    body=original_text,
                )
                full_check_text_llm = _build_alarm_filter_text(
                    sender=mask_sensitive_info(alarm.sender or ""),
                    app_name=alarm.app_name,
                    package=alarm.package,
                    app_title=mask_sensitive_info(alarm.app_title or ""),
                    body=masked_text,
                )
                
                is_spam_result = False
                discard_reason = ""
                classification = ""
                
                if not is_whitelisted(full_check_text):
                    if is_review_spam(full_check_text):
                        is_spam_result, classification, discard_reason = True, "review_spam", "Review/Rating request"
                    else:
                        is_it_spam, cls = is_spam(full_check_text, db)
                        if is_it_spam:
                            is_spam_result, classification, discard_reason = True, cls, "Spam rule match"
                        elif is_promo_spam(full_check_text, db):
                            is_spam_result, classification, discard_reason = True, "promo_rule", "Promotion rule match"
                        else:
                            is_it_spam_llm, cls = is_spam_llm(
                                full_check_text_llm,
                                model=summary_model,
                                **summary_llm_kwargs,
                            )
                            if is_it_spam_llm:
                                is_spam_result, classification, discard_reason = True, cls, "LLM spam classification"
                
                if is_spam_result:
                    alarm.classification = classification
                    db.add(SpamAlarm(
                        raw_text=alarm.raw_text, masked_text=masked_text, sender=alarm.sender,
                        app_name=alarm.app_name, package=alarm.package, app_title=alarm.app_title,
                        conversation=alarm.conversation, classification=classification,
                        discard_reason=discard_reason, rule_version=1
                    ))
                    # db.commit() 제거
                    processing_alarms.remove(alarm)
                    filtered_count += 1
                    filtered_reasons["광고/프로모션"] += 1
                    continue

                if alarm.sender:
                    senders.add(alarm.sender)

                # 2. 카드 승인 내역 처리
                card_info = parse_card_approval(original_text)
                if card_info:
                    category = "기타"
                    if nb_pipeline and card_info["merchant"]:
                        try: category = nb_pipeline.predict([card_info["merchant"]])[0]
                        except: pass
                    
                    db.add(Expense(
                        user_id=user.id, date=card_info["date"], amount=card_info["amount"],
                        merchant=card_info["merchant"], method=card_info["method"],
                        category=category, is_fixed=False
                    ))
                    alarm.classification = "rule"
                    # db.commit() 제거
                    processing_alarms.remove(alarm)
                    continue

                # 3. 요약 대상 알람 (루프 끝난 후 LLM 처리)
                # 상태는 아직 processing 유지
                to_summarize_alarms.append({
                    "text": masked_text,
                    "sender": mask_sensitive_info(alarm.sender) if alarm.sender else None,
                    "app_name": alarm.app_name,
                    "package": alarm.package,
                    "app_title": mask_sensitive_info(alarm.app_title) if alarm.app_title else None,
                    "conversation": mask_sensitive_info(alarm.conversation) if alarm.conversation else None,
                    "db_obj": alarm # 상태 업데이트를 위해 객체 참조 유지
                })
            except Exception as e:
                logger.error(f"Error processing individual alarm {alarm.id}: {e}")
                db.rollback()
                # 개별 알람 실패 시 다음 알람으로 진행 (해당 알람은 processing 상태 유지되어 finally에서 복구됨)

        # 4. 요약 전 배치 메일 카운트 알림 압축(최신 1건만 유지)
        if to_summarize_alarms:
            to_summarize_alarms, dropped_mail_batches = _collapse_mail_batch_notifications(to_summarize_alarms)
            if dropped_mail_batches:
                logger.info("Collapsed mail batch notifications: dropped=%s", len(dropped_mail_batches))
                for item in dropped_mail_batches:
                    db_obj = item.get("db_obj")
                    if not db_obj:
                        continue
                    db_obj.status = "processed"
                    db_obj.classification = "merged_mail_batch"
                    if db_obj in processing_alarms:
                        processing_alarms.remove(db_obj)
            # 실제 요약 대상으로 남은 sender만 헤더에 반영
            senders = {str(item["sender"]) for item in to_summarize_alarms if item.get("sender")}

        # 5. 요약 처리 (가계부 리포트 비활성화)
        random_payload = None
        if to_summarize_alarms:
            llm_summary = await summarize_with_llm(
                [a for a in to_summarize_alarms],
                model=summary_model,
                **summary_llm_kwargs,
            )
            if llm_summary:
                safe_summary = escape_html_preserve_urls(llm_summary)
                summaries.append("\n<b>[주요 알림 요약]</b>\n" + safe_summary)
                # 요약 성공 시에만 대상 알람들 완료 처리
                for item in to_summarize_alarms:
                    item["db_obj"].status = "processed"
                    item["db_obj"].classification = "llm"
                    if item["db_obj"] in processing_alarms:
                        processing_alarms.remove(item["db_obj"])
        else:
            random_payload = await generate_random_message_payload(
                model=random_model,
                **random_llm_kwargs,
            )
            if random_payload and random_payload.get("body"):
                summaries.append(escape_html_preserve_urls(random_payload["body"]))
        
        db.commit() # 요약 결과 최종 커밋

        # 6. 텔레그램 전송
        if summaries:
            if to_summarize_alarms:
                title = "알림 리포트"
            else:
                title = (random_payload or {}).get("title") or "오늘의 브리핑"
            safe_title = escape_html_preserve_urls(title)

            sender_info = f" ({', '.join(list(senders)[:3])}{'...' if len(senders) > 3 else ''})" if senders else ""
            header = f"<b>[{safe_title}]{sender_info}</b>\n\n"
            
            if filtered_count > 0 and to_summarize_alarms:
                details = [f"{r} {c}개" for r, c in filtered_reasons.items() if c > 0]
                if details: header += f"🗑️ <i>필터링됨: {', '.join(details)}</i>\n\n"
            
            summary_text = header + "\n".join(summaries)
            try:
                from ..llm.service import LLMService
                if LLMService._instance and LLMService._instance.last_used_paid():
                    summary_text = f"{LLMService._instance.telegram_paid_prefix()}{summary_text}"
            except: pass
            
            await send_telegram_message(summary_text)

    except Exception as e:
        logger.error(f"Global error in process_pending_alarms: {e}")
        db.rollback()
        raise
    finally:
        # 7. 복구: 여전히 processing 상태인 알람들(에러 등으로 누락된 것)을 다시 pending으로
        if processing_alarms:
            logger.info(f"Recovering {len(processing_alarms)} alarms back to pending")
            for alarm in processing_alarms:
                alarm.status = "pending"
            db.commit()
