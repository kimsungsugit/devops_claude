from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(r"D:\Project\devops\260105")
    script = root / "tools" / "generate_uds_local.py"
    env = dict(os.environ)
    env["UDS_RESUME_LAST"] = "1"
    cmd = [sys.executable, "-u", str(script)]
    run = subprocess.run(cmd, cwd=str(root), env=env, check=False)
    if run.returncode != 0:
        raise SystemExit(run.returncode)


if __name__ == "__main__":
    main()
