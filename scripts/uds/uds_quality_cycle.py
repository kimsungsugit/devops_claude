from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi.testclient import TestClient

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.main import app


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_user(explicit: str = "") -> str:
    """토큰을 발급할 사용자. 없으면 `config/admin_users.json` 의 첫 admin."""
    if explicit.strip():
        return explicit.strip()
    try:
        data = json.loads((repo_root / "config" / "admin_users.json").read_text(encoding="utf-8"))
        admins = data.get("admins") or []
        if admins:
            return str(admins[0])
    except Exception:                              # noqa: BLE001 - 아래에서 사유를 낸다
        pass
    raise SystemExit(
        "[ERROR] 토큰을 발급할 사용자를 못 정했다. `--user <이름>` 으로 지정하거나 "
        "config/admin_users.json 에 admin 을 등록할 것."
    )


def _auth_headers(username: str) -> Dict[str, str]:
    """실제 Bearer 토큰을 발급해 단다.

    ⚠ 없으면 **전부 401 이다.** 커밋 `1b6bb99`(2026-08-04)가 `X-User` 단독 신원을
    막았다. 그 뒤로 이 러너는 한 번도 성공한 적이 없는데, `_run_once` 가 401 응답을
    그대로 담고 `main()` 이 그걸 **베이스라인으로 저장**해 exit 0 을 냈다 —
    저장소에 남은 최신 베이스라인이 2026-02 인 이유다.

    `DEV_MODE_X_USER_FALLBACK` 같은 개발용 우회에 기대지 않는다. 그 폴백은 언제든
    꺼질 수 있고, 꺼지면 여기가 다시 조용히 401 을 기록한다.

    ⚠ `token_version` 을 **저장소에서 읽는다.** 0 으로 가정하면 로그아웃/비밀번호
    변경으로 버전이 오르는 순간 `TOKEN_REVOKED` 로 조용히 401 이 된다. 사용자가 아예
    없으면 `USER_REVOKED` 라 인증이 성립하지 않으므로 여기서 먼저 막는다.
    """
    from backend.services.auth_service import create_access_token
    from backend.services.users import get_user

    record = get_user(username)
    if not record:
        raise SystemExit(
            f"[ERROR] 사용자 {username!r} 가 없다 — 그 토큰은 USER_REVOKED 로 거부된다. "
            "`--user` 로 실재하는 사용자를 지정할 것."
        )
    tv = int(record.get("token_version", 0))
    token = create_access_token(username, token_version=tv)
    return {"Authorization": f"Bearer {token}"}


def _run_once(args: argparse.Namespace) -> Dict[str, Any]:
    client = TestClient(app, headers=_auth_headers(_resolve_user(getattr(args, "user", ""))))
    data: Dict[str, Any] = {
        "source_root": args.source_root,
        "req_paths": args.req_paths,
        "report_dir": args.report_dir,
        "doc_only": "false" if args.full else "true",
        "test_mode": "true" if args.test_mode else "false",
        "ai_enable": "true" if args.ai_enable else "false",
        "expand": "true" if args.expand else "false",
        "ai_detailed": "true" if args.ai_detailed else "false",
        "call_relation_mode": "code",
        "rag_top_k": str(args.rag_top_k),
        "globals_format_with_labels": "true",
    }
    files = None
    if args.template:
        tpl_path = Path(args.template)
        files = {
            "template_file": (
                tpl_path.name,
                tpl_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
    res = client.post("/api/local/uds/generate", data=data, files=files)
    payload = {"status_code": res.status_code}
    try:
        payload["response"] = res.json()
    except Exception:
        payload["response"] = {"raw": res.text}
    payload["executed_at"] = datetime.now().isoformat(timespec="seconds")
    payload["input_fingerprint"] = _fingerprint_inputs(args)
    return payload


def _fingerprint_inputs(args: argparse.Namespace) -> str:
    raw = {
        "source_root": str(args.source_root or ""),
        "req_paths": str(args.req_paths or ""),
        "report_dir": str(args.report_dir or ""),
        "template": str(args.template or ""),
        "test_mode": bool(args.test_mode),
        "full": bool(args.full),
        "ai_enable": bool(args.ai_enable),
        "expand": bool(args.expand),
        "ai_detailed": bool(args.ai_detailed),
        "rag_top_k": int(args.rag_top_k or 12),
    }
    text = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# 표시 순서(필터 아님 — `_compare` 는 합집합을 본다). 게이트 7축 → 참고축 순.
_ORDERED_RATE_KEYS = [
    "called_fill", "calling_fill", "input_fill", "output_fill",
    "description_fill", "asil_fill", "related_fill",
    "input_real_fill", "output_real_fill",
    "global_fill", "static_fill",
    "description_trusted_fill", "asil_trusted_fill", "related_trusted_fill",
]


def _artifact_fidelity(run: Dict[str, Any]) -> Dict[str, Any]:
    """산출물 충실도 — **문서에 실제로 들어간 함수 수**.

    게이트 rates 는 전부 payload 를 재므로, payload 가 완벽하면 문서가 비어 있어도
    만점이 나온다(실측: run 660·661 = 반영 0/5 인데 점수 100.0). 그 축이 응답 본문에는
    없고 라이터가 남기는 sidecar 에만 있어서, 여기서 산출물 경로로 되읽는다.

    `measured=False` 는 **미측정**이다 — 반영률 0% 와 섞으면 안 된다.
    """
    out = str(((run.get("response") or {}).get("path")) or "")
    if not out:
        return {"measured": False, "reason": "응답에 산출물 경로가 없다"}
    side = Path(out + ".gen_stats.json")
    if not side.exists():
        return {"measured": False, "reason": f"sidecar 없음: {side.name}"}
    try:
        st = json.loads(side.read_text(encoding="utf-8"))
    except Exception as exc:                       # noqa: BLE001 - 미측정으로 보고한다
        return {"measured": False, "reason": f"sidecar 파싱 실패: {exc}"}
    total, matched = st.get("payload_functions"), st.get("matched_functions")
    if not isinstance(total, int) or total <= 0 or not isinstance(matched, int):
        return {"measured": False, "reason": f"분모/분자 없음(payload={total!r}, matched={matched!r})"}
    return {
        "measured": True,
        "payload_functions": total,
        "matched_functions": matched,
        "artifact_match_pct": round((matched / total) * 100.0, 1),
        "unmatched_payload_count": st.get("unmatched_payload_count"),
        "empty_heading_count": st.get("empty_heading_count"),
    }


def _compare(prev: Dict[str, Any], cur: Dict[str, Any]) -> Dict[str, Any]:
    p_gate = (((prev.get("response") or {}).get("quick_quality_gate") or {}).get("rates") or {})
    c_gate = (((cur.get("response") or {}).get("quick_quality_gate") or {}).get("rates") or {})
    p_counts = (((prev.get("response") or {}).get("quick_quality_gate") or {}).get("counts") or {})
    c_counts = (((cur.get("response") or {}).get("quick_quality_gate") or {}).get("counts") or {})
    # ⚠ 예전엔 여기에 축 12개가 **하드코딩**돼 있었다. 생산자에 축을 더해도 이 목록에
    #   안 적으면 러너가 조용히 빼먹는다 — 실제로 `input_real_fill`/`output_real_fill`
    #   (실질 인터페이스 채움)이 그렇게 누락된 채였다. 이제 **양쪽 rates 의 합집합**을
    #   본다: 새 축은 자동으로 따라오고, 사라진 축도 prev 쪽에 남아 보인다.
    #   `_ORDERED_RATE_KEYS` 는 표시 순서일 뿐 필터가 아니다.
    seen = set(p_gate) | set(c_gate)
    keys = [k for k in _ORDERED_RATE_KEYS if k in seen] + sorted(seen - set(_ORDERED_RATE_KEYS))
    delta: Dict[str, Any] = {}
    for key in keys:
        p = float(p_gate.get(key) or 0.0)
        c = float(c_gate.get(key) or 0.0)
        row = {"prev": p, "cur": c, "delta": round(c - p, 1)}
        # 한쪽에만 있는 축은 "0.0 이었다" 가 아니라 **미측정**이다. 이걸 구분하지 않으면
        # 새 축이 들어온 라운드마다 "+18.9 개선" 같은 거짓 델타가 찍힌다.
        if key not in p_gate or key not in c_gate:
            row["delta"] = None
            row["note"] = "prev 에만 있음" if key not in c_gate else "cur 에만 있음(신규 축)"
        delta[key] = row
    prev_codes = set((((prev.get("response") or {}).get("quality_evaluation") or {}).get("reason_codes") or []))
    cur_codes = set((((cur.get("response") or {}).get("quality_evaluation") or {}).get("reason_codes") or []))
    soft_fail_reasons = []
    hard_fail_reasons = []
    for metric_name, row in delta.items():
        if float(row.get("delta") or 0.0) < -3.0:
            soft_fail_reasons.append(f"REGRESSION_{metric_name.upper()}")
    if len(cur_codes - prev_codes) > 0:
        soft_fail_reasons.append("NEW_REASON_CODES")
    cur_status = int(cur.get("status_code") or 0)
    cur_total = int(c_counts.get("total_functions") or 0)
    if cur_status != 200:
        hard_fail_reasons.append("STATUS_NOT_200")
    if cur_total <= 0:
        hard_fail_reasons.append("NO_FUNCTIONS")
    prev_fp = str(prev.get("input_fingerprint") or "")
    cur_fp = str(cur.get("input_fingerprint") or "")
    return {
        "prev_status": prev.get("status_code"),
        "cur_status": cur_status,
        "prev_gate_pass": (((prev.get("response") or {}).get("quality_evaluation") or {}).get("gate_pass")),
        "cur_gate_pass": (((cur.get("response") or {}).get("quality_evaluation") or {}).get("gate_pass")),
        "input_fingerprint_match": bool(prev_fp and cur_fp and prev_fp == cur_fp),
        "counts": {
            "prev": p_counts,
            "cur": c_counts,
        },
        "rates": delta,
        "reason_codes": {
            "prev": sorted(prev_codes),
            "cur": sorted(cur_codes),
            "added": sorted(cur_codes - prev_codes),
            "removed": sorted(prev_codes - cur_codes),
        },
        "artifact_fidelity": {"prev": _artifact_fidelity(prev), "cur": _artifact_fidelity(cur)},
        "hard_fail": bool(len(hard_fail_reasons) > 0),
        "hard_fail_reasons": hard_fail_reasons,
        "soft_fail": bool(len(soft_fail_reasons) > 0),
        "soft_fail_reasons": soft_fail_reasons,
    }


def _unusable_reasons(run: Dict[str, Any]) -> list:
    """베이스라인/비교로 쓸 수 없는 사유. 비어 있으면 쓸 수 있다.

    ⚠ 예전엔 `main()` 이 응답을 **검사 없이** 베이스라인으로 저장했다. 그래서 401
    응답이 `[baseline] created` + exit 0 으로 기록됐고, 이후 모든 비교가 그 거짓
    기준선 위에서 돌았다. 미측정을 기준선으로 바꾸는 것이 이 저장소가 반복해 고쳐 온
    fail-open 이다.
    """
    reasons = []
    status = int(run.get("status_code") or 0)
    if status != 200:
        err = ((run.get("response") or {}).get("error") or {})
        detail = err.get("message") or err.get("code") or ""
        reasons.append(f"HTTP {status}" + (f" — {detail}" if detail else ""))
    qg = ((run.get("response") or {}).get("quick_quality_gate") or {})
    total = int((qg.get("counts") or {}).get("total_functions") or 0)
    if total <= 0:
        reasons.append(f"함수 {total}개 — 소스 경로/파싱을 확인할 것")
    return reasons


def main() -> None:
    ap = argparse.ArgumentParser(description="UDS quality baseline/compare/repro runner")
    ap.add_argument("--source-root", required=True)
    ap.add_argument("--req-paths", required=True, help="newline/comma separated requirement paths")
    ap.add_argument("--report-dir", default="reports")
    ap.add_argument("--template", default="")
    ap.add_argument("--test-mode", action="store_true")
    ap.add_argument("--full", action="store_true", help="generate extra reports (doc_only=false)")
    ap.add_argument("--ai-enable", action="store_true")
    ap.add_argument("--expand", action="store_true")
    ap.add_argument("--ai-detailed", action="store_true")
    ap.add_argument("--rag-top-k", type=int, default=12)
    ap.add_argument("--user", default="", help="토큰 발급 사용자(기본: admin_users.json 의 첫 admin)")
    ap.add_argument("--baseline-out", default="reports/uds_local/quality_baseline.json")
    ap.add_argument("--run-out", default="reports/uds_local/quality_run.json")
    ap.add_argument("--compare-out", default="reports/uds_local/quality_compare.json")
    args = ap.parse_args()

    run = _run_once(args)
    run_out = Path(args.run_out)
    _save_json(run_out, run)

    bad = _unusable_reasons(run)
    if bad:
        print(f"[run] saved: {run_out}")
        print("[ERROR] 이 실행은 기준선으로 쓸 수 없다 — " + " / ".join(bad), file=sys.stderr)
        print("        (베이스라인을 만들지 않았다. 위 사유를 고친 뒤 다시 돌릴 것)", file=sys.stderr)
        raise SystemExit(2)

    baseline_out = Path(args.baseline_out)
    if not baseline_out.exists():
        _save_json(baseline_out, run)
        print(f"[baseline] created: {baseline_out}")
        return

    prev = _load_json(baseline_out)
    cmp_data = _compare(prev, run)
    if not bool(cmp_data.get("input_fingerprint_match")):
        cmp_data["soft_fail"] = True
        reasons = list(cmp_data.get("soft_fail_reasons") or [])
        if "INPUT_FINGERPRINT_MISMATCH" not in reasons:
            reasons.append("INPUT_FINGERPRINT_MISMATCH")
        cmp_data["soft_fail_reasons"] = reasons
    _save_json(Path(args.compare_out), cmp_data)
    print(f"[run] saved: {run_out}")
    print(f"[compare] saved: {args.compare_out}")
    print(json.dumps(cmp_data, ensure_ascii=False, indent=2))
    if cmp_data.get("hard_fail"):
        # hard_fail 은 "품질이 나빠졌다" 가 아니라 **측정이 성립하지 않았다** 는 뜻이다.
        # 예전엔 그것도 exit 0 이라 래퍼(`run_quality_cycle.ps1`)가 통과로 읽었다.
        print("[ERROR] 측정 불성립: " + ", ".join(cmp_data.get("hard_fail_reasons") or []),
              file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
