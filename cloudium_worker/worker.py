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
    path = args["path"]
    pattern = args.get("pattern", "*")
    recursive = bool(args.get("recursive", False))
    p = Path(path)
    if not p.is_dir():
        return []
    if recursive:
        return [str(f) for f in p.rglob(pattern) if f.is_file()]
    return [str(f) for f in p.glob(pattern) if f.is_file()]


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
    allow_reuse_address = True


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
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        # tkinter 미설치 (headless) — 백그라운드만으로 동작
        srv = _start_tcp_server(host, port)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            srv.shutdown()
        return 0

    server = _start_tcp_server(host, port)

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
