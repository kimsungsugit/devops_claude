"""config/swut_meta.json 실파일 sanity — KJPDS02 SwUT PV 전환 회귀 가드.

2026-06-04 PV 실측 로그 전환분 (config 에이전트 변경) 중 **SwUT 영역만** 검증:
- valid JSON (json.loads round-trip)
- KJPDS02 doc_filenames SwUT 3종(coverage/sutr/swutcr) _PV_
- swut_log_folders 2항목 (APP/BOOT) + 단수 키(swut_log_folder)는 첫 항목과 일치
- swutcr_metadata phase=PV + DV 실측 고정값 3키 제거 (aggregator graceful fallback)

SwIT 영역(switcv/switr/switcr doc_filenames, swit_log_folders, switcr_metadata)은
별도 워크스트림이 PV 전환 진행 중 — 본 파일에서 단언하지 않는다 (이중 진리원 방지).

참고: 타 회귀(test_swut_meta_resolver/test_swut_router)는 monkeypatch로 자체 config
dict를 주입하므로 실파일 값을 검증하지 않는다 — 본 파일이 실파일 단일 가드.
"""
from __future__ import annotations

import json
from pathlib import Path

_CFG_PATH = Path(__file__).resolve().parents[2] / "config" / "swut_meta.json"


def _load_cfg() -> dict:
    """실파일 load — 한국어 경로 포함이므로 utf-8 고정."""
    return json.loads(_CFG_PATH.read_text(encoding="utf-8"))


class TestSwutMetaConfigKJPDS02PV:
    def test_valid_json_and_kjpds02_present(self):
        cfg = _load_cfg()
        assert isinstance(cfg, dict)
        assert "KJPDS02" in cfg.get("projects", {})

    def test_doc_filenames_swut_pv(self):
        """SwUT 3종(coverage/sutr/swutcr) PV 전환 — 2026-06-04 PV 실측 기준."""
        doc = _load_cfg()["projects"]["KJPDS02"]["doc_filenames"]
        for key in ("coverage", "sutr", "swutcr"):
            assert "KJPDS02_PV_" in doc[key], f"doc_filenames[{key}] PV 전환 누락"

    def test_swut_log_folders_two_entries_app_boot(self):
        """B2 멀티 폴더 — [0]=APP 43유닛, [1]=BOOT 10유닛(Report_sort 하위)."""
        k = _load_cfg()["projects"]["KJPDS02"]
        folders = k["swut_log_folders"]
        assert isinstance(folders, list)
        assert len(folders) == 2
        assert all(isinstance(f, str) and f for f in folders)
        assert "1.APP_UT_report_260604" in folders[0]
        assert "2.BOOT_UT_report_260604" in folders[1]
        # 단수 키(기존 코드 호환)는 APP(첫 항목)과 일치 — 우선순위 4단계 일관성
        assert k["swut_log_folder"] == folders[0]

    def test_swutcr_metadata_pv_and_dv_fixed_values_removed(self):
        """phase=PV + mcu 선행 탭 제거 + DV 실측 고정값 3키 부재."""
        meta = _load_cfg()["projects"]["KJPDS02"]["swutcr_metadata"]
        assert meta["phase"] == "PV"
        assert meta["mcu"] == "NXP S12ZVMC"
        for key in (
            "qualified_function_total",
            "fault_injection_total",
            "fault_injection_passed",
        ):
            assert key not in meta, (
                f"{key}: DV 실측 고정값 — PV 전환으로 제거됨 "
                "(부재 시 aggregator가 session 계산값으로 graceful fallback)"
            )

    def test_swuts_docx_path_wip_pv_spec_v0_10(self):
        """2026-06-18 — swuts_docx_path가 현행 PV spec((KJPDS02_PV_SwUTS) v0.10_260615)을 가리킴.

        빌더 라운드 105(spec 레이아웃 동적화)와 한 쌍인 config 교체분 가드:
        - 구 DV spec(v1.01_251205_R)으로 조용히 되돌아가면 PV SwUT 빌드가
          구 spec 기반으로 산출되는 회귀.
        - top-level 키가 비면 resolve_swuts_path가 iso26262_docs.swuts_xlsm_path
          (여전히 DV v1.01_R)로 폴백하는 잠재 함정 — 비어있지 않음을 고정.
        - 2026-06-18: 팀이 작성중...v0.10_260608 → (KJPDS02_PV_SwUTS)...v0.10_260615로
          rename(작성중 prefix 제거+날짜 갱신). 구 경로는 404로 빌드 전체 실패 →
          현행 파일명 가드.
        """
        k = _load_cfg()["projects"]["KJPDS02"]
        p = k["swuts_docx_path"]
        assert isinstance(p, str) and p.strip(), (
            "swuts_docx_path 공란 — iso26262_docs(DV spec) silent 폴백 함정"
        )
        assert p.endswith(
            "(KJPDS02_PV_SwUTS) Software Unit Test "
            "Specification_v0.10_260615.xlsm"
        ), f"현행 PV spec 미지정: {p!r}"
        assert "v1.01_251205_R" not in p, "구 DV spec으로 회귀 금지"
