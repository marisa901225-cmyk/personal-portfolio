from __future__ import annotations

import http.client
import json
import logging
import socket
import time
from dataclasses import dataclass
from urllib.parse import quote

logger = logging.getLogger(__name__)


class DockerSocketError(RuntimeError):
    pass


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


@dataclass(frozen=True)
class ContainerState:
    running: bool
    health: str | None = None

    @property
    def ready(self) -> bool:
        return self.running and self.health in {None, "healthy"}


def _docker_request(
    *,
    socket_path: str,
    method: str,
    path: str,
    timeout: float = 10.0,
) -> tuple[int, bytes]:
    conn = _UnixHTTPConnection(socket_path, timeout=timeout)
    try:
        conn.request(method, path)
        response = conn.getresponse()
        body = response.read()
        return int(response.status), body
    except OSError as exc:
        raise DockerSocketError(f"Docker socket request failed: {method} {path}: {exc}") from exc
    finally:
        conn.close()


def inspect_container(*, socket_path: str, container_name: str) -> ContainerState | None:
    encoded_name = quote(container_name, safe="")
    status, body = _docker_request(socket_path=socket_path, method="GET", path=f"/containers/{encoded_name}/json")
    if status == 404:
        return None
    if status >= 400:
        raise DockerSocketError(f"Docker inspect failed for {container_name}: HTTP {status} {body[:200]!r}")

    data = json.loads(body.decode("utf-8") or "{}")
    state = data.get("State") or {}
    health = state.get("Health") or {}
    health_status = str(health.get("Status") or "").strip() or None
    return ContainerState(running=bool(state.get("Running")), health=health_status)


def stop_container(*, socket_path: str, container_name: str, timeout_sec: int) -> bool:
    state = inspect_container(socket_path=socket_path, container_name=container_name)
    if state is None:
        logger.warning("Docker container not found for stop: %s", container_name)
        return False
    if not state.running:
        return False

    encoded_name = quote(container_name, safe="")
    status, body = _docker_request(
        socket_path=socket_path,
        method="POST",
        path=f"/containers/{encoded_name}/stop?t={max(1, int(timeout_sec))}",
        timeout=max(5.0, float(timeout_sec) + 5.0),
    )
    if status not in {204, 304}:
        raise DockerSocketError(f"Docker stop failed for {container_name}: HTTP {status} {body[:200]!r}")
    return True


def start_container(*, socket_path: str, container_name: str) -> None:
    encoded_name = quote(container_name, safe="")
    status, body = _docker_request(socket_path=socket_path, method="POST", path=f"/containers/{encoded_name}/start")
    if status not in {204, 304}:
        raise DockerSocketError(f"Docker start failed for {container_name}: HTTP {status} {body[:200]!r}")


def wait_container_ready(
    *,
    socket_path: str,
    container_name: str,
    timeout_sec: int,
    poll_sec: float = 2.0,
) -> ContainerState:
    deadline = time.monotonic() + max(1.0, float(timeout_sec))
    last_state: ContainerState | None = None
    while time.monotonic() < deadline:
        state = inspect_container(socket_path=socket_path, container_name=container_name)
        if state is None:
            raise DockerSocketError(f"Docker container not found: {container_name}")
        last_state = state
        if state.ready:
            return state
        time.sleep(max(0.2, float(poll_sec)))
    raise DockerSocketError(f"Timed out waiting for {container_name} to become ready: {last_state}")
