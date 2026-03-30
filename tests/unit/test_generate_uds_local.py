from __future__ import annotations

from pathlib import Path


def test_resolve_source_root_prefers_env_override(tmp_path, monkeypatch):
    from tools import generate_uds_local

    source_root = tmp_path / "PDS64_RD"
    source_root.mkdir(parents=True)
    monkeypatch.setenv("UDS_SOURCE_ROOT", str(source_root))

    resolved = generate_uds_local._resolve_source_root(tmp_path)

    assert resolved == source_root


def test_write_uds_payload_sidecar_persists_function_details(tmp_path):
    from tools import generate_uds_local

    out_path = tmp_path / "uds.docx"
    out_path.write_text("placeholder", encoding="utf-8")
    payload = {
        "summary": {"mapping": {"total": 1}},
        "function_details": {
            "SwUFn_0001": {
                "name": "g_ap_buzzerctrl_func",
                "inputs": ["state"],
                "outputs": ["ret"],
                "globals_global": ["g_state"],
                "globals_static": ["s_timer"],
                "related": "SwCom_01",
            }
        },
    }

    sidecar = generate_uds_local._write_uds_payload_sidecar(out_path, payload)

    assert sidecar is not None
    assert sidecar.exists()
    text = sidecar.read_text(encoding="utf-8")
    assert "g_ap_buzzerctrl_func" in text
    assert "globals_static" in text
