# backend/services/alarm/llm_logic.py
# 420줄 alarm_service.py에서 추출한 LLM 로직
import logging
import os
import random
import re
from datetime import datetime
from typing import List, Optional

from .sanitizer import infer_source, sanitize_llm_output, clean_exaone_tokens
from ..prompt_loader import load_prompt
from ..llm_service import LLMService

logger = logging.getLogger(__name__)

# 2차 정제용 경량 LLM 서버 URL
LLM_LIGHT_BASE_URL = os.getenv("LLM_LIGHT_BASE_URL", "http://llama-server-light:8080")

# LLM 초안 디버그 로깅 (환경변수로 제어)
DEBUG_LLM_DRAFT = os.getenv("DEBUG_LLM_DRAFT", "0") == "1"
LLM_DRAFT_LOG_PATH = os.getenv(
    "LLM_DRAFT_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "../../data/llm_drafts.jsonl")
)
LLM_DRAFT_LOG_MAX_MB = int(os.getenv("LLM_DRAFT_LOG_MAX_MB", "10"))  # 10MB 기본

# 랜덤 메시지 카테고리 중복 방지용 (마지막 선택 카테고리)
_last_category = None

# Light LLM 클라이언트 재사용 (성능 개선)
_light_client = None
_light_model_id_cache = None

# LLM stop 토큰 (중복 방지)
STOP_TOKENS = ["Okay", "let me", "Let me", "I'll", "아하", "음,", "사용자가", "지시사항을", "지문을", "지시를", "알겠습니다", "확인했습니다"]



def _dump_llm_draft(tag: str, draft: str):
    """
    프롬프트/원문은 저장하지 않고, LLM 1차 출력(draft)만 파일로 남긴다.
    보안: 민감정보 노출 방지, 성능: 로테이션 지원
    """
    if not DEBUG_LLM_DRAFT:
        return
    if not draft:
        return

    try:
        from pathlib import Path
        import json
        
        p = Path(LLM_DRAFT_LOG_PATH).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)

        # 간단 로테이션: 파일이 너무 커지면 .1로 밀고 새로 시작
        if p.exists():
            size_mb = p.stat().st_size / (1024 * 1024)
            if size_mb >= LLM_DRAFT_LOG_MAX_MB:
                rotated = p.with_suffix(p.suffix + ".1")
                if rotated.exists():
                    rotated.unlink()
                p.rename(rotated)

        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tag": tag,
            "len": len(draft),
            "draft": draft,
        }

        # jsonl (한 줄에 한 건)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 파일 권한(리눅스): 600 권장
        try:
            os.chmod(str(p), 0o600)
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"Failed to dump llm draft: {e}")


def _clean_meta_headers(text: str) -> str:
    """
    LLM 출력에서 '주제:', '출력 예:', '출력:', 'Draft:' 같은 메타 헤더를 제거한다.
    경량 LLM이 정제에 실패했을 때의 안전망 역할.
    """
    if not text:
        return text
    
    # 제거할 패턴들 (대소문자 무시, 줄 시작에 위치)
    meta_patterns = [
        r'^\s*(주제|Topic|테마)[:\s]+.*?\n',  # 주제: 우주 -> 제거
        r'^\s*(출력\s*예?|Example\s*Output?|Output)[:\s]+.*?\n',  # 출력 예: -> 제거
        r'^\s*\[?Draft\]?[:\s]*',  # [Draft] or Draft: -> 제거
        r'^\s*---+\s*\n',  # 구분선 제거
    ]
    
    result = text
    for pattern in meta_patterns:
        result = re.sub(pattern, '', result, flags=re.IGNORECASE | re.MULTILINE)
    
    return result.strip()


def _get_light_client():
    """Light LLM httpx 클라이언트를 재사용한다 (성능 개선)."""
    global _light_client
    if _light_client is None:
        import httpx
        _light_client = httpx.Client(timeout=30)
    return _light_client


def _get_light_model_id() -> str:
    """Light LLM 서버의 모델 ID를 가져온다 (env 우선, /v1/models 조회 fallback)."""
    global _light_model_id_cache
    
    # 1. 환경변수 우선
    env_model = os.getenv("LLM_LIGHT_MODEL_ID")
    if env_model:
        return env_model
    
    # 2. 캐시 확인
    if _light_model_id_cache:
        return _light_model_id_cache
    
    # 3. /v1/models API 조회
    try:
        client = _get_light_client()
        url = f"{LLM_LIGHT_BASE_URL.rstrip('/')}/v1/models"
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
        items = data.get("data") or []
        if items and isinstance(items[0], dict):
            model_id = items[0].get("id", "Qwen3-0.6B")
            _light_model_id_cache = model_id
            logger.info(f"Light LLM model ID detected: {model_id}")
            return model_id
    except Exception as e:
        logger.warning(f"Failed to get light model id: {e}")
    
    # 4. 최종 폴백
    return "Qwen3-0.6B"


def _get_korean_ratio(text: str) -> float:
    """텍스트의 한국어 비율을 계산한다."""
    if not text:
        return 0
    import re
    korean_chars = len(re.findall(r'[가-힣]', text))
    meaningful_chars = len(re.findall(r'[가-힣a-zA-Z0-9]', text))
    if meaningful_chars == 0:
        return 0
    return korean_chars / meaningful_chars


def _generate_with_light_llm(messages: List[dict], max_tokens: int = 256, temperature: float = 0.3) -> str:
    """
    경량 LLM 서버 (Qwen3-0.6B)를 사용하여 텍스트를 생성한다.
    주로 2차 정제(refine) 용도로 사용한다.
    성능: httpx.Client 재사용, enable_thinking을 chat_template_kwargs로 전달
    """
    try:
        client = _get_light_client()
        url = f"{LLM_LIGHT_BASE_URL.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": _get_light_model_id(),
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": False},  # llama.cpp 서버 공식 방식
        }
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"Light LLM call failed, falling back to main LLM: {e}")
        # 폴백: 메인 LLM 서비스 사용
        llm_service = LLMService.get_instance()
        if llm_service.is_loaded():
            return llm_service.generate_chat(messages, max_tokens=max_tokens, temperature=temperature)
        return ""

async def summarize_with_llm(items: List[dict]) -> Optional[str]:
    """
    원격 LLM을 사용하여 여러 알림을 요약한다.
    items: [{"text": "...", "sender": "..."}, ...]
    알람이 없을 때는 LLM이 랜덤으로 재미있는 말을 한다.
    Returns: 요약 메시지, 또는 None (전송 스킵)
    """
    llm_service = LLMService.get_instance()
    
    if not llm_service.is_loaded():
        if not items:
            return "🤖 LLM 모델이 로드되지 않았습니다... 알람도 없고, 모델도 없네요 😅"
        return "\n".join([f"- [{item['sender']}] {item['text']}" for item in items])
    
    # 알람이 없을 때: 재미있는 말 하기 모드 (10분 간격으로만)
    if not items:
        current_minute = datetime.now().minute
        # 10분 간격이 아니면 조용히 스킵 (:00, :10, :20, :30, :40, :50만 전송)
        if current_minute % 10 != 0:
            logger.info("No alarms; skip random message (not 10-min interval)")
            return None  # 메시지 안 보냄
        
        # 매 시간 정각(:00)에 LLM 세션 리셋 (주제 집착 방지)
        if current_minute == 0:
            llm_service.reset_context()
            logger.info("Hourly LLM context reset performed.")
        
        # 카테고리와 형식을 완전 랜덤으로 선택 (다양성 확보)
        categories = [
            "우주/천문학 (행성, 블랙홀, 외계 생명체, 우주 탐사)",
            "물리학/화학 (양자역학, 상대성이론, 원소, 신기한 물질)",
            "생물학/자연 (동물, 식물, 미생물, 인체의 신비)",
            "역사/문화 (고대문명, 이상한 역사, 기묘한 법률, 잊혀진 발명품)",
            "기술/엔지니어링 (AI, 로봇, 미래기술, 발명 히스토리)",
            "수학/논리 (수학 퍼즐, 역설, 확률, 기하학)",
            "심리학/뇌과학 (인지편향, 심리실험, 착시, 기억)",
            "게임/e스포츠 (게임 트리비아, 프로게이머, 게임 역사)",
            "영화/드라마/음악 (비하인드, 이스터에그, 뮤지션 일화)",
            "언어유희/드립 (말장난, 아재개그, 수수께끼)",
            "음식/요리 (음식 역사, 이상한 음식, 요리 과학)",
            "지리/여행 (신기한 장소, 세계 기록, 자연 경관)",
        ]
        
        # 문장 시작 형식도 랜덤
        formats = [
            "질문형으로 시작해라 (예: '혹시 알아?' / '이거 들어봤어?')",
            "팩트 단언형으로 시작해라 (예: '사실...' / '진짜 신기한 건...')",
            "감탄형으로 시작해라 (예: '와!' / '헐!' / '대박!')",
            "수수께끼/퀴즈형으로 시작해라 (예: 'OO는 왜 OO일까?')",
            "뉴스속보형으로 시작해라 (예: '[속보]...')",
            "TMI형으로 시작해라 (예: '갑자기 생각난 건데...')",
        ]
        
        # 이전 카테고리와 중복되지 않도록 선택
        global _last_category
        available_categories = [c for c in categories if c != _last_category]
        forced_category = random.choice(available_categories)
        _last_category = forced_category  # 다음 호출시 중복 방지
        
        forced_format = random.choice(formats)
        
        # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
        prompt_content = load_prompt("random_topic", category=forced_category, format=forced_format)
        if not prompt_content:
            # 폴백: 파일이 없으면 기본 메시지
            return "🤔 오늘도 심심한 하루... 뭐 재미있는 거 없나?"
        
        messages = [
            {
                "role": "user",
                "content": prompt_content
            }
        ]
        
        for attempt in range(3):
            logger.info(f"Generating random wisdom (Attempt {attempt + 1}/3)...")
            result = llm_service.generate_chat(
                messages, 
                max_tokens=256, 
                temperature=0.8,
                stop=STOP_TOKENS
            )
            result = clean_exaone_tokens(result)
            # 보안: 초안만 파일로 저장 (환경변수 켜진 경우만), 로그에는 길이만
            _dump_llm_draft("random_wisdom_draft", result)
            logger.info(f"🔍 [Random Wisdom Draft] Attempt {attempt+1} generated (len={len(result)})")
            
            if not result or len(result.strip()) < 10:
                logger.warning(f"Attempt {attempt+1}: Generated message too short.")
                continue
                
            korean_ratio = _get_korean_ratio(result)
            
            # 한국어 비율이 낮거나 메타 문구가 포함되어 있으면 2차 정제 시도
            meta_patterns = ["아하", "음,", "사용자가", "let me", "I'll", "Okay", "알겠습니다", "지정된 주제", "시작하는 말"]
            needs_refine = korean_ratio < 0.6 or any(p.lower() in result.lower() for p in meta_patterns)
            
            final_result = result
            if needs_refine:
                refine_prompt = load_prompt("refine_random_wisdom", draft=result)
                if refine_prompt:
                    refine_messages = [{"role": "user", "content": refine_prompt}]
                    logger.info(f"✂️ Attempt {attempt+1}: Refining with Low-Temp (0.0)...")
                    refined_result = _generate_with_light_llm(refine_messages, max_tokens=256, temperature=0.0)
                    refined_result = clean_exaone_tokens(refined_result)
                    logger.info(f"✨ Attempt {attempt+1}: Refined Output: {refined_result}")
                    if refined_result and len(refined_result.strip()) > 10:
                        final_result = refined_result
            
            # 최종 한국어 비율 검증 (0.5 이상이어야 통과)
            final_ratio = _get_korean_ratio(final_result)
            if final_ratio >= 0.5:
                # 마지막 안전망: 메타 헤더 정규표현식으로 제거
                final_result = _clean_meta_headers(final_result)
                logger.info(f"✅ Attempt {attempt+1} Success! Korean Ratio: {final_ratio:.2f}")
                return final_result
            else:
                logger.warning(f"❌ Attempt {attempt+1} Failed. Korean Ratio: {final_ratio:.2f}. Retrying...")

        logger.error("All 3 attempts to generate clean random wisdom failed.")
        return None

    
    # 알림 목록 구성 (발신자 포함, 중복 제거 로직 강화)
    notification_list = []
    seen_notifications = set()  # (source, text) 중복 체크용
    
    for item in items:
        source = infer_source(item)
        title = item.get('app_title') or ""
        conv = item.get('conversation') or ""
        text = (item.get('text') or "").strip()
        
        # Tasker 변수가 치환 안 된 경우 제외
        if title.startswith('%'): title = ""
        if conv.startswith('%'): conv = ""
        
        # 중복 체크 키 (출처와 본문이 같으면 중복으로 간주)
        identifier = (source, text)
        if identifier in seen_notifications:
            continue
        seen_notifications.add(identifier)
        
        context = f"[앱: {source}]"
        if title: context += f" 제목: {title}"
        if conv: context += f" 발신/대화: {conv}"
        
        notification_list.append(f"- {context} 본문: {text}")

    # 외부 프롬프트 파일에서 로드 (핫 리로드 지원)
    notifications_str = "\n".join(notification_list)
    prompt_content = load_prompt("alarm_summary", notifications=notifications_str)
    
    if not prompt_content:
        # 폴백: 파일이 없으면 기본 포맷 사용
        prompt_content = f"아래 스마트폰 알림들을 한국어로 요약해줘:\n{notifications_str}"
    
    messages = [
        {
            "role": "user",
            "content": prompt_content
        }
    ]
    
    # 보안: 프롬프트는 로그에 찍지 않음 (민감정보 노출 방지)
    total_prompt_len = sum(len(m['content']) for m in messages)
    logger.info(f"LLM Prompt total length: {total_prompt_len} characters")
    result = llm_service.generate_chat(messages, max_tokens=512)
    # 보안: 초안만 파일로 저장 (환경변수 켜진 경우만), 로그에는 길이만
    _dump_llm_draft("alarm_summary_draft", result)
    logger.info(f"LLM draft generated (len={len(result or '')})")
    
    # 1단계: 환각 제거 및 특수 토큰 제거
    result = sanitize_llm_output(items, result)
    result = clean_exaone_tokens(result)
    
    # 2단계: 경량 LLM으로 사고과정/메타 설명 정제 (Qwen3-0.6B)
    if result and result.strip():
        refine_prompt = load_prompt("refine_alarm_summary", draft=result)
        if refine_prompt:
            refine_messages = [{"role": "user", "content": refine_prompt}]
            refined_result = _generate_with_light_llm(refine_messages, max_tokens=256, temperature=0.3)
            refined_result = clean_exaone_tokens(refined_result)
            # 보안: 정제 결과 파일로 저장
            _dump_llm_draft("alarm_summary_refined", refined_result)
            logger.info(f"LLM refined by Light LLM (len={len(refined_result)})")
            if refined_result and refined_result.strip():
                result = refined_result
    
    return result


async def summarize_expenses_with_llm(expenses: List[dict]) -> str:
    """
    가계부 내역(결제 승인)을 분석하여 짧은 코멘트를 생성한다.
    """
    if not expenses:
        return ""
    
    llm_service = LLMService.get_instance()
    
    if not llm_service.is_loaded():
        return ""

    expense_list = []
    for e in expenses:
        expense_list.append(f"- {e['merchant']}: {abs(e['amount']):,.0f}원 ({e['category']})")

    messages = [
        {"role": "user", "content": f"""You are a financial assistant. Analyze the following payment records and provide a short, witty one-sentence analysis in Korean about the user's spending patterns or characteristics.
Start directly with the result without any introductory phrases or greetings.

[Payments]
{chr(10).join(expense_list)}"""}
    ]
    result = llm_service.generate_chat(messages, max_tokens=256)
    return clean_exaone_tokens(result)


async def generate_daily_catchphrases() -> bool:
    """
    매일 또는 주기적으로 e스포츠 전용 캐치프레이즈를 생성하여 파일로 저장한다.
    """
    import json
    import os
    
    llm_service = LLMService.get_instance()
    if not llm_service.is_loaded():
        logger.warning("LLM model NOT loaded. Cannot generate catchphrases.")
        return False

    games = ["리그 오브 레전드", "발로란트"]
    results = {"LoL": [], "Valorant": []}
    
    for game in games:
        prompt = load_prompt("generate_catchphrases", game=game)
        if not prompt:
            continue
            
        messages = [{"role": "user", "content": prompt}]
        raw_result = llm_service.generate_chat(messages, max_tokens=256, temperature=0.8)
        raw_result = clean_exaone_tokens(raw_result)
        
        # 줄 단위로 분리하여 유효한 멘트만 추출
        lines = [line.strip().lstrip("-*•123456789. ").strip() for line in raw_result.split("\n") if line.strip()]
        
        # 종목 매칭
        key = "LoL" if "리그" in game else "Valorant"
        results[key] = lines[:10] # 최대 10개 유지
        
    # 파일 저장 (V2 버전으로 저장하여 기존 match_notifier와 호환성 유지 또는 전환)
    save_path = os.path.join(os.path.dirname(__file__), "../../data/esports_catchphrases_v2.json")
    try:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        logger.info(f"Daily catchphrases generated and saved to {save_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save generated catchphrases: {e}")
        return False
