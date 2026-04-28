import logging
import json
import traceback
import re
import os
from datetime import datetime, timedelta, timezone

class SensitiveDataFormatter(logging.Formatter):
    """
    민감 정보를 마스킹하는 전역 로깅 포맷터 (기본 텍스트용).
    """
    
    PATTERNS = [
        (r'sk-[a-zA-Z0-9]{20,}', 'sk-[MASKED]'),
        (r'https://api\.telegram\.org/bot[0-9]{6,12}:[a-zA-Z0-9_-]{20,}/', 'https://api.telegram.org/bot[TELEGRAM_TOKEN_MASKED]/'),
        (r'[0-9]{9,12}:[a-zA-Z0-9_-]{32,}', '[TELEGRAM_TOKEN_MASKED]'),
        (r'(?i)bearer\s+[a-zA-Z0-9.\-_]{20,}', 'Bearer [MASKED]'),
        (r'(?i)("api[-_]key"|"secret"|"token")\s*:\s*"[^"]{10,}"', r'\1: "[MASKED]"'),
        (r'(?i)(api[-_]key|secret|token)\s*[:=]\s*[a-zA-Z0-9]{10,}', r'\1: [MASKED]'),
        (r'://([^:]+):([^@]+)@', r'://\1:***@'),
    ]

    def _mask_message(self, msg: str) -> str:
        for pattern, replacement in self.PATTERNS:
            msg = re.sub(pattern, replacement, msg)
        return msg

    def format(self, record):
        msg = super().format(record)
        return self._mask_message(msg)

class JsonSensitiveFormatter(SensitiveDataFormatter):
    """
    JSON 형식으로 구조화된 로그를 출력하는 포맷터. (민감 정보 마스킹 포함)
    """
    def format(self, record):
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": self._mask_message(record.getMessage()),
        }
        
        # 추가 정보(extra) 포함
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            for key, value in record.extra.items():
                if key not in log_data:
                    log_data[key] = value
        
        # 예외 정보 포함
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)

def setup_global_logging(level=logging.INFO, log_file: str | None = None, use_json: bool = True):
    """애플리케이션 전역 로깅 설정을 초기화하고 포맷터를 적용한다."""
    if use_json:
        formatter = JsonSensitiveFormatter()
    else:
        formatter = SensitiveDataFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        try:
            handlers.append(logging.FileHandler(log_file, encoding='utf-8'))
        except (PermissionError, OSError):
            pass

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    
    for handler in handlers:
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    
    return root_logger
