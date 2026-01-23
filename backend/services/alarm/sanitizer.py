import re
import html
import logging
import urllib.parse
from typing import List, Set

logger = logging.getLogger(__name__)

# 정규식 패턴 상수
URL_PATTERN = re.compile(r'https?://[^\s\)\]<>"]+')
TOKEN_PATTERN = re.compile(r'[가-힣A-Za-z0-9_*]+')
LABEL_PATTERN = re.compile(r'^[-•*]\s*\[?([^\]]+)\]?:?')
MAX_DROP_REASONS = 10
SUMMARY_KEYWORDS = ['결제', '송금', '입금', '출금', '알림', '메시지', '카톡', '문자', '배송', '택배', '배달', '업데이트', '건', '도착', '완료']

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
        logger.debug("[COT REMOVAL] Found closing tag %s, removed %d chars before it", last_tag, cut)
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
    
    # 0. 한글/영문 COT 시작 패턴 제거
    # 문장 시작 부분의 사고과정 패턴을 regex로 잘라냄
    cot_start_patterns = [
        # 한글 패턴
        r'^아하[,.]?\s*',
        r'^음[,.]?\s*',
        r'^흠[,.]?\s*',
        r'^사용자가\s+[가-힣]+\s+대로[^.]*[.]\s*',  # "사용자가 요구한 대로~." 패턴
        r'^[가-힣]+해야겠[어다네][.!]?\s*',  # "~해야겠어." 패턴
        r'^[가-힣]+할게[.!]?\s*',  # "~할게." 패턴
        r'^이런\s*식으로[^.]*[.]\s*',  # "이런 식으로~." 패턴
        r'^[가-힣]+말이지[.!]?\s*',  # "~말이지." 패턴
        r'^지문을\s+[가-힣]+\s+이해했어[!.]?\s*',  # "지문을 잘 이해했어." 패턴
        r'^알겠습니다[!.]?\s*',  # "알겠습니다." 패턴
        # 영문 패턴 (LLM이 영어로 CoT 시작하는 경우)
        r'^Okay[,.]?\s+let\s+me\s+[^\n]{0,100}[.\n]\s*',  # "Okay, let me approach this..." 
        r'^Let\s+me\s+[^\n]{0,80}[.\n]\s*',  # "Let me think about..."
        r"^I'll\s+[^\n]{0,80}[.\n]\s*",  # "I'll analyze this..."
        r'^Here\s+is\s+[^\n]{0,50}:\s*',  # "Here is the result:"
        r'^Sure[,!]?\s*[^\n]{0,80}[.\n]\s*',  # "Sure, here's..."
    ]
    # 오탐 방지: MULTILINE 제거 (텍스트 맨 앞에서만 1회 제거)
    for pattern in cot_start_patterns:
        text_new = re.sub(pattern, '', text, count=1, flags=re.IGNORECASE)
        if text_new != text:
            text = text_new
    
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
            logger.debug("[COT REMOVAL] Removed %d lines of suspected thinking process", content_start_idx)
    
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
    parts = []
    last = 0
    for m in URL_PATTERN.finditer(text):
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

    COMMON_PREFIXES = ('배달', '완료', '알림', '메시지', '확인', '오늘', '내일', '어제', '전송')
    def _extract_strong_tokens(text: str) -> Set[str]:
        """
        텍스트에서 의미 있는 '강한 토큰' (주로 명사, 고유대명사 등) 추출.
        한글은 2글자 이상, 영어/숫자는 3글자 이상.
        """
        if not text:
            return set()
        
        # URL 제거
        text = re.sub(r'https?://[^\s]+', ' ', text)
        
        # 한글: 2자 이상
        ko_tokens = set(re.findall(r'[가-힣]{2,}', text))
        # 영무/숫자: 3자 이상
        en_tokens = set(re.findall(r'[a-zA-Z0-9]{3,}', text))
        
        # 흔한 단어(COMMON_PREFIXES)는 근거에서 제외
        filtered_tokens = {tok for tok in (ko_tokens | en_tokens) if not tok.startswith(COMMON_PREFIXES)}
        
        return filtered_tokens

    original_strong_tokens = _extract_strong_tokens(original_body_text)

    # 1) 라인 단위 필터링
    lines = llm_output.splitlines()
    kept = []
    dropped_reasons = []
    
    for line in lines:
        if not line.strip():
            continue
            
        line_urls = URL_PATTERN.findall(line)
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
            if len(dropped_reasons) < MAX_DROP_REASONS:
                dropped_reasons.append(f"drop(bad domain): {line[:50]}...")
            continue

        # 의심 서비스명 제거
        suspicious_service_tokens = ["크레도", "Credo", "CREDO"]
        has_suspicious = any(tok in line for tok in suspicious_service_tokens)
        if has_suspicious:
            if not any("크레도" in a or "credo" in a.lower() for a in original_apps):
                if len(dropped_reasons) < MAX_DROP_REASONS:
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

        # bullet/번호 뒤에 붙는 "[서비스]" 라벨이 원본에 부분적으로라도 포함되어 있으면 유지
        label_match = LABEL_PATTERN.match(line.strip())
        if label_match:
            label = label_match.group(1).strip()
            if label:
                # 정확히 일치하거나, 원본 앱/발신자 이름에 포함되어 있거나, 포함하고 있는 경우 모두 허용
                is_valid_label = (
                    label in original_apps or 
                    label in original_senders or
                    any(label in app for app in original_apps) or
                    any(app in label for app in original_apps) or
                    any(label in s for s in original_senders) or
                    any(s in label for s in original_senders)
                )
                if not is_valid_label:
                    if len(dropped_reasons) < MAX_DROP_REASONS:
                        dropped_reasons.append(f"drop(hallucinated app label '{label}'): {line[:50]}...")
                    continue

        # 본문 기반 '근거 토큰'이 전혀 없으면 환각으로 간주
        if original_strong_tokens:
            has_sender = any(s and s.lower() in line.lower() for s in original_senders)
            has_original_url = any(normalize_url(u) in original_urls_norm for u in URL_PATTERN.findall(line))
            has_summary_keyword = any(k in line for k in SUMMARY_KEYWORDS)
            
            if not has_sender and not has_original_url and not has_summary_keyword:
                line_tokens = _extract_strong_tokens(line)
                # 교집합이 없더라도, line_tokens 중 하나라도 원본 텍스트 전체에 포함되어 있는지 확인 (부분 일치 허용)
                # 또는 원본 토큰 중 하나가 line에 포함되어 있는지 확인
                is_grounded = (
                    bool(line_tokens & original_strong_tokens) or
                    any(token in original_body_text for token in line_tokens if len(token) >= 2) or
                    any(token in line for token in original_strong_tokens if len(token) >= 2)
                )
                
                if not is_grounded:
                    if len(dropped_reasons) < MAX_DROP_REASONS:
                        dropped_reasons.append(f"drop(ungrounded): {line[:50]}...")
                    continue

        # "왜냐하면/비커즈/because" - 드랍 대신 치환으로 변경
        line_cleaned = line
        annoying_phrases = ["왜냐하면", "비커즈", "because", "Because", "왜냐면"]
        for phrase in annoying_phrases:
            if phrase in line_cleaned:
                line_cleaned = line_cleaned.replace(phrase, "").strip()

        # 메타 문장/설명 제거 (사족 필터링)
        meta_patterns = [
            r'fits under', r'belongs to', r'classified as', r'notification type', 
            r'요약하자면', r'포함시켰습니다',
            # LLM 사고과정 패턴 (출력에 사고과정 포함된 경우)
            r'요약\s*가능', r'같은\s*이벤트니까', r'처리했다는\s*건',
            r'통합하여', r'하나로\s*묶', r'정리하면', r'분석하면',
        ]
        if any(re.search(p, line_cleaned, re.I) for p in meta_patterns):
            if len(dropped_reasons) < MAX_DROP_REASONS:
                dropped_reasons.append(f"drop(meta/explanation): {line_cleaned[:50]}...")
            continue

        # 한글 비중 검사 (URL 제외하고 한글이 너무 적으면 메타 설명일 확률 높음)
        text_only = URL_PATTERN.sub('', line_cleaned)
        text_only = re.sub(r'[^\w\s]', '', text_only) # 특수문자 제거
        if text_only.strip():
            korean_chars = len(re.findall(r'[가-힣]', text_only))
            total_chars = len(text_only.strip())
            # 한글이 20% 미만이고 영어가 주인 경우 (요약문이 아닐 확률이 높음)
            if korean_chars / total_chars < 0.2 and any(c.isalpha() for c in text_only):
                if len(dropped_reasons) < MAX_DROP_REASONS:
                    dropped_reasons.append(f"drop(too much english/meta): {line_cleaned[:50]}...")
                continue

        # URL 개별 제거 (정규화 기반 비교)
        line_output_urls = URL_PATTERN.findall(line_cleaned)
        for url in line_output_urls:
            if normalize_url(url) not in original_urls_norm:
                line_cleaned = line_cleaned.replace(url, "")
        
        if line_cleaned.strip():
            kept.append(line_cleaned)

    result = "\n".join(kept).strip()

    if dropped_reasons:
        logger.warning("LLM hallucination lines removed: %s", dropped_reasons[:5])

    return result
