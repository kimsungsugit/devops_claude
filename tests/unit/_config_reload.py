"""`config` 를 **이 저장소의 파일로** 다시 실행한다 — `importlib.reload` 대신.

(R30 리뷰 I7 2차 원인, 2026-09-04) `tools/generate_uds_local.py` 는 import 시점에 `sys.path[0]` 에 외부 트리
`D:/Project/devops/260105` 를 꽂는다. 그 뒤 `importlib.reload(config)` 는 spec 을 **sys.path 로 다시 찾아**
그 트리의 `config.py` 를 실행하고, 이 저장소 config 에만 있는 속성(`UDS_SIDECAR_GATE_THRESHOLDS` 등)은 옛 값
그대로 남는다 → "env 를 0.99 로 넣고 reload 했는데 0.7" 이 선택 실행(`-k …uds…`)에서만 재현됐다.

여기서는 모듈 객체에 붙어 있는 `__spec__.loader` 로 **같은 파일**을 다시 실행한다 — sys.path 상태와 무관하다.
"""
from __future__ import annotations

import importlib
import sys
import types


def reexec_config() -> types.ModuleType:
    """`sys.modules["config"]` 가 실 모듈이면 그 파일을 재실행해 돌려준다. 아니면(스텁) 실 모듈을 새로 올린다."""
    mod = sys.modules.get("config")
    spec = getattr(mod, "__spec__", None) if isinstance(mod, types.ModuleType) else None
    if mod is not None and spec is not None and spec.loader is not None:
        spec.loader.exec_module(mod)
        return mod
    sys.modules.pop("config", None)
    return importlib.import_module("config")
