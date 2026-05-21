"""
Telegram Webhook Router - 텔레그램 봇 웹훅 엔드포인트
명령어를 적절한 핸들러로 라우팅
"""
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Request, HTTPException

from ..core.db import SessionLocal
from ..integrations.telegram import send_telegram_message
from .handlers.spam_handler import handle_spam_command

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
logger = logging.getLogger(__name__)

# 환경변수에서 시크릿 토큰과 허용된 채팅 ID 로드
WEBHOOK_SECRET = os.getenv("X_TELEGRAM_BOT_API_SECRET_TOKEN") or os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN")
ALLOWED_CHAT_ID = os.getenv("ALARM_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
JELLYFIN_CONTAINER_NAME = os.getenv("TELEGRAM_JELLYFIN_CONTAINER_NAME", "jellyfin")
JELLYFIN_COMPOSE_SERVICE = os.getenv("TELEGRAM_JELLYFIN_COMPOSE_SERVICE", "jellyfin")
JELLYFIN_COMPOSE_PROJECT = os.getenv("TELEGRAM_JELLYFIN_COMPOSE_PROJECT", "my-home-server")
COMFYUI_CONTAINER_NAME = os.getenv("TELEGRAM_COMFYUI_CONTAINER_NAME", "myasset-comfyui")
DOCKER_STATUS_PROJECTS = {
    item.strip()
    for item in os.getenv("TELEGRAM_DOCKER_STATUS_PROJECTS", "personal-portfolio").split(",")
    if item.strip()
}
HARUHI_LLM_CONTAINER_NAME = os.getenv("TELEGRAM_HARUHI_LLM_CONTAINER_NAME", "myasset-llm-sycl-huihui")
DOCKER_SOCKET_PATH = os.getenv("TELEGRAM_DOCKER_SOCKET_PATH", "/var/run/docker.sock")
LLM_MANUAL_STOP_FLAG_FILE = Path(
    os.getenv(
        "LLM_MANUAL_STOP_FLAG_FILE",
        str(Path(__file__).resolve().parents[1] / "data" / "llm_manual_stop.flag"),
    )
)
LLM_MANUAL_STOP_RESUME_HOUR = int(os.getenv("LLM_MANUAL_STOP_RESUME_HOUR", "8"))
LLM_MANUAL_STOP_TIMEZONE = os.getenv("LLM_MANUAL_STOP_TIMEZONE", "Asia/Seoul")


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """텔레그램 업데이트 수신 웹훅"""
    if not WEBHOOK_SECRET:
        logger.error("Telegram webhook secret not configured")
        raise HTTPException(status_code=503, detail="Webhook not configured")
    if not ALLOWED_CHAT_ID:
        logger.error("Telegram chat id not configured")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    # 1. Secret Token 검증
    secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if WEBHOOK_SECRET and secret_header != WEBHOOK_SECRET:
        logger.warning("Invalid webhook secret token (len=%s)", len(secret_header) if secret_header else 0)
        raise HTTPException(status_code=403, detail="Invalid secret")
    
    # 2. 업데이트 파싱
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    message = update.get("message")
    if not message:
        return {"ok": True}
    
    # 3. Chat ID 검증 (본인만 허용)
    chat_id = str(message.get("chat", {}).get("id", ""))
    if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID:
        logger.warning(f"Unauthorized chat_id: {chat_id}")
        return {"ok": True}
    
    # 4. 텍스트 추출 및 유효성 검사
    text = message.get("text", "").strip()
    if not text:
        return {"ok": True}
    
    # 5. 명령어 처리 (/)
    if text.startswith("/"):
        await _handle_command(text, chat_id)
    
    return {"ok": True}


async def _handle_command(text: str, chat_id: str):
    """슬래시 명령어 처리"""
    parts = text[1:].split(maxsplit=1)
    cmd = parts[0] if len(parts) > 0 else ""
    arg = parts[1] if len(parts) > 1 else ""
    # Group chats may send commands as /command@BotUsername.
    cmd = cmd.split("@", maxsplit=1)[0]
    
    # /spam 접두사 지원 (하이브리드)
    if cmd == "spam":
        parts = arg.split(maxsplit=1)
        cmd = parts[0] if len(parts) > 0 else ""
        arg = parts[1] if len(parts) > 1 else ""
        cmd = cmd.split("@", maxsplit=1)[0]

    if cmd == "com":
        subcmd = arg.strip().split(maxsplit=1)[0].lower() if arg.strip() else ""
        if subcmd in {"on", "off"}:
            cmd = f"com_{subcmd}"
            arg = ""
    
    # 지원하는 명령어 리스트
    SUPPORTED_CMDS = [
        "add",
        "del",
        "list",
        "on",
        "off",
        "help",
        "report",
        "docker_status",
        "jellyfin_restart",
        "com_on",
        "com_off",
        "haruhi_llm_start",
        "haruhi_llm_stop",
    ]
    if cmd not in SUPPORTED_CMDS:
        return
    
    # 명령어별 처리
    response_text = ""
    
    if cmd == "help":
        help_text = (
            "🚀 <b>개인 포트폴리오 관리 봇 도움말</b>\n\n"
            "<b>🛡️ 스팸 필터 관리</b>\n"
            "• /add [단어] - 스팸 차단 키워드 추가\n"
            "• /del [단어] - 스팸 차단 키워드 삭제\n"
            "• /list - 현재 차단된 키워드 목록 확인\n"
            "• /on - 스팸 필터 기능을 활성화합니다.\n"
            "• /off - 스팸 필터 기능을 일시 중지합니다.\n\n"
            "<b>🐳 서버 및 Docker 제어</b>\n"
            "• /docker_status - 주요 컨테이너의 가동 상태와 포트 정보를 확인합니다.\n"
            "• /jellyfin_restart - Jellyfin 미디어 서버 컨테이너를 안전하게 재시작합니다.\n"
            "• /com_on 또는 /com on - ComfyUI 그림서버를 시작합니다.\n"
            "• /com_off 또는 /com off - ComfyUI 그림서버를 정지합니다.\n"
            "• /haruhi_llm_start - 하루히 LLM(채팅) 인벤토리 서비스를 시작합니다.\n"
            "• /haruhi_llm_stop - 하루히 LLM 서비스를 정지하여 자원을 확보합니다.\n\n"
            "<b>📈 분석 및 리포트</b>\n"
            "• /report [게임명] - 스팀 실시간 트렌드 및 관련 소식 요약을 생성합니다.\n\n"
            "<b>💡 기타</b>\n"
            "• /help - 지금 보고 계신 도움말 메뉴를 출력합니다."
        )
        await send_telegram_message(help_text)
        return

    if cmd == "report":
        from ..services.reporting.template import build_telegram_steam_trend_message
        response_text = build_telegram_steam_trend_message(arg)
        await send_telegram_message(response_text)
        return

    if cmd == "docker_status":
        response_text = await _get_docker_status()
        await send_telegram_message(response_text)
        return

    if cmd == "jellyfin_restart":
        response_text = await _restart_jellyfin_container()
        await send_telegram_message(response_text)
        return

    if cmd == "com_on":
        response_text = await _control_comfyui("start")
        await send_telegram_message(response_text)
        return

    if cmd == "com_off":
        response_text = await _control_comfyui("stop")
        await send_telegram_message(response_text)
        return

    if cmd == "haruhi_llm_start":
        response_text = await _control_haruhi_llm("start")
        await send_telegram_message(response_text)
        return

    if cmd == "haruhi_llm_stop":
        response_text = await _control_haruhi_llm("stop")
        await send_telegram_message(response_text)
        return
    
    db = SessionLocal()
    try:
        response_text = await handle_spam_command(cmd, arg, db)
        
        # 규칙 변경 시 AI 모델 재학습 트리거
        if cmd in ["add", "del", "on", "off"] and any(icon in response_text for icon in ["✅", "🗑️", "⏸️", "▶️"]):
            from ..services.spam_trainer import train_spam_model
            if train_spam_model():
                response_text += "\n <i>AI 모델이 최신 규칙으로 재학습되었습니다.</i>"
    finally:
        db.close()
    
    if response_text:
        await send_telegram_message(response_text)


async def _restart_jellyfin_container() -> str:
    """Restart the configured Jellyfin container through the Docker Engine API."""
    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET_PATH)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=20.0) as client:
            container_id, container_name = await _find_jellyfin_container(client)
            if not container_id:
                return f"❌ Jellyfin 컨테이너를 찾지 못했습니다: <code>{JELLYFIN_COMPOSE_PROJECT}/{JELLYFIN_COMPOSE_SERVICE}</code>"

            restart_response = await client.post(f"/containers/{container_id}/restart", params={"t": 10})
            restart_response.raise_for_status()

        return f"✅ Jellyfin 재시작 명령을 보냈습니다: <code>{container_name}</code>"
    except httpx.HTTPError as exc:
        logger.error("Jellyfin restart failed through Docker API: %s", exc)
        return f"❌ Jellyfin 재시작 실패: <code>{type(exc).__name__}</code>"
    except Exception as exc:
        logger.exception("Unexpected Jellyfin restart failure")
        return f"❌ Jellyfin 재시작 중 예외 발생: <code>{type(exc).__name__}</code>"


async def _get_docker_status() -> str:
    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET_PATH)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=20.0) as client:
            response = await client.get("/containers/json", params={"all": "true"})
            response.raise_for_status()
            containers = _filter_docker_status_containers(response.json())

        if not containers:
            return "📦 <b>Docker 상태</b>\n표시할 컨테이너가 없습니다."

        lines = ["📦 <b>Docker 상태</b>"]
        for container in containers[:15]:
            names = container.get("Names") or ["unknown"]
            name = str(names[0]).lstrip("/")
            state = str(container.get("State") or "")
            status = str(container.get("Status") or state or "unknown")
            icon = "🟢" if state == "running" else "🔴"
            ports = _format_container_ports(container.get("Ports") or [])
            line = f"{icon} <code>{name}</code> - {status}"
            if ports:
                line += f" ({ports})"
            lines.append(line)

        if len(containers) > 15:
            lines.append(f"… 외 {len(containers) - 15}개")
        return "\n".join(lines)
    except httpx.HTTPError as exc:
        logger.error("Docker status fetch failed through Docker API: %s", exc)
        return f"❌ Docker 상태 조회 실패: <code>{type(exc).__name__}</code>"
    except Exception as exc:
        logger.exception("Unexpected Docker status failure")
        return f"❌ Docker 상태 조회 중 예외 발생: <code>{type(exc).__name__}</code>"


def _filter_docker_status_containers(containers: list[dict]) -> list[dict]:
    filtered = [container for container in containers if _should_include_container_in_status(container)]
    return sorted(
        filtered,
        key=lambda container: (
            0 if str(container.get("State") or "") == "running" else 1,
            str((container.get("Names") or ["unknown"])[0]).lstrip("/"),
        ),
    )


def _should_include_container_in_status(container: dict) -> bool:
    state = str(container.get("State") or "")
    labels = container.get("Labels") or {}
    project = str(labels.get("com.docker.compose.project") or "")
    service = str(labels.get("com.docker.compose.service") or "")
    names = container.get("Names") or []
    primary_name = str(names[0]).lstrip("/") if names else ""

    if state == "running":
        return True
    if project and project in DOCKER_STATUS_PROJECTS:
        return True
    if project == JELLYFIN_COMPOSE_PROJECT and service == JELLYFIN_COMPOSE_SERVICE:
        return True
    if primary_name == JELLYFIN_CONTAINER_NAME:
        return True
    return False


async def _control_haruhi_llm(action: str) -> str:
    if action == "start":
        _clear_llm_manual_stop_flag()

    result = await _control_container(
        action=action,
        container_name=HARUHI_LLM_CONTAINER_NAME,
        label="하루히 LLM",
    )

    if action == "stop":
        _write_llm_manual_stop_flag()

    return result


async def _control_comfyui(action: str) -> str:
    return await _control_container(
        action=action,
        container_name=COMFYUI_CONTAINER_NAME,
        label="ComfyUI 그림서버",
    )


def _write_llm_manual_stop_flag() -> None:
    LLM_MANUAL_STOP_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    resume_epoch = _next_llm_manual_stop_resume_epoch()
    LLM_MANUAL_STOP_FLAG_FILE.write_text(
        f"telegram_haruhi_llm_stop\nresume_epoch={resume_epoch}\n",
        encoding="utf-8",
    )


def _next_llm_manual_stop_resume_epoch() -> int:
    timezone = ZoneInfo(LLM_MANUAL_STOP_TIMEZONE)
    now = datetime.now(timezone)
    resume_hour = min(max(LLM_MANUAL_STOP_RESUME_HOUR, 0), 23)
    resume_at = now.replace(hour=resume_hour, minute=0, second=0, microsecond=0)
    if resume_at <= now:
        resume_at += timedelta(days=1)
    return int(resume_at.timestamp())


def _clear_llm_manual_stop_flag() -> None:
    try:
        LLM_MANUAL_STOP_FLAG_FILE.unlink()
    except FileNotFoundError:
        return


async def _control_container(*, action: str, container_name: str, label: str) -> str:
    if action not in {"start", "stop"}:
        logger.error("Unsupported container control action: %s", action)
        return f"❌ 지원하지 않는 동작입니다: <code>{action}</code>"

    action_kr = "시작" if action == "start" else "정지"
    try:
        transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET_PATH)
        async with httpx.AsyncClient(transport=transport, base_url="http://docker", timeout=20.0) as client:
            container_id = await _find_container_id_by_name(client, container_name)
            if not container_id:
                return f"❌ {label} 컨테이너를 찾지 못했습니다: <code>{container_name}</code>"

            params = {"t": 10} if action == "stop" else None
            response = await client.post(f"/containers/{container_id}/{action}", params=params)
            if response.status_code == 304:
                state_kr = "이미 실행 중입니다" if action == "start" else "이미 정지 상태입니다"
                return f"ℹ️ {label}은 {state_kr}: <code>{container_name}</code>"
            response.raise_for_status()

        return f"✅ {label} {action_kr} 명령을 보냈습니다: <code>{container_name}</code>"
    except httpx.HTTPError as exc:
        logger.error("%s %s failed through Docker API: %s", label, action, exc)
        return f"❌ {label} {action_kr} 실패: <code>{type(exc).__name__}</code>"
    except Exception as exc:
        logger.exception("Unexpected %s %s failure", label, action)
        return f"❌ {label} {action_kr} 중 예외 발생: <code>{type(exc).__name__}</code>"


async def _find_jellyfin_container(client: httpx.AsyncClient) -> tuple[str | None, str]:
    filters = {
        "label": [
            f"com.docker.compose.project={JELLYFIN_COMPOSE_PROJECT}",
            f"com.docker.compose.service={JELLYFIN_COMPOSE_SERVICE}",
        ]
    }
    response = await client.get("/containers/json", params={"all": "true", "filters": json.dumps(filters)})
    response.raise_for_status()
    containers = response.json()

    if containers:
        container = containers[0]
        names = container.get("Names") or [JELLYFIN_COMPOSE_SERVICE]
        return container.get("Id"), str(names[0]).lstrip("/")

    inspect_response = await client.get(f"/containers/{JELLYFIN_CONTAINER_NAME}/json")
    if inspect_response.status_code == 404:
        return None, JELLYFIN_CONTAINER_NAME
    inspect_response.raise_for_status()
    inspect_data = inspect_response.json()
    return inspect_data.get("Id"), str(inspect_data.get("Name") or JELLYFIN_CONTAINER_NAME).lstrip("/")


async def _find_container_id_by_name(client: httpx.AsyncClient, container_name: str) -> str | None:
    inspect_response = await client.get(f"/containers/{container_name}/json")
    if inspect_response.status_code == 404:
        return None
    inspect_response.raise_for_status()
    inspect_data = inspect_response.json()
    return inspect_data.get("Id")


def _format_container_ports(ports: list[dict]) -> str:
    rendered: list[str] = []
    for port in ports:
        public_port = port.get("PublicPort")
        private_port = port.get("PrivatePort")
        if public_port and private_port:
            rendered.append(f"{public_port}->{private_port}")
        elif private_port:
            rendered.append(str(private_port))
    return ", ".join(rendered)
