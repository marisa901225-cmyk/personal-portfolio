import re
import html
import logging
import urllib.parse
from typing import List

logger = logging.getLogger(__name__)

# URL 정규화용 구두점
_TRAILING_PUNCT = '.,;:!?)]}>"\''


def _strip_after_last_closing_think_tag(text: str) -> str:
    """
    여러 닫는 태그가 섞인 경우 "가장 마지막에 등장한 닫는 태그" 뒤만 남긴다.
    """
    closing_tags = ['</think>', '</reasoning>', '</thought>']
    low = text.lower()

    last_pos = -1
    last_tag = None
    for tag in closing_tags:
        pos = low.rfind(tag)
        if pos > last_pos:
            last_pos = pos
            last_tag = tag

    if last_pos != -1 and last_tag is not None:
        cut = last_pos + len(last_tag)
        logger.info(f"[COT REMOVAL] Found closing tag {last_tag}, removed {cut} chars before it")
        return text[cut:].strip()

    return text


def normalize_url(u: str) -> str:
    """
    URL을 정규화하여 문장부호 문제를 해결한다.
    """
    # 문장 끝에 붙은 구두점 제거
    u = u.rstrip(_TRAILING_PUNCT)

    try:
        p = urllib.parse.urlparse(u)
        scheme = (p.scheme or "").lower()
        netloc = (p.netloc or "").lower()

        # 기본 포트 정리
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        if netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]

        path = p.path or ""
        return urllib.parse.urlunparse((scheme, netloc, path, "", p.query or "", ""))
    except Exception:
        return u


def clean_exaone_tokens(text: str) -> str:
    """
    EXAONE, Qwen 등 LLM 특수 토큰과 Chain of Thought (COT) 추론 과정을 제거한다.
    """
    if not text:
        return ""
    
    # 1. COT 태그 제거 (완전한 쌍)
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<reasoning>.*?</reasoning>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. 닫는 태그만 있는 경우 - 가장 마지막에 등장한 닫는 태그 뒤만 남기기 (버그 수정)
    text = _strip_after_last_closing_think_tag(text)
    
    # 3. 시작 태그만 있는 경우 (EOT 전까지 모두 제거)
    text = re.sub(r'<think>.*', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<reasoning>.*', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<thought>.*', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # 4. EXAONE 특수 토큰: [|user|], [|assistant|] 등
    text = re.sub(r'\[\|[a-z_]+\|\]', '', text, flags=re.IGNORECASE)
    
    # 5. Qwen/기타 <|...|> 스타일 토큰
    text = re.sub(r'<\|.*?\|>', '', text)
    
    # 6. COT 전처리: 첫 번째 bullet point 전까지 사고 과정 제거
    lines = text.split('\n')
    content_start_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(('-', '•', '*')) or re.match(r'^\d+\.', stripped):
            content_start_idx = i
            break
        if any(marker in stripped for marker in ['💳', '💰', '📱', '🔔', '주요 알림', '결제', '배달', '카카오톡']):
            content_start_idx = i
            break
    
    if content_start_idx > 0:
        potential_cot = '\n'.join(lines[:content_start_idx]).lower()
        thinking_keywords = ['생각', '분석', 'hmm', 'let me', '확인', '보면', '같아', '같네', '것 같', '추측', '판단', '음...', '사용자가']
        if any(kw in potential_cot for kw in thinking_keywords):
            text = '\n'.join(lines[content_start_idx:])
            logger.info(f"[COT REMOVAL] Removed {content_start_idx} lines of suspected thinking process")
    
    # 7. 연속된 빈 줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text.strip()


def infer_source(item: dict) -> str:
    """
    패키지명, 앱 이름, 텍스트 등을 기반으로 서비스 출처를 추론한다.
    """
    pkg = (item.get("package") or "").lower()
    app = (item.get("app_name") or "")
    app_lower = app.lower()
    text = (item.get("text") or "").lower()

    if "munpia" in pkg or "문피아" in app_lower or "munpia.com" in text:
        return "문피아"
    if "credo" in pkg or "credo" in app_lower or "credo.game" in text:
        return "크레도"
    if "telegram" in pkg or "텔레그램" in app_lower:
        return "텔레그램"
    if "kakaotalk" in pkg or "카카오톡" in app_lower:
        return "카카오톡"
    
    # 폴백: app_name이 있으면 반환, 없으면 sender, 둘 다 없으면 "기타"
    if app:
        return app
    sender = (item.get("sender") or "").strip()
    if sender:
        return sender
    return "기타"


def escape_html_preserve_urls(text: str) -> str:
    """
    URL도 최소 escape 처리하여 안전하게 HTML 출력.
    """
    url_pattern = r'https?://[^\s\)\]<>"]+'
    parts = []
    last = 0
    for m in re.finditer(url_pattern, text):
        s, e = m.span()
        parts.append(html.escape(text[last:s], quote=True))
        parts.append(html.escape(text[s:e], quote=True))  # URL도 escape
        last = e
    parts.append(html.escape(text[last:], quote=True))
    return "".join(parts)


def sanitize_llm_output(original_items: List[dict], llm_output: str) -> str:
    """
    환각 가능성이 있는 줄/URL을 "제거/정정"한다.
    """
    def extract_all_text_for_urls(item: dict) -> str:
        fields = [
            item.get("app_name", ""),
            item.get("sender", ""),
            item.get("package", ""),
            item.get("app_title", ""),
            item.get("conversation", ""),
            item.get("text", ""),
        ]
        return " ".join([f for f in fields if f])

    def extract_body_text(item: dict) -> str:
        fields = [
            item.get("app_title", ""),
            item.get("conversation", ""),
            item.get("text", ""),
        ]
        return " ".join([f for f in fields if f])

    original_text_for_urls = " ".join(extract_all_text_for_urls(it) for it in original_items)
    original_body_text = " ".join(extract_body_text(it) for it in original_items)

    url_pattern = r'https?://[^\s\)\]<>"]+' 
    original_urls = set(re.findall(url_pattern, original_text_for_urls))
    
    # URL 정규화 세트 생성 (문장부호 문제 해결)
    original_urls_norm = set(normalize_url(u) for u in original_urls)
    
    # 원본 도메인 세트 (정규화 기반)
    original_domains = set()
    for url in original_urls:
        try:
            d = urllib.parse.urlparse(normalize_url(url)).netloc.lower()
            if d:
                original_domains.add(d)
        except:
            pass

    original_apps = set()
    original_senders = set()  # 원본 발신자 이름 세트
    for it in original_items:
        original_apps.add(infer_source(it))
        a = (it.get("app_name") or it.get("sender") or "").strip()
        if a:
            original_apps.add(a)
        # 발신자 이름 수집 (마스킹 포함)
        sender = (it.get("sender") or "").strip()
        if sender:
            original_senders.add(sender)
            # 마스킹된 이름도 추가 (예: "홍길동" -> "홍*동")
            if len(sender) >= 2:
                original_senders.add(sender[0] + "*" + sender[2:] if len(sender) > 2 else sender[0] + "*")
        # text에서 발신자 이름 추출 (conversation 포함)
        for field in ['text', 'conversation', 'app_title']:
            text = (it.get(field) or "")
            # "XXX님" 패턴 추출
            name_matches = re.findall(r'([가-힣A-Za-z0-9_*]{1,10})님', text)
            for name in name_matches:
                original_senders.add(name)

    def _extract_strong_tokens(text: str) -> set[str]:
        """
        입력 알림 본문에서만 뽑은 '근거 토큰' (환각 방지용).
        - 길이>=4 또는 숫자/* 포함 토큰만 사용 (너무 흔한 단어로 인한 오탐 감소)
        """
        tokens = set()
        for tok in re.findall(r'[가-힣A-Za-z0-9_*]{2,}', text or ""):
            if len(tok) >= 4 or any(ch.isdigit() for ch in tok) or "*" in tok:
                tokens.add(tok)
        return tokens

    original_strong_tokens = _extract_strong_tokens(original_body_text)

    # 1) 라인 단위 필터링
    lines = llm_output.splitlines()
    kept = []
    dropped_reasons = []
    
    for line in lines:
        if not line.strip():
            continue
            
        line_urls = re.findall(url_pattern, line)
        bad_domain = False
        for u in line_urls:
            try:
                d = urllib.parse.urlparse(normalize_url(u)).netloc.lower()
                if d and d not in original_domains:
                    bad_domain = True
                    break
            except:
                pass
        if bad_domain:
            dropped_reasons.append(f"drop(bad domain): {line[:50]}...")
            continue

        # 의심 서비스명 제거
        suspicious_service_tokens = ["크레도", "Credo", "CREDO"]
        has_suspicious = any(tok in line for tok in suspicious_service_tokens)
        if has_suspicious:
            if not any("크레도" in a or "credo" in a.lower() for a in original_apps):
                dropped_reasons.append(f"drop(hallucinated service): {line[:50]}...")
                continue

        # 발신자 이름 환각 검증 (예: "홍길동님이" 패턴)
        hallucinated_sender = False
        sender_pattern = re.findall(r'([가-힣A-Za-z0-9_*]{1,10})님이', line)
        for sender_name in sender_pattern:
            # 원본 발신자 목록에 없으면 환각으로 판단
            if sender_name and sender_name not in original_senders:
                # 부분 일치도 허용 (마스킹된 이름)
                partial_match = any(sender_name in s or s in sender_name for s in original_senders if len(s) >= 2)
                if not partial_match:
                    dropped_reasons.append(f"drop(hallucinated sender '{sender_name}'): {line[:50]}...")
                    hallucinated_sender = True
                    break
        if hallucinated_sender:
            continue

        # bullet/번호 뒤에 붙는 "[서비스]" 라벨이 원본에 없으면 제거
        label_match = re.match(r'^\s*(?:[-•*]|\d+\.)\s*(?:\d+\.\s*)?\[([^\]]{1,30})\]', line.strip())
        if label_match:
            label = label_match.group(1).strip()
            if label and (label not in original_apps) and (label not in original_senders):
                dropped_reasons.append(f"drop(hallucinated app label '{label}'): {line[:50]}...")
                continue

        # 본문 기반 '근거 토큰'이 전혀 없으면 환각으로 간주 (단, 원본 발신자/URL 포함 시 예외)
        if original_strong_tokens:
            has_sender = any(s and s in line for s in original_senders)
            has_original_url = any(normalize_url(u) in original_urls_norm for u in re.findall(url_pattern, line))
            if not has_sender and not has_original_url:
                line_tokens = _extract_strong_tokens(line)
                if not (line_tokens & original_strong_tokens):
                    dropped_reasons.append(f"drop(ungrounded): {line[:50]}...")
                    continue

        # "왜냐하면/비커즈/because" - 드랍 대신 치환으로 변경
        line_cleaned = line
        annoying_phrases = ["왜냐하면", "비커즈", "because", "Because", "왜냐면"]
        for phrase in annoying_phrases:
            if phrase in line_cleaned:
                line_cleaned = line_cleaned.replace(phrase, "").strip()

        # 메타 문장/설명 제거 (예: "The ... notification fits under ...")
        meta_patterns = [
            r'fits under', r'belongs to', r'classified as', r'notification type', 
            r'요약하자면', r'알려드립니다', r'포함시켰습니다', r'해당합니다'
        ]
        if any(re.search(p, line_cleaned, re.I) for p in meta_patterns):
            dropped_reasons.append(f"drop(meta/explanation): {line_cleaned[:50]}...")
            continue

        # 한글 비중 검사 (URL 제외하고 한글이 너무 적으면 메타 설명일 확률 높음)
        text_only = re.sub(url_pattern, '', line_cleaned)
        text_only = re.sub(r'[^\w\s]', '', text_only) # 특수문자 제거
        if text_only.strip():
            korean_chars = len(re.findall(r'[가-힣]', text_only))
            total_chars = len(text_only.strip())
            # 한글이 20% 미만이고 영어가 주인 경우 (요약문이 아닐 확률이 높음)
            if korean_chars / total_chars < 0.2 and any(c.isalpha() for c in text_only):
                dropped_reasons.append(f"drop(too much english/meta): {line_cleaned[:50]}...")
                continue

        # URL 개별 제거 (정규화 기반 비교)
        line_output_urls = re.findall(url_pattern, line_cleaned)
        for url in line_output_urls:
            if normalize_url(url) not in original_urls_norm:
                line_cleaned = line_cleaned.replace(url, "")
        
        if line_cleaned.strip():
            kept.append(line_cleaned)

    result = "\n".join(kept).strip()

    if dropped_reasons:
        logger.warning("LLM hallucination lines removed: %s", dropped_reasons[:5])

    return result
