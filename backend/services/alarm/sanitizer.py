import re
import logging
import urllib.parse
from typing import List

logger = logging.getLogger(__name__)

def infer_source(item: dict) -> str:
    """
    패키지명, 앱 이름, 텍스트 등을 기반으로 서비스 출처를 추론한다.
    """
    pkg = (item.get("package") or "").lower()
    app = (item.get("app_name") or "").lower()
    text = (item.get("text") or "").lower()

    if "munpia" in pkg or "문피아" in app or "munpia.com" in text:
        return "문피아"
    if "credo" in pkg or "credo" in app or "credo.game" in text:
        return "크레도"
    if "telegram" in pkg or "텔레그램" in app:
        return "텔레그램"
    if "kakaotalk" in pkg or "카카오톡" in app:
        return "카카오톡"
    
    return app or "기타"

def escape_html_preserve_urls(text: str) -> str:
    """
    URL은 그대로 유지하고 나머지 텍스트만 HTML 이스케이프한다.
    """
    import html
    url_pattern = r'https?://[^\s\)\]<>"]+'
    parts = []
    last = 0
    for m in re.finditer(url_pattern, text):
        s, e = m.span()
        parts.append(html.escape(text[last:s]))
        parts.append(text[s:e])
        last = e
    parts.append(html.escape(text[last:]))
    return "".join(parts)

def sanitize_llm_output(original_items: List[dict], llm_output: str) -> str:
    """
    환각 가능성이 있는 줄/URL을 "제거/정정"한다.
    """
    def extract_all_text(item: dict) -> str:
        fields = [
            item.get("app_name", ""),
            item.get("sender", ""),
            item.get("package", ""),
            item.get("app_title", ""),
            item.get("conversation", ""),
            item.get("text", ""),
        ]
        return " ".join([f for f in fields if f])

    original_text = " ".join(extract_all_text(it) for it in original_items)

    url_pattern = r'https?://[^\s\)\]<>"]+'
    original_urls = set(re.findall(url_pattern, original_text))
    
    # 원본 도메인 세트
    original_domains = set()
    for url in original_urls:
        try:
            original_domains.add(urllib.parse.urlparse(url).netloc.lower())
        except:
            pass

    original_apps = set()
    for it in original_items:
        original_apps.add(infer_source(it))
        a = (it.get("app_name") or it.get("sender") or "").strip()
        if a:
            original_apps.add(a)

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
                d = urllib.parse.urlparse(u).netloc.lower()
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

        # "왜냐하면/비커즈/because" 집착 방지 필터
        annoying_phrases = ["왜냐하면", "비커즈", "because", "Because", "왜냐면"]
        if any(phrase in line for phrase in annoying_phrases):
            dropped_reasons.append(f"drop(annoying phrase): {line[:50]}...")
            continue

        # URL 개별 제거
        line_cleaned = line
        line_output_urls = re.findall(url_pattern, line)
        for url in line_output_urls:
            if url not in original_urls:
                line_cleaned = line_cleaned.replace(url, "")
        
        if line_cleaned.strip():
            kept.append(line_cleaned)

    result = "\n".join(kept).strip()

    if dropped_reasons:
        logger.warning("LLM hallucination lines removed: %s", dropped_reasons[:5])

    return result
