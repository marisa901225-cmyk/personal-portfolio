• 0. 전체 결론 요약

     현재 라우팅 구조는 대부분 토큰 보호가 되어 있지만, 인증이 실패‑오픈(fail‑open)인 구조와 무인증 메모리 API, 텔레그램 웹훅의 선택적 시크릿이 합쳐져 외부 노출 시 바로 악용될 수 있는 구멍이 있습니다. 또한 설정 API에서 KIS 비밀키가 그대로 내려가고, 업로드/LLM/뉴스 엔드포인트의 보호(크기 제한·레이트리

     밋·오류 노출)가 부족합니다.

  1. 우선순위 Top 10 이슈 표



  | Severity | 제목 | 악용 난이도 | 영향 | 위치(파일/함수) | 빠른 대응책 |

  |---|---|---|---|---|---|

  | Critical | API_TOKEN 미설정 시 인증 무효(FAIL‑OPEN) | 낮음 | 전체 API 무단 접근 | core/auth.py:17 | 토큰 미설정 시 503/부팅 실패 |

  | High | Memories API 무인증 접근 가능 | 낮음 | 메모리 데이터 읽기/삭제/변조 | routers/memories.py:14 | Depends(verify_api_token) 추가 |

  | High | Telegram 웹훅 시크릿 미설정 시 명령 실행 | 낮음 | 스팸 규칙 변경/모델 재학습/알림 남발 | routers/telegram_webhook.py:17 | 시크릿/채팅ID 필수화 |

  | High | Settings API가 KIS 비밀키 노출 | 낮음 | 자격증명 유출 | core/schemas.py:153, services/settings_service.py:143 | 응답 마스킹/제외 |

  | Medium | 업로드 크기 제한 없음(메모리/디스크 DoS) | 낮음 | 서비스 장애 | routers/expense_upload.py:50, services/import_service.py:40 | 업로드 상한 + 스트리밍 |

  | Medium | 에러 상세 메시지/예외 노출 | 낮음 | 내부 경로·업스트림 응답 노출 | routers/expense_upload.py:81, routers/report_ai.py:56 | 클라이언트에는 일반 메시지 |

  | Medium | 고비용 엔드포인트 레이트리밋 부재 | 낮음 | 비용 폭증/DoS | routers/news.py:11, routers/report_ai.py:42, routers/memory_chat.py:373 | 간단한 토큰/IP 기반 제한 |

  | Low | 토큰 비교 상수시간 아님 + 무차별 대입 방어 없음 | 중간 | 토큰 추측·타이밍 | core/auth.py:26 | hmac.compare_digest + 제한 |

  | Medium | 백업 암호화 실패 시 평문 ZIP 폴백 | 낮음 | 백업 유출 위험 | services/backup.py:45 | 암호화 실패 시 실패 처리 |

  | Medium | KIS 자격증명 DB 평문 저장 | 낮음 | DB/백업 유출 시 키 탈취 | core/models.py:186, services/kis_settings.py:24 | 환경변수/암호화 저장 |



  2. 상세 이슈(각 이슈당)



  이슈 1. API_TOKEN 미설정 시 인증 무효(FAIL‑OPEN)



  - 증상/설명: API_TOKEN이 없으면 모든 보호된 라우터가 인증 없이 통과됩니다. 실제 배포에서 환경변수 누락 시 전체 API가 공개됩니다.

  - 근거: core/auth.py:17, core/auth.py:23

  - 악용 시나리오: (가정) 외부에 노출된 서버에서 API_TOKEN이 빠진 채 실행 → 누구나 데이터 조회/수정 가능.

  - 권장 수정: 디버그/개발 모드가 아닌 경우 토큰 미설정 시 요청 차단(또는 부팅 실패).

  - 패치 제안:



  diff --git a/core/auth.py b/core/auth.py

  index 2d8c1a1..9c7b4b2 100644

  --- a/core/auth.py

  +++ b/core/auth.py

  @@ -1,7 +1,9 @@

   from __future__ import annotations

   from fastapi import Header, HTTPException

   from .config import settings

  +import hmac



   import os



   API_TOKEN = settings.api_token

  +ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").lower() in ("1", "true", "yes")

  @@ -23,7 +25,12 @@ async def verify_api_token(x_api_token: str | None = Header(default=None)) -> No

       """

       token = resolve_api_token()

       if not token:

  -        return

  -    if not x_api_token or x_api_token != token:

  +        if settings.debug or ALLOW_NO_AUTH:

  +            return

  +        raise HTTPException(status_code=503, detail="API token not configured")

  +    if not x_api_token or not hmac.compare_digest(x_api_token, token):

           raise HTTPException(status_code=401, detail="invalid api token")



  - 검증 방법: API_TOKEN 미설정 상태에서 /api/portfolio 호출 시 503 반환, 설정 후에는 401/200 동작 확인.



  이슈 2. Memories API 무인증 접근 가능



  - 증상/설명: /api/memories 전체 엔드포인트가 인증 없이 공개되어 있음.

  - 근거: routers/memories.py:14, routers/memories.py:63

  - 악용 시나리오: 외부에서 메모리 전체 목록 조회/삭제(개인정보 포함 가능).

  - 권장 수정: 라우터에 Depends(verify_api_token) 적용.

  - 패치 제안:



  diff --git a/routers/memories.py b/routers/memories.py

  index 7a1c0fd..2f6b0e4 100644

  --- a/routers/memories.py

  +++ b/routers/memories.py

  @@ -8,10 +8,11 @@ from pydantic import BaseModel, Field

   from sqlalchemy.orm import Session

   from datetime import datetime



   from ..core.db import get_db

  +from ..core.auth import verify_api_token

   from ..services import memory_service



  -router = APIRouter(prefix="/api/memories", tags=["Memories"])

  +router = APIRouter(prefix="/api/memories", tags=["Memories"], dependencies=[Depends(verify_api_token)])



  - 검증 방법: 토큰 없이 /api/memories 호출 시 401/503, 토큰 포함 시 정상 응답.



  이슈 3. Telegram 웹훅 시크릿 미설정 시 명령 실행



  - 증상/설명: 시크릿/채팅ID가 설정되지 않아도 웹훅이 동작합니다.

  - 근거: routers/telegram_webhook.py:17, routers/telegram_webhook.py:28

  - 악용 시나리오: 외부에서 /api/telegram/webhook에 요청 → 스팸 규칙 변경, 모델 재학습 트리거, 알림 발송.

  - 권장 수정: 시크릿/허용 채팅ID 미설정 시 즉시 503 반환.

  - 패치 제안:



  diff --git a/routers/telegram_webhook.py b/routers/telegram_webhook.py

  index e8c5f8a..7c0c5a1 100644

  --- a/routers/telegram_webhook.py

  +++ b/routers/telegram_webhook.py

  @@ -22,6 +22,14 @@ ALLOWED_CHAT_ID = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

   @router.post("/webhook")

   async def telegram_webhook(request: Request):

       """텔레그램 업데이트 수신 웹훅"""

  +    if not WEBHOOK_SECRET:

  +        logger.error("Telegram webhook secret not configured")

  +        raise HTTPException(status_code=503, detail="Webhook not configured")

  +    if not ALLOWED_CHAT_ID:

  +        logger.error("Telegram chat id not configured")

  +        raise HTTPException(status_code=503, detail="Webhook not configured")



       # 1. Secret Token 검증

       secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")



  - 검증 방법: 시크릿 미설정 시 503, 설정 후 올바른 시크릿만 200.



  이슈 4. Settings API가 KIS 비밀키 노출



  - 증상/설명: /api/settings 응답에 KIS 비밀키가 그대로 포함됩니다.

  - 근거: core/schemas.py:153, services/settings_service.py:143

  - 악용 시나리오: 토큰 탈취 시 KIS 키/계정정보 유출.

  - 권장 수정: 응답에서 마스킹하거나 제외.

  - 패치 제안(마스킹 예시):



  diff --git a/services/settings_service.py b/services/settings_service.py

  index 2a9963a..0f5f2d6 100644

  --- a/services/settings_service.py

  +++ b/services/settings_service.py

  @@ -10,6 +10,13 @@ logger = logging.getLogger(__name__)



   def _normalize_benchmark_name(name: str) -> str:

       return name.replace(" ", "").upper()

  +

  +def _mask_secret(value: str | None) -> str | None:

  +    if not value:

  +        return None

  +    if len(value) <= 4:

  +        return "***"

  +    return f"{value[:2]}***{value[-2:]}"

  @@ -150,16 +157,16 @@ def to_settings_read(setting: Setting) -> SettingsRead:

           usd_fx_base=setting.usd_fx_base,

           usd_fx_now=setting.usd_fx_now,

           benchmark_name=setting.benchmark_name,

           benchmark_return=setting.benchmark_return,

  -        kis_app=setting.kis_app,

  -        kis_sec=setting.kis_sec,

  -        kis_acct_stock=setting.kis_acct_stock,

  -        kis_prod=setting.kis_prod,

  -        kis_htsid=setting.kis_htsid,

  -        kis_prod_url=setting.kis_prod_url,

  -        kis_ops_url=setting.kis_ops_url,

  -        kis_vps_url=setting.kis_vps_url,

  -        kis_vops_url=setting.kis_vops_url,

  -        kis_agent=setting.kis_agent,

  +        kis_app=_mask_secret(setting.kis_app),

  +        kis_sec=_mask_secret(setting.kis_sec),

  +        kis_acct_stock=_mask_secret(setting.kis_acct_stock),

  +        kis_prod=_mask_secret(setting.kis_prod),

  +        kis_htsid=_mask_secret(setting.kis_htsid),

  +        kis_prod_url=setting.kis_prod_url,

  +        kis_ops_url=setting.kis_ops_url,

  +        kis_vps_url=setting.kis_vps_url,

  +        kis_vops_url=setting.kis_vops_url,

  +        kis_agent=_mask_secret(setting.kis_agent),

       )



  - 검증 방법: /api/settings에서 키가 마스킹되는지 확인.



  이슈 5. 업로드 크기 제한 없음(메모리/디스크 DoS)



  - 증상/설명: 업로드 파일을 메모리로 전부 읽거나 무제한 디스크로 저장합니다.

  - 근거: routers/expense_upload.py:50, services/import_service.py:40

  - 악용 시나리오: 대형 파일 업로드로 메모리/디스크 고갈 → 서비스 중단.

  - 권장 수정: 최대 크기 제한 + 스트리밍 저장.

  - 패치 제안(핵심 로직 예시):



  diff --git a/routers/expense_upload.py b/routers/expense_upload.py

  index 17f9f7c..e9d3c4a 100644

  --- a/routers/expense_upload.py

  +++ b/routers/expense_upload.py

  @@ -2,8 +2,11 @@

   from __future__ import annotations



  +import os

  +import logging

   import tempfile

   from pathlib import Path

   from typing import Any

  @@ -13,6 +16,11 @@ from ..core.auth import verify_api_token

   from ..core.db import get_db



  +logger = logging.getLogger(__name__)

  +MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))

  +MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

  +CHUNK_SIZE = 1024 * 1024

  +

  @@ -49,11 +57,18 @@ async def upload_expense_file(

       # 임시 파일로 저장

       with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:

           tmp_path = Path(tmp_file.name)

  -        content = await file.read()

  -        tmp_file.write(content)

  +        total = 0

  +        while True:

  +            chunk = await file.read(CHUNK_SIZE)

  +            if not chunk:

  +                break

  +            total += len(chunk)

  +            if total > MAX_UPLOAD_BYTES:

  +                raise HTTPException(status_code=413, detail="File too large")

  +            tmp_file.write(chunk)



  - 검증 방법: 제한 초과 파일 업로드 시 413 반환 확인.



  이슈 6. 에러 상세 메시지/예외 노출



  - 증상/설명: 서버 내부 예외 메시지가 클라이언트에 그대로 노출됩니다.

  - 근거: routers/expense_upload.py:81, routers/report_ai.py:56, routers/report_ai.py:86

  - 악용 시나리오: 에러를 유발해 내부 경로/업스트림 응답/환경 정보를 추출.

  - 권장 수정: 클라이언트에는 일반 메시지, 상세는 로그.

  - 패치 제안(예시):



  diff --git a/routers/expense_upload.py b/routers/expense_upload.py

  index 17f9f7c..b23c40c 100644

  --- a/routers/expense_upload.py

  +++ b/routers/expense_upload.py

  @@ -81,8 +81,8 @@ async def upload_expense_file(

       except ValueError as e:

           raise HTTPException(status_code=400, detail=str(e))

       except Exception as e:

  -        import traceback

  -        traceback.print_exc()

  -        raise HTTPException(status_code=500, detail=str(e))

  +        logger.exception("Expense upload failed")

  +        raise HTTPException(status_code=500, detail="Internal error during import")



  - 검증 방법: 의도적 오류 발생 시 상세 대신 일반 메시지 반환 확인.



  이슈 7. 고비용 엔드포인트 레이트리밋 부재



  - 증상/설명: 뉴스 수집/AI 리포트/메모리 챗에 호출 제한이 없습니다.

  - 근거: routers/news.py:11, routers/report_ai.py:42, routers/memory_chat.py:373

  - 악용 시나리오: (가정) 토큰 유출 또는 미설정 시 외부에서 무제한 호출 → 비용/쿼터 소진.

  - 권장 수정: 토큰 또는 IP 기반 간단한 레이트리밋(인메모리라도).

  - 패치 제안: 의존성 추가 없이 core/rate_limit.py로 간단한 토큰 버킷 구현 후 Depends로 적용.

  - 검증 방법: 연속 호출 시 429 반환 확인.



  이슈 8. 토큰 비교 상수시간 아님 + 무차별 대입 방어 없음



  - 증상/설명: 문자열 비교가 타이밍에 민감하고, 반복 시도 제한이 없습니다.

  - 근거: core/auth.py:26

  - 악용 시나리오: 타이밍 측정/무차별 대입 시도(특히 레이트리밋 부재와 결합).

  - 권장 수정: hmac.compare_digest 사용 및 요청 제한 추가.

  - 패치 제안: 이슈 1 패치에 포함.

  - 검증 방법: 토큰 비교가 일정 시간에 가까운지(단위 테스트) 및 반복 시도 제한 확인.



  이슈 9. 백업 암호화 실패 시 평문 ZIP 폴백



  - 증상/설명: 암호화가 실패해도 평문 ZIP으로 계속 진행합니다.

  - 근거: services/backup.py:45, services/backup.py:52

  - 악용 시나리오: 백업이 외부로 전송/보관될 때 평문 유출.

  - 권장 수정: password 제공 시 암호화 실패는 실패 처리.

  - 패치 제안:



  diff --git a/services/backup.py b/services/backup.py

  index 2b7d4f8..9b1f1e3 100644

  --- a/services/backup.py

  +++ b/services/backup.py

  @@ -47,7 +47,8 @@ class BackupService:

                   subprocess.run(["zip", "-j", "-P", password, str(zip_file), str(src_file)], check=True)

                   logger.info("Password protected zip created via subprocess.")

                   return

               except Exception as e:

  -                logger.error(f"Subprocess zip failed: {e}. Falling back to standard zip (unencrypted).")

  +                logger.error(f"Subprocess zip failed: {e}.")

  +                raise RuntimeError("Encrypted zip failed") from e



  - 검증 방법: zip 명령 실패 시 예외 발생 확인.



  이슈 10. KIS 자격증명 DB 평문 저장



  - 증상/설명: KIS 키/계정정보가 DB에 평문 저장됩니다.

  - 근거: core/models.py:186, services/kis_settings.py:24

  - 악용 시나리오: DB/백업 유출 시 즉시 키 탈취.

  - 권장 수정: 민감 키는 환경변수로만 관리하거나, DB 저장 시 키로 암호화(예: KIS_TOKEN_KEY 기반) 후 복호화 사용.

  - 패치 제안: 장기 개선 항목(설계 변경).

  - 검증 방법: DB 스냅샷에서 키가 평문으로 보이지 않는지 확인.



  3. 빠른 액션 플랜



  - 오늘 바로(30~60분): 이슈 1, 2, 3, 6 적용(인증 강제/무인증 제거/에러 마스킹).

  - 이번 주(반나절~하루): 이슈 4, 5, 9 적용(설정 마스킹, 업로드 제한, 백업 실패 처리).

  - 장기(설계개선): 이슈 7, 10(레이트리밋 체계화, 비밀키 암호화/외부 Vault).



  4. 추가로 보면 좋은 파일/영역 목록(근거 포함)



  - core/config.py: 보안 관련 기본값/환경변수 정책 점검(특히 allowed_origins).

  - services/llm/*: 원격 LLM 호출 실패 시 응답/로그에서 민감정보 노출 여부 점검.

  - services/news/*: 외부 요청 타임아웃/재시도 정책과 API 키 노출 여부 확인.

  - Dockerfile, Dockerfile.base: root 실행 여부와 비밀키 주입 방식 확인.

  - storage/ 및 백업 관련 스크립트: DB/백업 파일 권한 및 외부 전송 경로 확인.



  원하면 위 패치들을 실제로 적용해서 커밋까지 진행해줄게.

Token usage: total=106,023 input=80,733 (+ 2,900,736 cached) output=25,290 (reasoning 14,208)



• 0. 전체 결론 요약

     현재 라우팅 구조는 대부분 토큰 보호가 되어 있지만, 인증이 실패‑오픈(fail‑open)인 구조와 무인증 메모리 API, 텔레그램 웹훅의 선택적 시크릿이 합쳐져 외부 노출 시 바로 악용될 수 있는 구멍이 있습니다. 또한 설정 API에서 KIS 비밀키가 그대로 내려가고, 업로드/LLM/뉴스 엔드포인트의 보호(크기 제한·레이트리

     밋·오류 노출)가 부족합니다.

  1. 우선순위 Top 10 이슈 표



  | Severity | 제목 | 악용 난이도 | 영향 | 위치(파일/함수) | 빠른 대응책 |

  |---|---|---|---|---|---|

  | Critical | API_TOKEN 미설정 시 인증 무효(FAIL‑OPEN) | 낮음 | 전체 API 무단 접근 | core/auth.py:17 | 토큰 미설정 시 503/부팅 실패 |

  | High | Memories API 무인증 접근 가능 | 낮음 | 메모리 데이터 읽기/삭제/변조 | routers/memories.py:14 | Depends(verify_api_token) 추가 |

  | High | Telegram 웹훅 시크릿 미설정 시 명령 실행 | 낮음 | 스팸 규칙 변경/모델 재학습/알림 남발 | routers/telegram_webhook.py:17 | 시크릿/채팅ID 필수화 |

  | High | Settings API가 KIS 비밀키 노출 | 낮음 | 자격증명 유출 | core/schemas.py:153, services/settings_service.py:143 | 응답 마스킹/제외 |

  | Medium | 업로드 크기 제한 없음(메모리/디스크 DoS) | 낮음 | 서비스 장애 | routers/expense_upload.py:50, services/import_service.py:40 | 업로드 상한 + 스트리밍 |

  | Medium | 에러 상세 메시지/예외 노출 | 낮음 | 내부 경로·업스트림 응답 노출 | routers/expense_upload.py:81, routers/report_ai.py:56 | 클라이언트에는 일반 메시지 |

  | Medium | 고비용 엔드포인트 레이트리밋 부재 | 낮음 | 비용 폭증/DoS | routers/news.py:11, routers/report_ai.py:42, routers/memory_chat.py:373 | 간단한 토큰/IP 기반 제한 |

  | Low | 토큰 비교 상수시간 아님 + 무차별 대입 방어 없음 | 중간 | 토큰 추측·타이밍 | core/auth.py:26 | hmac.compare_digest + 제한 |

  | Medium | 백업 암호화 실패 시 평문 ZIP 폴백 | 낮음 | 백업 유출 위험 | services/backup.py:45 | 암호화 실패 시 실패 처리 |

  | Medium | KIS 자격증명 DB 평문 저장 | 낮음 | DB/백업 유출 시 키 탈취 | core/models.py:186, services/kis_settings.py:24 | 환경변수/암호화 저장 |



  2. 상세 이슈(각 이슈당)



  이슈 1. API_TOKEN 미설정 시 인증 무효(FAIL‑OPEN)



  - 증상/설명: API_TOKEN이 없으면 모든 보호된 라우터가 인증 없이 통과됩니다. 실제 배포에서 환경변수 누락 시 전체 API가 공개됩니다.

  - 근거: core/auth.py:17, core/auth.py:23

  - 악용 시나리오: (가정) 외부에 노출된 서버에서 API_TOKEN이 빠진 채 실행 → 누구나 데이터 조회/수정 가능.

  - 권장 수정: 디버그/개발 모드가 아닌 경우 토큰 미설정 시 요청 차단(또는 부팅 실패).

  - 패치 제안:



  diff --git a/core/auth.py b/core/auth.py

  index 2d8c1a1..9c7b4b2 100644

  --- a/core/auth.py

  +++ b/core/auth.py

  @@ -1,7 +1,9 @@

   from __future__ import annotations

   from fastapi import Header, HTTPException

   from .config import settings

  +import hmac



   import os



   API_TOKEN = settings.api_token

  +ALLOW_NO_AUTH = os.getenv("ALLOW_NO_AUTH", "").lower() in ("1", "true", "yes")

  @@ -23,7 +25,12 @@ async def verify_api_token(x_api_token: str | None = Header(default=None)) -> No

       """

       token = resolve_api_token()

       if not token:

  -        return

  -    if not x_api_token or x_api_token != token:

  +        if settings.debug or ALLOW_NO_AUTH:

  +            return

  +        raise HTTPException(status_code=503, detail="API token not configured")

  +    if not x_api_token or not hmac.compare_digest(x_api_token, token):

           raise HTTPException(status_code=401, detail="invalid api token")



  - 검증 방법: API_TOKEN 미설정 상태에서 /api/portfolio 호출 시 503 반환, 설정 후에는 401/200 동작 확인.



  이슈 2. Memories API 무인증 접근 가능



  - 증상/설명: /api/memories 전체 엔드포인트가 인증 없이 공개되어 있음.

  - 근거: routers/memories.py:14, routers/memories.py:63

  - 악용 시나리오: 외부에서 메모리 전체 목록 조회/삭제(개인정보 포함 가능).

  - 권장 수정: 라우터에 Depends(verify_api_token) 적용.

  - 패치 제안:



  diff --git a/routers/memories.py b/routers/memories.py

  index 7a1c0fd..2f6b0e4 100644

  --- a/routers/memories.py

  +++ b/routers/memories.py

  @@ -8,10 +8,11 @@ from pydantic import BaseModel, Field

   from sqlalchemy.orm import Session

   from datetime import datetime



   from ..core.db import get_db

  +from ..core.auth import verify_api_token

   from ..services import memory_service



  -router = APIRouter(prefix="/api/memories", tags=["Memories"])

  +router = APIRouter(prefix="/api/memories", tags=["Memories"], dependencies=[Depends(verify_api_token)])



  - 검증 방법: 토큰 없이 /api/memories 호출 시 401/503, 토큰 포함 시 정상 응답.



  이슈 3. Telegram 웹훅 시크릿 미설정 시 명령 실행



  - 증상/설명: 시크릿/채팅ID가 설정되지 않아도 웹훅이 동작합니다.

  - 근거: routers/telegram_webhook.py:17, routers/telegram_webhook.py:28

  - 악용 시나리오: 외부에서 /api/telegram/webhook에 요청 → 스팸 규칙 변경, 모델 재학습 트리거, 알림 발송.

  - 권장 수정: 시크릿/허용 채팅ID 미설정 시 즉시 503 반환.

  - 패치 제안:



  diff --git a/routers/telegram_webhook.py b/routers/telegram_webhook.py

  index e8c5f8a..7c0c5a1 100644

  --- a/routers/telegram_webhook.py

  +++ b/routers/telegram_webhook.py

  @@ -22,6 +22,14 @@ ALLOWED_CHAT_ID = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")

   @router.post("/webhook")

   async def telegram_webhook(request: Request):

       """텔레그램 업데이트 수신 웹훅"""

  +    if not WEBHOOK_SECRET:

  +        logger.error("Telegram webhook secret not configured")

  +        raise HTTPException(status_code=503, detail="Webhook not configured")

  +    if not ALLOWED_CHAT_ID:

  +        logger.error("Telegram chat id not configured")

  +        raise HTTPException(status_code=503, detail="Webhook not configured")



       # 1. Secret Token 검증

       secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")



  - 검증 방법: 시크릿 미설정 시 503, 설정 후 올바른 시크릿만 200.



  이슈 4. Settings API가 KIS 비밀키 노출



  - 증상/설명: /api/settings 응답에 KIS 비밀키가 그대로 포함됩니다.

  - 근거: core/schemas.py:153, services/settings_service.py:143

  - 악용 시나리오: 토큰 탈취 시 KIS 키/계정정보 유출.

  - 권장 수정: 응답에서 마스킹하거나 제외.

  - 패치 제안(마스킹 예시):



  diff --git a/services/settings_service.py b/services/settings_service.py

  index 2a9963a..0f5f2d6 100644

  --- a/services/settings_service.py

  +++ b/services/settings_service.py

  @@ -10,6 +10,13 @@ logger = logging.getLogger(__name__)



   def _normalize_benchmark_name(name: str) -> str:

       return name.replace(" ", "").upper()

  +

  +def _mask_secret(value: str | None) -> str | None:

  +    if not value:

  +        return None

  +    if len(value) <= 4:

  +        return "***"

  +    return f"{value[:2]}***{value[-2:]}"

  @@ -150,16 +157,16 @@ def to_settings_read(setting: Setting) -> SettingsRead:

           usd_fx_base=setting.usd_fx_base,

           usd_fx_now=setting.usd_fx_now,

           benchmark_name=setting.benchmark_name,

           benchmark_return=setting.benchmark_return,

  -        kis_app=setting.kis_app,

  -        kis_sec=setting.kis_sec,

  -        kis_acct_stock=setting.kis_acct_stock,

  -        kis_prod=setting.kis_prod,

  -        kis_htsid=setting.kis_htsid,

  -        kis_prod_url=setting.kis_prod_url,

  -        kis_ops_url=setting.kis_ops_url,

  -        kis_vps_url=setting.kis_vps_url,

  -        kis_vops_url=setting.kis_vops_url,

  -        kis_agent=setting.kis_agent,

  +        kis_app=_mask_secret(setting.kis_app),

  +        kis_sec=_mask_secret(setting.kis_sec),

  +        kis_acct_stock=_mask_secret(setting.kis_acct_stock),

  +        kis_prod=_mask_secret(setting.kis_prod),

  +        kis_htsid=_mask_secret(setting.kis_htsid),

  +        kis_prod_url=setting.kis_prod_url,

  +        kis_ops_url=setting.kis_ops_url,

  +        kis_vps_url=setting.kis_vps_url,

  +        kis_vops_url=setting.kis_vops_url,

  +        kis_agent=_mask_secret(setting.kis_agent),

       )



  - 검증 방법: /api/settings에서 키가 마스킹되는지 확인.



  이슈 5. 업로드 크기 제한 없음(메모리/디스크 DoS)



  - 증상/설명: 업로드 파일을 메모리로 전부 읽거나 무제한 디스크로 저장합니다.

  - 근거: routers/expense_upload.py:50, services/import_service.py:40

  - 악용 시나리오: 대형 파일 업로드로 메모리/디스크 고갈 → 서비스 중단.

  - 권장 수정: 최대 크기 제한 + 스트리밍 저장.

  - 패치 제안(핵심 로직 예시):



  diff --git a/routers/expense_upload.py b/routers/expense_upload.py

  index 17f9f7c..e9d3c4a 100644

  --- a/routers/expense_upload.py

  +++ b/routers/expense_upload.py

  @@ -2,8 +2,11 @@

   from __future__ import annotations



  +import os

  +import logging

   import tempfile

   from pathlib import Path

   from typing import Any

  @@ -13,6 +16,11 @@ from ..core.auth import verify_api_token

   from ..core.db import get_db



  +logger = logging.getLogger(__name__)

  +MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "10"))

  +MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

  +CHUNK_SIZE = 1024 * 1024

  +

  @@ -49,11 +57,18 @@ async def upload_expense_file(

       # 임시 파일로 저장

       with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:

           tmp_path = Path(tmp_file.name)

  -        content = await file.read()

  -        tmp_file.write(content)

  +        total = 0

  +        while True:

  +            chunk = await file.read(CHUNK_SIZE)

  +            if not chunk:

  +                break

  +            total += len(chunk)

  +            if total > MAX_UPLOAD_BYTES:

  +                raise HTTPException(status_code=413, detail="File too large")

  +            tmp_file.write(chunk)



  - 검증 방법: 제한 초과 파일 업로드 시 413 반환 확인.



  이슈 6. 에러 상세 메시지/예외 노출



  - 증상/설명: 서버 내부 예외 메시지가 클라이언트에 그대로 노출됩니다.

  - 근거: routers/expense_upload.py:81, routers/report_ai.py:56, routers/report_ai.py:86

  - 악용 시나리오: 에러를 유발해 내부 경로/업스트림 응답/환경 정보를 추출.

  - 권장 수정: 클라이언트에는 일반 메시지, 상세는 로그.

  - 패치 제안(예시):



  diff --git a/routers/expense_upload.py b/routers/expense_upload.py

  index 17f9f7c..b23c40c 100644

  --- a/routers/expense_upload.py

  +++ b/routers/expense_upload.py

  @@ -81,8 +81,8 @@ async def upload_expense_file(

       except ValueError as e:

           raise HTTPException(status_code=400, detail=str(e))

       except Exception as e:

  -        import traceback

  -        traceback.print_exc()

  -        raise HTTPException(status_code=500, detail=str(e))

  +        logger.exception("Expense upload failed")

  +        raise HTTPException(status_code=500, detail="Internal error during import")



  - 검증 방법: 의도적 오류 발생 시 상세 대신 일반 메시지 반환 확인.



  이슈 7. 고비용 엔드포인트 레이트리밋 부재



  - 증상/설명: 뉴스 수집/AI 리포트/메모리 챗에 호출 제한이 없습니다.

  - 근거: routers/news.py:11, routers/report_ai.py:42, routers/memory_chat.py:373

  - 악용 시나리오: (가정) 토큰 유출 또는 미설정 시 외부에서 무제한 호출 → 비용/쿼터 소진.

  - 권장 수정: 토큰 또는 IP 기반 간단한 레이트리밋(인메모리라도).

  - 패치 제안: 의존성 추가 없이 core/rate_limit.py로 간단한 토큰 버킷 구현 후 Depends로 적용.

  - 검증 방법: 연속 호출 시 429 반환 확인.



  이슈 8. 토큰 비교 상수시간 아님 + 무차별 대입 방어 없음



  - 증상/설명: 문자열 비교가 타이밍에 민감하고, 반복 시도 제한이 없습니다.

  - 근거: core/auth.py:26

  - 악용 시나리오: 타이밍 측정/무차별 대입 시도(특히 레이트리밋 부재와 결합).

  - 권장 수정: hmac.compare_digest 사용 및 요청 제한 추가.

  - 패치 제안: 이슈 1 패치에 포함.

  - 검증 방법: 토큰 비교가 일정 시간에 가까운지(단위 테스트) 및 반복 시도 제한 확인.



  이슈 9. 백업 암호화 실패 시 평문 ZIP 폴백



  - 증상/설명: 암호화가 실패해도 평문 ZIP으로 계속 진행합니다.

  - 근거: services/backup.py:45, services/backup.py:52

  - 악용 시나리오: 백업이 외부로 전송/보관될 때 평문 유출.

  - 권장 수정: password 제공 시 암호화 실패는 실패 처리.

  - 패치 제안:



  diff --git a/services/backup.py b/services/backup.py

  index 2b7d4f8..9b1f1e3 100644

  --- a/services/backup.py

  +++ b/services/backup.py

  @@ -47,7 +47,8 @@ class BackupService:

                   subprocess.run(["zip", "-j", "-P", password, str(zip_file), str(src_file)], check=True)

                   logger.info("Password protected zip created via subprocess.")

                   return

               except Exception as e:

  -                logger.error(f"Subprocess zip failed: {e}. Falling back to standard zip (unencrypted).")

  +                logger.error(f"Subprocess zip failed: {e}.")

  +                raise RuntimeError("Encrypted zip failed") from e



  - 검증 방법: zip 명령 실패 시 예외 발생 확인.



  이슈 10. KIS 자격증명 DB 평문 저장



  - 증상/설명: KIS 키/계정정보가 DB에 평문 저장됩니다.

  - 근거: core/models.py:186, services/kis_settings.py:24

  - 악용 시나리오: DB/백업 유출 시 즉시 키 탈취.

  - 권장 수정: 민감 키는 환경변수로만 관리하거나, DB 저장 시 키로 암호화(예: KIS_TOKEN_KEY 기반) 후 복호화 사용.

  - 패치 제안: 장기 개선 항목(설계 변경).

  - 검증 방법: DB 스냅샷에서 키가 평문으로 보이지 않는지 확인.



  3. 빠른 액션 플랜



  - 오늘 바로(30~60분): 이슈 1, 2, 3, 6 적용(인증 강제/무인증 제거/에러 마스킹).

  - 이번 주(반나절~하루): 이슈 4, 5, 9 적용(설정 마스킹, 업로드 제한, 백업 실패 처리).

  - 장기(설계개선): 이슈 7, 10(레이트리밋 체계화, 비밀키 암호화/외부 Vault).



  4. 추가로 보면 좋은 파일/영역 목록(근거 포함)



  - core/config.py: 보안 관련 기본값/환경변수 정책 점검(특히 allowed_origins).

  - services/llm/*: 원격 LLM 호출 실패 시 응답/로그에서 민감정보 노출 여부 점검.

  - services/news/*: 외부 요청 타임아웃/재시도 정책과 API 키 노출 여부 확인.

  - Dockerfile, Dockerfile.base: root 실행 여부와 비밀키 주입 방식 확인.

  - storage/ 및 백업 관련 스크립트: DB/백업 파일 권한 및 외부 전송 경로 확인.



  원하면 위 패치들을 실제로 적용해서 커밋까지 진행해줄게.

Token usage: total=106,023 input=80,733 (+ 2,900,736 cached) output=25,290 (reasoning 14,208)

To continue this session, run codex resume 019c1e23-d431-7582-9cc6-d6da90b82522

dlckdgn@marisa-server:~/personal-portfolio/backend$  한번 보안리뷰 시켰는데 음 바이브코딩 초보개발자라 그런가 미쳐 생각하지 못한거 나왔네 혼자쓰는 환경이긴한데  1. python -m unittest discover backend/tests