"""Cloudium worker — minimal Tk GUI for permission gate.

Built with PyInstaller --noconsole (console=False) to match the GUI
subsystem pattern of Cloudium-trusted apps (e.g. excel_rename_gui_v2 v7.0,
which is a tkinter GUI tool).

Hypothesis: Cloudium grants permissions based on the exe name + GUI
subsystem signature. A console-mode build is recognized as a different
process class and may be rejected.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        # tkinter 미설치 환경 (희귀) — silent exit
        return 1

    root = tk.Tk()
    root.title("Excel Rename GUI v2 — Cloudium Worker")
    root.geometry("440x220")
    try:
        root.attributes("-topmost", True)
        root.after(500, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass

    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Cloudium Worker", font=("Segoe UI", 14, "bold")).pack(pady=(0, 6))
    ttk.Label(frame, text=f"PID: {os.getpid()}", foreground="gray").pack()
    ttk.Label(
        frame,
        text="Cloudium 권한 부여 게이트.\nbackend가 이 프로세스의 권한으로 파일을 read합니다.",
        wraplength=400, justify="center",
    ).pack(pady=10)

    def pick_file_test():
        try:
            path = filedialog.askopenfilename(title="Cloudium 파일 선택 테스트")
            if path:
                messagebox.showinfo("선택됨", f"선택된 파일:\n{path}")
            else:
                messagebox.showinfo("취소", "선택 취소됨")
        except Exception as exc:
            messagebox.showerror("오류", str(exc))

    btn = ttk.Button(frame, text="파일 선택 다이얼로그 테스트", command=pick_file_test)
    btn.pack(pady=4)

    def on_close():
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
