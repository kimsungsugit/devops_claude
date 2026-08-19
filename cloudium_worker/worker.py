"""Cloudium worker — GUI process + TCP IPC server.

Cloudium grants permissions to GUI subsystem processes matching the
trusted name (`excel_rename_gui_v2.exe`). Backend Python (separate
process) does NOT inherit those permissions, so file reads must be
delegated to this worker via TCP.

Architecture:
  Main thread:  tkinter GUI window (kept open while service is needed).
                Closing the window terminates the worker.
  Worker thread: localhost TCP JSON-line server. Backend connects as
                 client and sends ops; worker executes them with its
                 own (Cloudium-granted) authority and returns results.

Protocol (JSON lines, one message per line):
  Request:  {"id": "<uuid>", "op": "<name>", "args": {...}}
  Response: {"id": "<uuid>", "ok": true, "result": ...} or
            {"id": "<uuid>", "ok": false, "error": "<msg>"}

Ops:
  ping              ()                                 -> "pong"
  version           ()                                 -> str
  read_text         (path, encoding="utf-8")           -> str
  read_bytes        (path)                             -> base64-encoded str
  exists            (path)                             -> bool
  is_file           (path)                             -> bool
  is_dir            (path)                             -> bool
  list_dir          (path, pattern="*", recursive=False) -> [str]
  browse_file       (title="", initialdir="")          -> str or ""
  browse_directory  (title="", initialdir="")          -> str or ""
"""
from __future__ import annotations

import base64
import json
import os
import queue
import socket
import socketserver
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict

WORKER_VERSION = "1.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


# ---------------------------------------------------------------------------
# Op handlers — called from worker thread; results returned to client
# ---------------------------------------------------------------------------
def _op_ping(_args: Dict[str, Any]) -> str:
    return "pong"


def _op_version(_args: Dict[str, Any]) -> str:
    return WORKER_VERSION


def _op_read_text(args: Dict[str, Any]) -> str:
    path = args["path"]
    encoding = args.get("encoding", "utf-8")
    return Path(path).read_text(encoding=encoding, errors="replace")


def _op_read_bytes(args: Dict[str, Any]) -> Dict[str, Any]:
    """청킹 read — offset/length로 부분 읽기 지원.

    - offset 미지정 시 0
    - length 미지정 시 전체 read (단 backend가 큰 파일은 chunk 호출해야)
    - 응답: {data: base64, size: total_file_size, eof: bool}
    """
    path = args["path"]
    offset = int(args.get("offset", 0))
    length = args.get("length")
    p = Path(path)
    total = p.stat().st_size
    with p.open("rb") as f:
        if offset:
            f.seek(offset)
        if length is None or int(length) <= 0:
            chunk = f.read()
        else:
            chunk = f.read(int(length))
    eof = (offset + len(chunk)) >= total
    return {
        "data": base64.b64encode(chunk).decode("ascii"),
        "size": total,
        "eof": eof,
    }


def _op_exists(args: Dict[str, Any]) -> bool:
    # Python 3.6+ Path.exists는 일부 OSError(EACCES 등)를 swallow하지만
    # WinError 5는 노출될 수 있어 명시 catch — 권한 거부는 "없음"이 아니라
    # "접근 거부"이므로 PermissionError로 raise하여 backend가 구분 가능하게 한다.
    try:
        return Path(args["path"]).exists()
    except PermissionError:
        raise
    except OSError:
        return False


def _op_is_file(args: Dict[str, Any]) -> bool:
    try:
        return Path(args["path"]).is_file()
    except PermissionError:
        raise
    except OSError:
        return False


def _op_is_dir(args: Dict[str, Any]) -> bool:
    try:
        return Path(args["path"]).is_dir()
    except PermissionError:
        raise
    except OSError:
        return False


def _op_list_dir(args: Dict[str, Any]) -> list:
    """list_dir — 파일/디렉토리 반환.

    Args:
        path: 대상 디렉토리
        pattern: glob 패턴 (default "*")
        recursive: True면 rglob (모든 하위 트리), False면 즉시 자식만
        include_dirs: True면 디렉토리도 결과에 포함 (default False — backward compat)

    이전(72차 이전): file만 반환 → 호출자(file_resolver inspect_real_logs_recursive 등)가
    `is_dir()` 추가 검사로 디렉토리 enumerate 시도해도 항상 0개. FileReName 프로그램이
    `os.walk` 패턴으로 하위 트리 전체를 자유 탐색하는 것과 일관성 부재.

    72차 fix: include_dirs=True 명시 시 디렉토리도 함께 반환. 기존 호출자(default
    False)는 영향 0. 자동 latest release 탐색 (swut_input_adapter.py 38차 C2 주석에서
    "worker 버전이 디렉토리 반환하면 동작" 명시) + 사용자 inspect/탐색 시나리오 충족.
    """
    path = args["path"]
    pattern = args.get("pattern", "*")
    recursive = bool(args.get("recursive", False))
    include_dirs = bool(args.get("include_dirs", False))
    p = Path(path)
    if not p.is_dir():
        return []
    iterator = p.rglob(pattern) if recursive else p.glob(pattern)
    if include_dirs:
        return [str(f) for f in iterator]
    return [str(f) for f in iterator if f.is_file()]


# Dialog ops dispatch to the GUI thread via the dialog queue (tkinter is
# not thread-safe; only the main thread can show dialogs).
_dialog_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue()


def _op_browse_file(args: Dict[str, Any]) -> str:
    return _dispatch_dialog({"kind": "file", **args})


def _op_browse_directory(args: Dict[str, Any]) -> str:
    return _dispatch_dialog({"kind": "directory", **args})


def _dispatch_dialog(req: Dict[str, Any]) -> str:
    """Send dialog request to GUI thread and wait for selection."""
    reply: "queue.Queue[str]" = queue.Queue()
    req["_reply"] = reply
    _dialog_queue.put(req)
    try:
        return reply.get(timeout=300)  # 5 minutes max
    except queue.Empty:
        return ""


_OPS = {
    "ping": _op_ping,
    "version": _op_version,
    "read_text": _op_read_text,
    "read_bytes": _op_read_bytes,
    "exists": _op_exists,
    "is_file": _op_is_file,
    "is_dir": _op_is_dir,
    "list_dir": _op_list_dir,
    "browse_file": _op_browse_file,
    "browse_directory": _op_browse_directory,
}


# ---------------------------------------------------------------------------
# TCP server — JSON line protocol
# ---------------------------------------------------------------------------
_LOOPBACK_IPS = ("127.0.0.1", "::1", "::ffff:127.0.0.1")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        # **W6 fix**: loopback 외 IP 거부 (default). LAN 노출이 필요하면 명시
        # CLOUDIUM_WORKER_ALLOW_LAN=1 opt-in. backend가 외부 host로 bind되어
        # 있어도 다른 PC가 worker에 임의 path read 요청 보내는 것 차단.
        client_ip = self.client_address[0] if self.client_address else ""
        if (client_ip not in _LOOPBACK_IPS
                and os.environ.get("CLOUDIUM_WORKER_ALLOW_LAN", "0") != "1"):
            try:
                self._send({"id": None, "ok": False,
                            "error": f"client IP not allowed: {client_ip}"})
            except Exception:
                pass
            return
        while True:
            try:
                line = self.rfile.readline()
            except (ConnectionResetError, OSError):
                return
            if not line:
                return
            try:
                req = json.loads(line.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send({"id": None, "ok": False, "error": f"invalid_json: {exc}"})
                continue
            req_id = req.get("id")
            op_name = req.get("op", "")
            handler = _OPS.get(op_name)
            if handler is None:
                self._send({"id": req_id, "ok": False, "error": f"unknown_op: {op_name}"})
                continue
            try:
                result = handler(req.get("args", {}) or {})
                self._send({"id": req_id, "ok": True, "result": result})
            except FileNotFoundError as exc:
                self._send({"id": req_id, "ok": False, "error": f"FileNotFoundError: {exc}"})
            except PermissionError as exc:
                self._send({"id": req_id, "ok": False, "error": f"PermissionError: {exc}"})
            except OSError as exc:
                self._send({"id": req_id, "ok": False, "error": f"OSError: {exc}"})
            except Exception as exc:  # noqa: BLE001 — IPC protocol에서 모든 예외 직렬화
                self._send({"id": req_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})

    def _send(self, msg: Dict[str, Any]):
        line = json.dumps(msg, ensure_ascii=False) + "\n"
        try:
            self.wfile.write(line.encode("utf-8"))
            self.wfile.flush()
        except (ConnectionResetError, OSError):
            pass


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True

    # ⚠ **Windows 에서 SO_REUSEADDR 은 POSIX 와 뜻이 다르다.** 재시작 편의가 아니라
    #   **남이 이미 바인딩한 포트를 가로챌 수 있게** 한다. 켜 두면 두 방향 다 뚫린다.
    #
    #   2026-08-19 실증(사고가 아니라 실제로 일으켰다): 두 번째 프로세스가 **살아 있는
    #   워커의 포트를 뺏어** `netstat` 에 리스너가 둘이 됐다. 뺏은 쪽은 Cloudium 권한이
    #   없으므로 그리로 간 요청은 조용히 실패한다 — 게이트는 초록인데 파일만 안 읽힌다.
    #
    #   끄면 손해가 있을 줄 알았는데 **재보니 없었다**(같은 트리 실측):
    #
    #       설정                A 가로채기 차단   B 즉시 재바인딩
    #       REUSEADDR(옛판)     ❌ 뚫림           ✅ 된다
    #       **끔(현행)**        ✅ 차단(10048)    ✅ 된다
    #       EXCLUSIVEADDRUSE    ✅ 차단(10048)    ✅ 된다
    #
    #   상대가 REUSEADDR 로 들어오는 비대칭 케이스도 끄기만 하면 막힌다(상대가 10013).
    #   `SO_EXCLUSIVEADDRUSE` 는 그 위에 얹어도 **관측되는 이득이 0** 이라 안 쓴다 —
    #   죽은 방어를 넣으면 뮤테이션이 통째로 살아남는다.
    #
    #   덤: 진짜 충돌일 때 에러가 10013("액세스 권한") 대신 **10048("포트 사용 중")**
    #   으로 바뀌어 원인이 바로 읽힌다.
    #
    #   ⚠ 이 값은 `dist/excel_rename_gui_v2.exe` 를 **다시 빌드해야** 반영된다.
    allow_reuse_address = False


def bind_failure_message(host: str, port: int, exc: OSError) -> str:
    """바인딩 실패를 **사람이 읽을 수 있는 말**로. 트레이스백만 내면 오독한다.

    Windows 에서 이 상황의 에러 코드는 두 가지로 갈린다:

      · 10048 WSAEADDRINUSE  "포트 사용 중"          ← 현행(REUSEADDR 끔)
      · 10013 WSAEACCES      "액세스 권한…"          ← 옛 판(REUSEADDR 켬)일 때

    옛 판이 문제였다 — **포트 충돌인데 권한 문제로 읽힌다**(2026-08-19 실사고:
    무관한 앱이 8765 를 점유해 이 경로로 죽었고, 로그만 보고 권한을 의심하느라
    진단이 한참 헛돌았다). 지금은 위 `_ThreadingTCPServer` 가 REUSEADDR 을 끄므로
    10048 이 나지만, **이미 배포된 exe 는 옛 판**이라 10013 도 계속 들어온다.
    둘 다 같은 안내로 받는다.
    """
    code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    hint = ""
    if code in (10013, 10048, 98, 13):
        hint = (
            f"\n\n포트 {port} 를 **다른 프로세스가 이미 쓰고 있습니다.**\n"
            f"(WinError 10013 '액세스 권한' 으로 보이더라도 권한 문제가 아니라 포트 충돌입니다)\n\n"
            f"확인:  netstat -ano | findstr \":{port} \"\n"
            f"해결1: 그 PID 프로세스를 종료\n"
            f"해결2: 저장소 .env 의 CLOUDIUM_WORKER_PORT 를 빈 포트로 바꾸고 백엔드 재기동"
        )
    return f"Cloudium Worker 를 {host}:{port} 에 열 수 없습니다.\n{exc}{hint}"


def _start_tcp_server(host: str, port: int) -> _ThreadingTCPServer:
    server = _ThreadingTCPServer((host, port), _Handler)
    t = threading.Thread(target=server.serve_forever, name="cloudium_tcp", daemon=True)
    t.start()
    return server


# ---------------------------------------------------------------------------
# GUI main loop
# ---------------------------------------------------------------------------
def _run_gui(host: str, port: int) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        # tkinter 미설치 (headless) — 백그라운드만으로 동작
        try:
            srv = _start_tcp_server(host, port)
        except OSError as exc:
            print(bind_failure_message(host, port, exc), file=sys.stderr)
            return 2
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            srv.shutdown()
        return 0

    try:
        server = _start_tcp_server(host, port)
    except OSError as exc:
        # ⚠ 이 exe 는 `--noconsole` GUI 다 — **print 는 아무 데도 안 보인다.**
        #   트레이스백만 남기면 사용자는 "그냥 안 켜진다" 로 겪는다. 대화상자로 알린다.
        msg = bind_failure_message(host, port, exc)
        try:
            _err_root = tk.Tk()
            _err_root.withdraw()
            messagebox.showerror("Cloudium Worker - 기동 실패", msg)
            _err_root.destroy()
        except Exception:  # noqa: BLE001  # silent-ok
            # 대화상자를 못 띄우는 상황(디스플레이 없음 등)에서도 **아래 stderr 출력은
            # 반드시 나간다** — 삼키는 게 아니라 보고 경로가 둘이고 하나가 실패한 것.
            pass
        print(msg, file=sys.stderr)
        return 2

    root = tk.Tk()
    root.title("Excel Rename GUI v2 - Cloudium Worker")
    root.geometry("480x260")
    try:
        root.attributes("-topmost", True)
        root.after(800, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Cloudium Worker", font=("Segoe UI", 14, "bold")).pack(pady=(0, 6))
    ttk.Label(frame, text=f"PID: {os.getpid()}    Listen: {host}:{port}",
              foreground="gray").pack()
    ttk.Label(
        frame,
        text="이 창이 떠있는 동안 backend가 클라우디움 파일을 읽을 수 있습니다.\n"
             "창을 닫으면 권한이 사라집니다.",
        wraplength=420, justify="center",
    ).pack(pady=10)

    status_var = tk.StringVar(value="대기 중")
    ttk.Label(frame, textvariable=status_var, foreground="darkgreen").pack(pady=4)

    def pick_file_test():
        try:
            path = filedialog.askopenfilename(title="Cloudium 파일 선택 테스트")
            if path:
                messagebox.showinfo("선택됨", f"선택된 파일:\n{path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("오류", str(exc))

    ttk.Button(frame, text="파일 선택 다이얼로그 테스트", command=pick_file_test).pack(pady=4)

    # GUI thread polls the dialog queue every 100ms — when backend asks
    # for a dialog via IPC, we open it here in the main thread.
    def _poll_dialog_queue():
        try:
            while True:
                req = _dialog_queue.get_nowait()
                kind = req.get("kind")
                title = req.get("title") or ("파일 선택" if kind == "file" else "폴더 선택")
                initialdir = req.get("initialdir") or ""
                reply = req.get("_reply")
                if reply is None:
                    continue
                try:
                    if kind == "file":
                        path = filedialog.askopenfilename(title=title, initialdir=initialdir or None)
                    else:
                        path = filedialog.askdirectory(title=title, initialdir=initialdir or None)
                    reply.put(path or "")
                    if path:
                        status_var.set(f"선택됨: {Path(path).name}")
                except Exception as exc:  # noqa: BLE001
                    reply.put("")
                    status_var.set(f"다이얼로그 오류: {exc}")
        except queue.Empty:
            pass
        finally:
            root.after(100, _poll_dialog_queue)

    root.after(100, _poll_dialog_queue)

    def on_close():
        try:
            server.shutdown()
        except Exception:  # noqa: BLE001
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


def main(argv: list[str]) -> int:
    host = os.environ.get("CLOUDIUM_WORKER_HOST", DEFAULT_HOST)
    try:
        port = int(os.environ.get("CLOUDIUM_WORKER_PORT", DEFAULT_PORT))
    except ValueError:
        port = DEFAULT_PORT

    if len(argv) >= 2 and argv[1] == "--port":
        # Probe mode — bind/unbind to verify port is available
        try:
            s = socket.socket()
            s.bind((host, port))
            s.close()
            print(f"available {host}:{port}")
            return 0
        except OSError as exc:
            print(f"unavailable {host}:{port} {exc}", file=sys.stderr)
            return 1

    return _run_gui(host, port)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
