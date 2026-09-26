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
        # 2026-06-24 — APP UT 로그 신규본 260611 갱신 (BOOT는 260604 불변).
        assert "1.APP_UT_report_260611" in folders[0]
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

    def test_swuts_docx_path_released_r_spec(self):
        """swuts_docx_path 가 **현행 released spec** 을 가리킴.

        이 테스트가 지키는 것 셋 — 파일명이 바뀌어도 이 셋은 그대로다:
        1. **공란 금지.** 비면 `resolve_swuts_path` 가 `iso26262_docs.swuts_xlsm_path`
           로 폴백하는데 그건 **아직도 DV v1.01_251205_R** 이다(실측). 조용히 구 spec
           으로 빌드된다.
        2. **DV 회귀 금지.** PV/released 판이 아닌 DV spec 으로 되돌아가면 산출물이
           통째로 구 양식이 된다.
        3. **현행 파일명 고정.** 낡은 경로는 404 로 빌드 전체를 실패시킨다.

        2026-08-25 갱신: 구 `(KJPDS02_PV_SwUTS)..v0.10_260615` 가 실측 404(팀이 released
        R 로 교체) → `(KJPDS02_SwUTS)..v2.01_260629_R`. 교체 전 파일을 열어 양식을 확인했다
        ('2.SW Unit Test Spec' C열 TC_ID + Inpt/ExpR 와이드 = PV 감사본 포맷 유지).
        """
        k = _load_cfg()["projects"]["KJPDS02"]
        p = k["swuts_docx_path"]
        assert isinstance(p, str) and p.strip(), (
            "swuts_docx_path 공란 — iso26262_docs(DV spec) silent 폴백 함정"
        )
        assert p.endswith(
            "(KJPDS02_SwUTS) Software Unit Test "
            "Specification_v2.01_260629_R.xlsm"
        ), f"현행 released spec 미지정: {p!r}"
        # 음성 대조군 — 구 DV spec 으로 되돌아간 것을 이름으로 못 박는다.
        assert "v1.01_251205_R" not in p, "DV spec 회귀"

    def test_swits_docx_path_released_r_spec(self):
        """SwITS 도 같은 가드 — **2026-08-25 신설**(그동안 비대칭이었다).

        SwIT 쪽이 더 위험하다: `sitr_spec_based` 빌드는 이 spec 시트를 **통째 복사**하므로
        DV 판이 들어오면 산출물 레이아웃이 통째로 바뀐다(DV 는 F열 `SwITC_0101_01`,
        PV/released 는 B열 `SwITC_SwUFn_0101_01`).

        ⚠ **파일명에 `_PV_` 가 없다고 DV 로 단정하면 틀린다** — released R 판은 `_PV_`
        접두 없이 나온다. 판정은 파일을 열어 TC ID 열로 해야 한다(2026-08-25 실측 확인).
        """
        k = _load_cfg()["projects"]["KJPDS02"]
        p = k["swits_docx_path"]
        assert isinstance(p, str) and p.strip(), (
            "swits_docx_path 공란 — iso26262_docs(DV spec) silent 폴백 함정"
        )
        assert p.endswith(
            "(KJPDS02_SwITS) Software Integration Test "
            "Specification_v2.01_260629_R.xlsm"
        ), f"현행 released spec 미지정: {p!r}"
        assert "v1.01_251205_R" not in p, "DV spec 회귀"
        assert "v1.01_251205_R" not in p, "구 DV spec으로 회귀 금지"
