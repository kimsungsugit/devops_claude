"""File resolver abstraction layer.

Provides a unified interface for file access with two modes:
  - LOCAL mode: direct filesystem access (default)
  - CLOUDIUM mode: read-only file access via IPC to a Cloudium-trusted
    worker process (excel_rename_gui_v2.exe, GUI subsystem). The worker
    holds Cloudium permissions; backend python.exe does NOT (no inheritance).
    All reads are delegated to the worker over a localhost TCP JSON
    line protocol.

Cloudium 동작 방식 (Phase 2 — IPC 모델):
  1. 사용자가 클라우디움 worker (excel_rename_gui_v2.exe, GUI subsystem) 실행
     → 클라우디움이 그 프로세스에 권한 부여
  2. backend는 worker에 TCP IPC로 read 위임 (localhost:8765)
  3. worker가 권한으로 read 후 결과 반환

설정:
    DEVOPS_FILE_MODE=local       (기본값)
    DEVOPS_FILE_MODE=cloudium

    CLOUDIUM_GATE_PROCESS=excel_rename_gui_v2.exe   (UI 표시용)
    CLOUDIUM_ALLOWED_PREFIXES=//cloudium/share,Z:/proj
    CLOUDIUM_WORKER_HOST=127.0.0.1                  (기본값)
    CLOUDIUM_WORKER_PORT=8765                       (기본값)
"""
from __future__ import annotations

import base64
import contextvars
import json
import os
import sys
import socket
import logging
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

# Backend project root — workspace bypass용 (workspace 자체 디렉토리는
# cloudium 권한 검사 면제. 예: reports/, .devops_pro_cache/, config/).
# backend/services/file_resolver.py → parents[2] = repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 사용자 home bypass — frontend cache_root가 보통 ~/.devops_v2_cache 등
# 사용자 home 안에 위치. backend python.exe는 사용자 home 자체 read/write
# 권한 보유(cloudium 권한 무관). N17 fix.
try:
    _USER_HOME = Path.home().resolve()
except Exception:
    _USER_HOME = None

# W1: request-local set — 미들웨어가 path들을 이미 검증했으면 read 메서드의
# 중복 검사를 skip할 수 있게 한다. 미들웨어 layer 통과 → ContextVar set →
# read 메서드는 _check_allowed/_ensure_gate 생략.
# ContextVar는 asyncio task 격리되므로 동시 요청간 누설 없음.
# **W4 fix**: 단일 path → frozenset[str]로 확장. 미들웨어가 검증한 모든 path를
# 한 번에 마킹해야 multi-path endpoint(req_paths 등)에서도 W1 perf 효과 누적.
_path_already_validated: contextvars.ContextVar[Optional[frozenset]] = contextvars.ContextVar(
    "_cloudium_path_already_validated", default=None,
)


def mark_path_validated(paths) -> Any:
    """미들웨어가 호출 — 검증 완료된 path 집합 마킹. token 반환.

    paths: Iterable[str] (list, tuple, frozenset 등) 또는 단일 str. 빈 iterable이면
    None 반환 — 호출자는 finally에서 `reset_path_validated(token)`을 호출하면 None일 때
    no-op로 처리되도록 보장된다.

    **C-N2 호출 규약 (paired-call invariant)**:
      - `mark_path_validated`와 `reset_path_validated`는 반드시 try/finally 짝으로 호출.
      - finally 블록 외부에서 mark만 호출하고 reset 누락하면 같은 asyncio task에 ContextVar
        잔존 → 재진입 시 stale frozenset에 의한 W1 false skip 위험.
      - 미들웨어 dispatch 외 호출자(WebSocket/BackgroundTask 등) 도입 시 반드시 try/finally
        보장. 외부 호출자 추가 전 본 docstring 갱신 필수.
    """
    if isinstance(paths, str):
        paths = (paths,)
    frozen = frozenset(p for p in paths if p)
    return _path_already_validated.set(frozen) if frozen else None


def reset_path_validated(token: Any) -> None:
    """미들웨어가 finally에서 호출 — ContextVar 원복.

    `mark_path_validated`가 빈 iterable로 None 반환한 경우 token=None이며 본 함수는 no-op.
    paired-call invariant는 mark_path_validated docstring 참조.
    """
    if token is not None:
        _path_already_validated.reset(token)

_logger = logging.getLogger("devops_api.file_resolver")

# Public API. set_resolver는 의도적으로 제외 — 테스트/내부 전용 (스타글로브 import
# `from file_resolver import *`로는 가져갈 수 없게 한다). 프로덕션 코드에서는
# switch_mode를 사용하라.
__all__ = [
    "FileResolver",
    "LocalFileResolver",
    "CloudiumFileResolver",
    "get_resolver",
    "switch_mode",
    "is_gate_running",
    "invalidate_gate_cache",
    "DEFAULT_GATE_PROCESS",
]

# ---------------------------------------------------------------------------
# Cloudium gate detection (Phase 2: worker IPC ping)
# ---------------------------------------------------------------------------
DEFAULT_GATE_PROCESS = "excel_rename_gui_v2.exe"  # UI 표시용 (실제 detect는 ping)
DEFAULT_WORKER_HOST = "127.0.0.1"
DEFAULT_WORKER_PORT = 8765
_GATE_CACHE_TTL = 1.0
_PING_TIMEOUT = 0.5  # seconds — worker 응답 대기 짧게 (live-ness 검사)

# Atomic tuple snapshot: (cache_key, running, ts)
_gate_cache: "tuple[str, bool, float]" = ("", False, 0.0)


def _gate_process_name() -> str:
    return os.getenv("CLOUDIUM_GATE_PROCESS", DEFAULT_GATE_PROCESS).strip() or DEFAULT_GATE_PROCESS


def _worker_endpoint() -> "tuple[str, int]":
    host = os.getenv("CLOUDIUM_WORKER_HOST", DEFAULT_WORKER_HOST).strip() or DEFAULT_WORKER_HOST
    try:
        port = int(os.getenv("CLOUDIUM_WORKER_PORT", str(DEFAULT_WORKER_PORT)))
    except ValueError:
        port = DEFAULT_WORKER_PORT
    return host, port


def invalidate_gate_cache() -> None:
    """게이트 캐시 강제 무효화 — 모드 전환·테스트·관리 작업 시 사용."""
    global _gate_cache
    _gate_cache = ("", False, 0.0)


def _ping_worker(host: str, port: int, timeout: float = _PING_TIMEOUT) -> bool:
    """worker TCP server에 ping op 전송 → pong 수신 시 True."""
    req = json.dumps({"id": "ping", "op": "ping", "args": {}}).encode("utf-8") + b"\n"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(req)
            sock.settimeout(timeout)
            buf = b""
            while b"\n" not in buf and len(buf) < 4096:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
        if not buf:
            return False
        line = buf.split(b"\n", 1)[0]
        resp = json.loads(line.decode("utf-8"))
        return bool(resp.get("ok") and resp.get("result") == "pong")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _logger.debug("Cloudium worker ping failed (%s:%d): %s", host, port, exc)
        return False


def is_gate_running(
    process_name: Optional[str] = None,  # 호환성 — 무시되며 UI display 전용
    *,
    force: bool = False,
    host: Optional[str] = None,
    port: Optional[int] = None,
) -> bool:
    """Cloudium worker가 살아있는지 TCP ping으로 검사.

    Phase 2 — tasklist/psutil로 프로세스 이름 탐지하던 방식 폐기.
    실제 권한 검증 = worker가 IPC에 응답하는지.
    """
    global _gate_cache
    h = host or _worker_endpoint()[0]
    p = port if port is not None else _worker_endpoint()[1]
    key = f"{h}:{p}"
    now = time.monotonic()
    cached_name, cached_running, cached_ts = _gate_cache
    if not force and cached_name == key and now - cached_ts < _GATE_CACHE_TTL:
        return cached_running

    running = _ping_worker(h, p)
    _gate_cache = (key, running, now)
    return running


class FileResolver(ABC):
    """Abstract base for file access."""

    @abstractmethod
    def exists(self, path: str) -> bool: ...
    @abstractmethod
    def is_file(self, path: str) -> bool: ...
    @abstractmethod
    def is_dir(self, path: str) -> bool: ...
    @abstractmethod
    def read_bytes(self, path: str) -> bytes: ...
    @abstractmethod
    def read_text(self, path: str, encoding: str = "utf-8") -> str: ...
    @abstractmethod
    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False) -> List[str]: ...
    @abstractmethod
    def resolve(self, path: str) -> str: ...

    @property
    @abstractmethod
    def mode(self) -> str: ...

    def get_config(self) -> Dict[str, Any]:
        return {"mode": self.mode}


class LocalFileResolver(FileResolver):
    """Direct local filesystem access."""

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def is_file(self, path: str) -> bool:
        return Path(path).is_file()

    def is_dir(self, path: str) -> bool:
        return Path(path).is_dir()

    def read_bytes(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        return Path(path).read_text(encoding=encoding, errors="replace")

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False) -> List[str]:
        p = Path(path)
        if not p.is_dir():
            return []
        if recursive:
            return [str(f) for f in p.rglob(pattern) if f.is_file()]
        return [str(f) for f in p.glob(pattern) if f.is_file()]

    def resolve(self, path: str) -> str:
        return str(Path(path).resolve())

    @property
    def mode(self) -> str:
        return "local"


class CloudiumFileResolver(LocalFileResolver):
    """Cloudium mode (Phase 2 — IPC) — read-only access via worker delegation.

    동작:
      1. 모든 read 호출은 worker (excel_rename_gui_v2.exe)에 TCP IPC로 위임
      2. backend python.exe는 클라우디움 권한 없음 — worker만 권한 보유
      3. worker 미연결 시 PermissionError (게이트 OFF)
      4. allowed_prefixes 화이트리스트는 backend에서 사전 검증 (worker로 전달 전)
    """

    def __init__(
        self,
        allowed_prefixes: str = "",
        gate_process: str = "",
        host: str = "",
        port: Optional[int] = None,
        **_kwargs,
    ):
        raw = allowed_prefixes or os.getenv("CLOUDIUM_ALLOWED_PREFIXES", "")
        self.allowed_prefixes = [p.strip() for p in raw.split(",") if p.strip()]
        self.gate_process = (gate_process or _gate_process_name()).strip() or DEFAULT_GATE_PROCESS
        env_host, env_port = _worker_endpoint()
        self.worker_host = (host or env_host).strip() or DEFAULT_WORKER_HOST
        try:
            self.worker_port = int(port) if port else env_port
        except (TypeError, ValueError):
            self.worker_port = DEFAULT_WORKER_PORT

    # ── Worker IPC ─────────────────────────────────────────────────────
    def _ipc_call(self, op: str, args: Optional[Dict[str, Any]] = None,
                  timeout: float = 10.0) -> Any:
        """worker에 op 전송 → result 수신. 실패 시 OSError/PermissionError raise."""
        request = {"id": uuid.uuid4().hex, "op": op, "args": args or {}}
        line = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            with socket.create_connection((self.worker_host, self.worker_port),
                                          timeout=timeout) as sock:
                sock.sendall(line)
                sock.settimeout(timeout)
                buf = b""
                while b"\n" not in buf:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
        except (ConnectionRefusedError, ConnectionResetError, socket.timeout, OSError) as exc:
            raise PermissionError(
                f"Cloudium worker 연결 실패 ({self.worker_host}:{self.worker_port}): {exc}\n"
                f"  '{self.gate_process}' 가 실행 중인지 확인하세요."
            ) from exc
        if not buf:
            raise PermissionError("Cloudium worker 응답 없음")
        first_line = buf.split(b"\n", 1)[0]
        try:
            resp = json.loads(first_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OSError(f"Cloudium worker 응답 파싱 실패: {exc}") from exc
        if not resp.get("ok"):
            err_msg = resp.get("error", "unknown")
            # worker가 직렬화한 OS 예외를 backend에서 재현해 endpoint 핸들러와 일관성 유지
            if err_msg.startswith("FileNotFoundError"):
                raise FileNotFoundError(err_msg)
            if err_msg.startswith("PermissionError"):
                raise PermissionError(err_msg)
            raise OSError(err_msg)
        return resp.get("result")

    def _ensure_gate(self):
        """worker가 IPC ping에 응답해야 read 허용."""
        if not is_gate_running(host=self.worker_host, port=self.worker_port):
            raise PermissionError(
                f"Cloudium worker 미응답 — {self.worker_host}:{self.worker_port}.\n"
                f"  '{self.gate_process}' 를 실행하세요."
            )

    def _check_allowed(self, path: str):
        """클라우디움 경로만 허용. 로컬 경로 차단.

        deny-by-default: allowed_prefixes가 비어 있으면 전부 차단.

        **workspace bypass**: backend project_root 하위 path는 자동 통과.
        backend가 자기 workspace(reports/, .devops_pro_cache/, config/)를
        read하는 건 cloudium 권한과 무관 — Job 목록 / 분석 결과 / scm_registry
        등이 사용자 시나리오에서 차단되는 false positive 방지.

        **N16 fix**: relative path(예: `.devops_pro_cache`, `reports/jobs.json`)는
        cwd 기준으로 abs 변환 후 비교. UNC/권한 무관(os.path.abspath는 단순 join).
        사용자가 frontend body에서 relative path 보내면 workspace bypass에 누락
        되어 차단되던 N16 회귀 차단.

        **C1 수정 (Phase 4)**: backend python.exe는 cloudium 권한 없으므로
        `Path.resolve()`를 호출하지 않는다. UNC unreachable 또는 권한 부재
        경로에서 silent fail / OSError 위험을 회피하기 위해 string 정규화만
        사용. traversal 방지는 `os.path.normpath`로 `..` 처리.

        **W3 수정**: lowercase 비교는 Windows에서만 적용. case-sensitive FS
        (Linux mount SMB 등)에서 잘못된 prefix 매칭 방지.
        """
        # N16: relative path는 cwd(보통 backend 실행 디렉토리=workspace) 기준
        # abs 변환. abspath는 stat 호출 없이 string join만이라 권한 영향 0.
        if not os.path.isabs(path):
            path = os.path.abspath(path)

        normalized_path = self._normalize_for_compare(path)

        # workspace bypass: project_root 하위는 cloudium 검사 면제
        project_root = self._normalize_for_compare(str(_PROJECT_ROOT)).rstrip("/")
        if (normalized_path == project_root
                or normalized_path.startswith(project_root + "/")):
            return

        # N17: 사용자 home bypass — cache_root 등 사용자 home 안 디렉토리 자동 통과
        if _USER_HOME is not None:
            user_home_n = self._normalize_for_compare(str(_USER_HOME)).rstrip("/")
            if (normalized_path == user_home_n
                    or normalized_path.startswith(user_home_n + "/")):
                return

        if not self.allowed_prefixes:
            raise PermissionError(
                f"Cloudium 모드: allowed_prefixes 미설정 — workspace/home 외부 경로 차단됨: {path}. "
                "CLOUDIUM_ALLOWED_PREFIXES 환경변수 또는 /api/file-mode "
                "POST body에 allowed_prefixes를 명시해야 합니다."
            )
        for prefix in self.allowed_prefixes:
            normalized_prefix = self._normalize_for_compare(prefix).rstrip("/")
            if (normalized_path == normalized_prefix
                    or normalized_path.startswith(normalized_prefix + "/")):
                return
        raise PermissionError(
            f"Cloudium 모드: 허용되지 않은 경로 접근 차단됨: {path}"
        )

    @staticmethod
    def _normalize_for_compare(p: str) -> str:
        r"""W3: platform-aware 경로 정규화.
          1) backslash → forward slash
          2) os.path.normpath로 .. 처리
          3) Windows에서만 lowercase (case-insensitive FS 보정)
          4) UNC `\\server\share` 의 leading `//` 보정
        """
        n = os.path.normpath(p).replace("\\", "/")
        if sys.platform == "win32":
            n = n.lower()
        # normpath가 UNC `//server/share`의 leading `//`를 `/`로 줄이는 윈도 동작 보정
        if (p.startswith("\\\\") or p.startswith("//")) and not n.startswith("//"):
            n = "/" + n
        return n

    def _gate_then_allow(self, path: str):
        # W1: 미들웨어가 이미 검증한 path 집합에 포함되면 ping/whitelist 생략.
        # 다중 사용자/다중 path 환경에서 매 요청 ms 단위 누적 비용 회피.
        # **W4 fix**: 과거 단일 path만 비교 → 다중 path frozenset 멤버십.
        already = _path_already_validated.get()
        if already is not None and path in already:
            return
        self._ensure_gate()
        self._check_allowed(path)

    def check_access(self, path: str) -> None:
        """게이트 + 화이트리스트 검사 — public API.

        외부 layer(미들웨어, 라우터)가 read 직전 호출할 수 있는 명시 인터페이스.
        실패 시 PermissionError raise. 성공 시 반환 None.
        """
        self._gate_then_allow(path)

    # ── Read ops — worker IPC 위임 ─────────────────────────────────────
    def exists(self, path: str) -> bool:
        self._gate_then_allow(path)
        return bool(self._ipc_call("exists", {"path": path}))

    def is_file(self, path: str) -> bool:
        self._gate_then_allow(path)
        return bool(self._ipc_call("is_file", {"path": path}))

    def is_dir(self, path: str) -> bool:
        self._gate_then_allow(path)
        return bool(self._ipc_call("is_dir", {"path": path}))

    # 청킹 단위: 4MB. 너무 작으면 round-trip 누적, 너무 크면 base64 인코딩 후
    # JSON 한 줄에서 socket buffer 부담. 4MB는 base64 후 ~5.4MB로 일반 OS
    # buffer/메모리 부담 적은 sweet spot.
    _CHUNK_SIZE = 4 * 1024 * 1024

    def read_bytes(self, path: str) -> bytes:
        """worker IPC로 파일 read. 큰 파일은 4MB chunk로 누적 read하여 OOM 방지.

        **W5 수정**: 옛 worker가 plain base64 string을 반환하던 backward-compat은
        4MB 이후 silent truncation 위험이 있어 차단. dict가 아닌 응답은 명시
        PermissionError raise해 사용자에게 worker 재시작을 안내.
        """
        self._gate_then_allow(path)
        offset = 0
        chunks: List[bytes] = []
        while True:
            resp = self._ipc_call("read_bytes",
                                  {"path": path, "offset": offset,
                                   "length": self._CHUNK_SIZE},
                                  timeout=60.0)
            if not isinstance(resp, dict):
                raise PermissionError(
                    "Cloudium worker가 chunking protocol(v2)을 지원하지 않습니다. "
                    "최신 worker(excel_rename_gui_v2.exe)를 재시작하세요."
                )
            data_b64 = resp.get("data", "") or ""
            chunk = base64.b64decode(data_b64) if data_b64 else b""
            chunks.append(chunk)
            if resp.get("eof") or not chunk:
                break
            offset += len(chunk)
        return b"".join(chunks)

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        self._gate_then_allow(path)
        result = self._ipc_call("read_text", {"path": path, "encoding": encoding})
        return result if isinstance(result, str) else ""

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False) -> List[str]:
        self._gate_then_allow(path)
        result = self._ipc_call("list_dir",
                                {"path": path, "pattern": pattern, "recursive": recursive})
        return list(result) if isinstance(result, list) else []

    # X5: read-only invariant — 명시적 write 차단 메서드.
    # 시그너처는 LocalFileResolver의 미래 write 메서드 후보와 일치시켜 정적
    # 검사기(mypy/Pyright)가 시그너처 mismatch를 감지할 수 있게 한다.
    # *args/**kwargs로 흡수하면 silent 통과되므로 명시 시그너처 사용.
    def write_text(self, path: str, data: str, encoding: str = "utf-8") -> None:
        raise PermissionError("Cloudium 모드는 read-only입니다. write_text 차단.")

    def write_bytes(self, path: str, data: bytes) -> None:
        raise PermissionError("Cloudium 모드는 read-only입니다. write_bytes 차단.")

    def delete(self, path: str) -> None:
        raise PermissionError("Cloudium 모드는 read-only입니다. delete 차단.")

    def remove(self, path: str) -> None:
        raise PermissionError("Cloudium 모드는 read-only입니다. remove 차단.")

    def unlink(self, path: str) -> None:
        raise PermissionError("Cloudium 모드는 read-only입니다. unlink 차단.")

    def append(self, path: str, data: str, encoding: str = "utf-8") -> None:
        raise PermissionError("Cloudium 모드는 read-only입니다. append 차단.")

    # ── Browse ops — worker tkinter 다이얼로그 위임 ──────────────────────
    def browse_file(self, title: str = "", initialdir: str = "") -> str:
        """worker GUI에서 파일 선택 다이얼로그를 띄움 — Cloudium 권한으로 클라우디움 폴더 탐색 가능."""
        result = self._ipc_call("browse_file",
                                {"title": title, "initialdir": initialdir},
                                timeout=600.0)
        return result if isinstance(result, str) else ""

    def browse_directory(self, title: str = "", initialdir: str = "") -> str:
        result = self._ipc_call("browse_directory",
                                {"title": title, "initialdir": initialdir},
                                timeout=600.0)
        return result if isinstance(result, str) else ""

    @property
    def mode(self) -> str:
        return "cloudium"

    def get_config(self) -> Dict[str, Any]:
        return {
            "mode": "cloudium",
            "allowed_prefixes": self.allowed_prefixes,
            "gate_process": self.gate_process,
            "gate_running": is_gate_running(host=self.worker_host, port=self.worker_port),
            "worker_host": self.worker_host,
            "worker_port": self.worker_port,
            "read_only": True,
        }

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_resolver: Optional[FileResolver] = None


def get_resolver() -> FileResolver:
    global _resolver
    if _resolver is None:
        mode = os.getenv("DEVOPS_FILE_MODE", "local").strip().lower()
        if mode == "cloudium":
            _resolver = CloudiumFileResolver()
        else:
            _resolver = LocalFileResolver()
        _logger.info("File resolver: mode=%s", _resolver.mode)
    return _resolver


def set_resolver(resolver: FileResolver) -> None:
    """싱글톤 resolver 강제 교체 — 테스트/내부 전용.

    프로덕션 코드는 switch_mode를 사용해야 한다. 본 함수는 __all__에서 제외되어
    `from file_resolver import *`로 가져올 수 없다.

    caller frame 수집(inspect.stack)은 INFO 레벨이 켜져 있을 때만 수행한다 —
    async loop 안에서 빈번 호출 시 ms × N 누적 비용 회피.
    """
    global _resolver
    invalidate_gate_cache()
    _resolver = resolver
    if _logger.isEnabledFor(logging.INFO):
        # INFO 활성 시에만 frame 수집 — 운영 추적용 caller 정보
        try:
            import inspect
            frame = inspect.stack()[1]
            caller = f"{frame.filename}:{frame.lineno} in {frame.function}"
        except (IndexError, OSError):
            caller = "unknown"
        _logger.info("File resolver changed: mode=%s caller=%s", resolver.mode, caller)


def switch_mode(mode: str, **kwargs) -> FileResolver:
    """모드 전환 — 프로덕션 public API."""
    if mode == "cloudium":
        resolver = CloudiumFileResolver(**{k: v for k, v in kwargs.items()
                                           if k in ('allowed_prefixes', 'gate_process')})
    else:
        resolver = LocalFileResolver()
    set_resolver(resolver)
    return resolver
