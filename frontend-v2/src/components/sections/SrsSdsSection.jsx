import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { api, post, getUsername, authHeaders, buildUrl } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';

export default function SrsSdsSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadProgress, setLoadProgress] = useState('');  // step description
  const [warnings, setWarnings] = useState([]);           // partial failure warnings
  const matrixCacheRef = useRef(null);                     // cache key + data

  // 영향도 분석(ImpactGuideSection)에서 넘어온 focus(영향 함수 집합) — 1회 소비.
  // 있으면 매트릭스를 그 함수들로 자동 필터해 "이 변경이 닿는 요구사항/시험/공백"만 보여준다.
  const [traceFocus, setTraceFocus] = useState(() => {
    try {
      const raw = localStorage.getItem('devops_v2_trace_focus');
      if (!raw) return null;
      localStorage.removeItem('devops_v2_trace_focus');  // 1회 소비(stale 방지)
      const o = JSON.parse(raw);
      if (o && Array.isArray(o.functions) && o.functions.length && Date.now() - (o.ts || 0) < 120000) return o;
    } catch (_) { /* ignore */ }
    return null;
  });
  const _autoLoadedRef = useRef(false);

  const localDocPaths = useMemo(() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_doc_paths') || '{}'); } catch (_) { return {}; }
  }, []);

  // Prefer the registry entry matched by Dashboard for THIS job; fall back to
  // scmList[0] only when no match was recorded (single-project setups).
  const activeScm = analysisResult?.matchedScm || analysisResult?.scmList?.[0];
  // Merge: SCM linked_docs takes priority, then localStorage
  const scmLinked = activeScm?.linked_docs || {};
  const docPaths = useMemo(() => ({
    srs: localDocPaths.srs || scmLinked.srs || '',
    sds: localDocPaths.sds || scmLinked.sds || '',
    hsis: localDocPaths.hsis || scmLinked.hsis || '',
    stp: localDocPaths.stp || scmLinked.stp || '',
  }), [localDocPaths, scmLinked.srs, scmLinked.sds, scmLinked.hsis, scmLinked.stp]);

  // SCM linked docs (for loadMatrix + UI)
  // Use stable key (scm id or job url) to avoid infinite re-renders from object reference changes
  const scmLinkedDocs = activeScm?.linked_docs;
  const scmId = activeScm?.id || '';
  const [linkedDocs, setLinkedDocs] = useState(scmLinkedDocs || {});

  // VectorCAST 결과 로그 경로(복수) — Jenkins 빌드에 RAG 없을 때 cloudium fallback.
  // 부트로더/FBL/APP 등 별도 결과 대응. 설정의 SCM '연결 문서 경로'(linked_docs.vectorcast)
  // 에서 등록하며, 여기서는 read-only로 표시만 한다.
  const vcastPaths = useMemo(
    () => (Array.isArray(linkedDocs?.vectorcast) ? linkedDocs.vectorcast.filter(Boolean) : []),
    [linkedDocs],
  );

  useEffect(() => {
    // 레지스트리(단일 진실원)를 항상 최신으로 가져온다. 과거엔 분석 시점 스냅샷
    // (scmLinkedDocs)이 sts/suts/sits+vectorcast로 완전하면 재fetch를 건너뛰었는데(early-return),
    // 그러면 관리/Settings에서 경로가 갱신돼도(예: SwUTS v0.10→v1.02 release, 상위폴더 이관)
    // 프론트가 옛 경로를 고집해 '파일을 찾을 수 없습니다'가 나고 새로고침·분석 재실행으로도
    // 안 고쳐졌다(스냅샷이 완전한 한 레지스트리를 안 읽음). 이제 레지스트리를 우선하되,
    // 원 스냅샷의 유일 목적이던 vectorcast 누락 방지만 보존한다: 레지스트리 vectorcast가 비고
    // 스냅샷에만 있으면 vectorcast만 스냅샷에서 보강(경로/문서는 레지스트리 최신본).
    api('/api/scm/list').then(d => {
      const items = d?.items || (Array.isArray(d) ? d : []);
      // Match the SAME registry entry the Dashboard selected for this job.
      // Falling back to items[0] would silently pull another project's docs
      // in multi-SCM environments.
      const matched = scmId ? items.find(it => it.id === scmId) : items[0];
      if (matched?.linked_docs) {
        const reg = matched.linked_docs;
        const regVcast = Array.isArray(reg.vectorcast) ? reg.vectorcast.filter(Boolean) : [];
        const snapVcast = Array.isArray(scmLinkedDocs?.vectorcast) ? scmLinkedDocs.vectorcast.filter(Boolean) : [];
        setLinkedDocs(regVcast.length === 0 && snapVcast.length > 0
          ? { ...reg, vectorcast: scmLinkedDocs.vectorcast }
          : reg);
      } else if (scmLinkedDocs) setLinkedDocs(scmLinkedDocs);
    }).catch(() => { if (scmLinkedDocs) setLinkedDocs(scmLinkedDocs); });
  }, [scmId]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadMatrix = useCallback(async (forceRefresh = false) => {
    // Ensure linkedDocs is loaded from SCM before proceeding
    let activeDocs = linkedDocs;
    // core 문서가 비었거나(최초 진입), vectorcast가 없거나 빈 배열([])이면 레지스트리(단일
    // 진실원) 최신본을 가져온다. 분석 스냅샷은 vectorcast 등록 전/직후에 캡처되어 vectorcast가
    // undefined 또는 []로 굳어 있을 수 있고, 그러면 sts/suts 스냅샷 때문에 재fetch를 건너뛰어
    // VectorCAST 경로가 끝까지 안 실린다(P/F 공백의 직접 원인). 빈 배열도 stale일 수 있으므로
    // 레지스트리로 한 번 확인한다 — 레지스트리도 비어있으면 그게 정답이라 그대로 진행.
    const vcastMissing = !Array.isArray(activeDocs.vectorcast) || activeDocs.vectorcast.length === 0;
    if ((!activeDocs.sts && !activeDocs.suts) || vcastMissing) {
      try {
        const scmData = await api('/api/scm/list');
        const items = scmData?.items || (Array.isArray(scmData) ? scmData : []);
        const matched = scmId ? items.find(it => it.id === scmId) : items[0];
        if (matched?.linked_docs) {
          // sts/suts가 이미 스냅샷에 있으면 core 문서는 유지하고 vectorcast만 레지스트리
          // 최신본으로 보강(분석 시점 일관성 + vcast 최신화). 둘 다 없으면 전체 교체.
          if (!activeDocs.sts && !activeDocs.suts) {
            activeDocs = matched.linked_docs;
          } else if (Array.isArray(matched.linked_docs.vectorcast)) {
            activeDocs = { ...activeDocs, vectorcast: matched.linked_docs.vectorcast };
          }
          setLinkedDocs(activeDocs);
        }
      } catch (_) {}
    }

    // Debug: log activeDocs state

    // Cache check: skip API calls if inputs haven't changed
    const cacheKey = JSON.stringify({ srs: docPaths.srs, sds: docPaths.sds, hsis: docPaths.hsis || activeDocs.hsis, jobUrl: job?.url, sts: activeDocs.sts, suts: activeDocs.suts, sits: activeDocs.sits, syts: activeDocs.syts, syits: activeDocs.syits, vcast: (Array.isArray(activeDocs?.vectorcast) ? activeDocs.vectorcast : []).filter(Boolean).join(',') });
    if (!forceRefresh && matrixCacheRef.current?.key === cacheKey && matrixCacheRef.current?.data) {
      setMatrix(matrixCacheRef.current.data);
      toast('info', '캐시된 매트릭스를 사용합니다. 새로고침하려면 버튼을 다시 클릭하세요.');
      return;
    }

    setLoading(true);
    setWarnings([]);
    const stepWarnings = [];
    const dataSources = [];  // track which sources contributed

    try {
      // Step 1: Get requirements from SRS
      setLoadProgress('요구사항 추출 중...');
      const form = new FormData();
      if (docPaths.srs) form.append('req_paths', docPaths.srs);
      if (activeScm?.source_root) form.append('source_root', activeScm.source_root);

      let reqItems = [];
      let mappingPairs = [];
      let udsFunctionIds = [];  // 전체 UDS 함수 인벤토리(SDS→UDS bridge 시드용)
      try {
        const user = getUsername();
        const previewRes = await fetch('/api/jenkins/uds/requirements-preview', {
          method: 'POST', body: form,
          headers: user ? { 'X-User': user } : {},
        });
        if (previewRes.ok) {
          const previewData = await previewRes.json();
          reqItems = previewData?.preview?.items || [];
          mappingPairs = previewData?.traceability?.mapping_pairs
            || previewData?.mapping || [];
        }
      } catch (e) {
        stepWarnings.push(`요구사항 미리보기 실패: ${e.message}`);
        toast('warning', `요구사항 미리보기 실패: ${e.message}`);
      }

      // Step 2a: Extract func→req mapping from UDS document
      setLoadProgress('UDS 함수 매핑 추출 중...');
      if (mappingPairs.length === 0 && activeDocs.uds) {
        try {
          const udsMapping = await post('/api/jenkins/uds/extract-mapping', {
            uds_path: activeDocs.uds,
          });
          mappingPairs = udsMapping?.mapping_pairs || [];
          // 전체 UDS 함수 인벤토리 — 설계 req 참조 없는 함수까지 포함. 매트릭스 SDS→UDS
          // bridge가 전체 함수를 매칭하도록 별도 전달(mapping_pairs만으론 ~5%만 커버).
          udsFunctionIds = udsMapping?.all_function_ids || [];
          if (mappingPairs.length > 0) {
            toast('info', `UDS에서 ${mappingPairs.length}개 매핑 / ${udsFunctionIds.length}개 함수 추출`);
          }
        } catch (e) {
          stepWarnings.push(`UDS 매핑 추출 실패: ${e.message}`);
        }
      }

      // Step 2b: Extract SDS component→requirement mapping
      let sdsPairs = [];
      let componentAsil = {};  // ASIL 결합(P5) — {컴포넌트/함수명: ASIL}, 매트릭스가 요구사항 ASIL 도출
      if (docPaths.sds || activeDocs.sds) {
        setLoadProgress('SDS 컴포넌트 매핑 추출 중...');
        try {
          const sdsData = await post('/api/jenkins/sds/extract-mapping', {
            sds_path: docPaths.sds || activeDocs.sds,
          });
          sdsPairs = sdsData?.sds_pairs || [];
          componentAsil = sdsData?.component_asil || {};
          if (sdsPairs.length > 0) {
            dataSources.push(`SDS: ${sdsPairs.length}개 매핑`);
          }
        } catch (e) {
          stepWarnings.push(`SDS 매핑 추출 실패: ${e.message}`);
        }
      }

      // Step 2c: Extract HSIS interface→requirement mapping (시스템 레벨 인터페이스 밴드)
      let hsisPairs = [];
      if (docPaths.hsis || activeDocs.hsis) {
        setLoadProgress('HSIS 인터페이스 매핑 추출 중...');
        try {
          const hsisData = await post('/api/jenkins/hsis/extract-mapping', {
            hsis_path: docPaths.hsis || activeDocs.hsis,
          });
          hsisPairs = hsisData?.hsis_pairs || [];
          if (hsisPairs.length > 0) {
            dataSources.push(`HSIS: ${hsisPairs.length}개 인터페이스 매핑`);
          }
        } catch (e) {
          stepWarnings.push(`HSIS 매핑 추출 실패: ${e.message}`);
        }
      }

      // Step 3: Collect test rows — priority: STS > SUTS > SITS > VectorCAST
      // STS/SUTS/SITS are exact matches; VectorCAST is fuzzy (function-name based)
      let vcastRows = [];
      let sitsRows = [];
      // (이전엔 exactCoveredReqs/stsSutsCoveredReqs Set으로 STS·SUTS·SITS exact-커버
      //  req를 VectorCAST fuzzy 추론에서 제외했으나, 이제 VectorCAST를 실행 evidence로
      //  exact-커버 req에도 함께 노출(confidence='mixed')하는 정책이라 제거됨.)

      // 3a. STS traceability (요구사항↔TC 직접 매핑 — 가장 정확, confidence=exact)
      if (activeDocs.sts) {
        setLoadProgress('STS 추적성 추출 중...');
        try {
          const stsData = await post('/api/jenkins/sts/extract-traceability', { path: activeDocs.sts, doc_type: 'sts' });
          if (stsData?.vcast_rows?.length) {
            for (const row of stsData.vcast_rows) {
              vcastRows.push({ ...row, source: row.source || 'STS', confidence: 'exact' });
            }
            dataSources.push(`STS: ${stsData.vcast_rows.length}건`);
          } else if (Array.isArray(stsData?.available_sheets)) {
            stepWarnings.push(`STS: ${stsData.error || '시트 미인식'}. 사용 가능한 시트: ${stsData.available_sheets.join(', ')}`);
          }
        } catch (e) {
          stepWarnings.push(`STS 추출 실패: ${e.message}`);
        }
      }

      // 3b. SUTS traceability (confidence=exact)
      if (activeDocs.suts) {
        setLoadProgress('SUTS 추적성 추출 중...');
        try {
          const sutsData = await post('/api/jenkins/sts/extract-traceability', { path: activeDocs.suts, doc_type: 'suts' });
          if (sutsData?.vcast_rows?.length) {
            for (const row of sutsData.vcast_rows) {
              vcastRows.push({ ...row, source: row.source || 'SUTS', confidence: 'exact' });
            }
            dataSources.push(`SUTS: ${sutsData.vcast_rows.length}건`);
          } else if (Array.isArray(sutsData?.available_sheets)) {
            stepWarnings.push(`SUTS: ${sutsData.error || '시트 미인식'}. 사용 가능한 시트: ${sutsData.available_sheets.join(', ')}`);
          }
        } catch (e) {
          stepWarnings.push(`SUTS 추출 실패: ${e.message}`);
        }
      }

      // 3c. SITS traceability (통합 테스트, confidence=exact)
      if (activeDocs.sits) {
        setLoadProgress('SITS 추적성 추출 중...');
        try {
          const sitsData = await post('/api/jenkins/sits/extract-traceability', { path: activeDocs.sits });
          if (sitsData?.vcast_rows?.length) {
            sitsRows = sitsData.vcast_rows.map(r => ({ ...r, source: r.source || 'SITS', confidence: 'exact' }));
            // 직접 요구 매핑(requirement_id 보유) vs testcase-only(2-hop 대기) 구분: 전부 후자면
            // 요구열 없는 Test-Log 포맷이라 매트릭스 2-hop이 SUTS/SDS로 구제하지 못하면 SITS 밴드가
            // 조용히 빈다. backend가 실은 warning을 성공 표시와 함께 노출한다(deep-review W6).
            const directN = sitsData.vcast_rows.filter(r => r.requirement_id).length;
            if (directN > 0) {
              dataSources.push(`SITS: ${sitsData.vcast_rows.length}건`);
            } else {
              dataSources.push(`SITS: ${sitsData.vcast_rows.length}건(요구열 없음·2-hop 의존)`);
              if (sitsData.warning) stepWarnings.push(`SITS: ${sitsData.warning}`);
            }
          } else if (Array.isArray(sitsData?.available_sheets)) {
            stepWarnings.push(`SITS: ${sitsData.warning || sitsData.error || '시트 미인식'}. 사용 가능한 시트: ${sitsData.available_sheets.join(', ')}`);
          }
        } catch (e) {
          stepWarnings.push(`SITS 추출 실패: ${e.message}`);
        }
      }

      // 3c-2. 시스템 시험(SyTS/SyITS) — SITS와 동일 구조, source 라벨만 다름.
      // 비기능/안전 요구의 시스템 레벨 검증으로 covered 승격(결정1). vcast_rows에 합류(source로 분류).
      for (const [docKey, ep, label] of [
        ['syts', '/api/jenkins/syts/extract-traceability', 'SyTS'],
        ['syits', '/api/jenkins/syits/extract-traceability', 'SyITS'],
      ]) {
        if (!activeDocs[docKey]) continue;
        setLoadProgress(`${label} 추적성 추출 중...`);
        try {
          const sysData = await post(ep, { path: activeDocs[docKey] });
          if (sysData?.vcast_rows?.length) {
            for (const row of sysData.vcast_rows) vcastRows.push({ ...row, source: row.source || label, confidence: 'exact' });
            dataSources.push(`${label}: ${sysData.vcast_rows.length}건`);
          } else if (Array.isArray(sysData?.available_sheets)) {
            // 0건이 silent하지 않게 — 시트 미인식 원인 노출(SITS와 동일).
            stepWarnings.push(`${label}: ${sysData.warning || sysData.error || '시트 미인식'}. 사용 가능한 시트: ${sysData.available_sheets.join(', ')}`);
          }
        } catch (e) {
          stepWarnings.push(`${label} 추출 실패: ${e.message}`);
        }
      }

      // 3d. VectorCAST (함수 기반, confidence=fuzzy)
      // Only add VectorCAST rows for req IDs NOT already covered by STS/SUTS/SITS
      setLoadProgress('VectorCAST 데이터 수집 중...');
      try {
        // Cloudium 폴백: Jenkins 빌드에 RAG 없으면 등록된 경로들(부트로더/FBL/APP 등
        // 별도 결과)에서 read. activeDocs는 loadMatrix가 새로 fetch한 최신 linked_docs.
        const vcastLogPaths = Array.isArray(activeDocs?.vectorcast)
          ? activeDocs.vectorcast.filter(Boolean)
          : [];
        const ragData = await post('/api/jenkins/report/vectorcast-rag', {
          job_url: job.url,
          cache_root: cacheRoot,
          build_selector: cfg.buildSelector || 'lastSuccessfulBuild',
          vcast_log_paths: vcastLogPaths,
        });
        const rawRows = ragData?.data?.test_rows || [];
        // silent-drop 방지(P1): VectorCAST 폴더 파싱 실패/빈결과 사유(worker timeout·폴더 부재
        // 등)를 표면화한다. 부분 실패는 data.parse_warnings, 완전 실패(missing 응답)는 top-level.
        const vcWarnings = ragData?.data?.parse_warnings || ragData?.parse_warnings || [];
        // VectorCAST 데이터가 하나도 없을 때만(완전 실패) 사유를 표면화한다. 성공/부분성공
        // (rawRows 존재)에는 성공 경로의 정보성 note([metric-report] 함수콜 보강 등)가 섞여 있어
        // 표시하면 노이즈이고, 이 stepWarnings가 matrix 캐시 게이트(hadStepFailure)를 꺼
        // 매 조회 재파싱을 유발한다(deep-review W1/W2). 데이터 0건일 때만 silent-drop을 막는다.
        if (!rawRows.length && Array.isArray(vcWarnings) && vcWarnings.length) {
          const _head = vcWarnings.slice(0, 3).join(' / ');
          const _more = vcWarnings.length > 3 ? ` 외 ${vcWarnings.length - 3}건` : '';
          stepWarnings.push(`VectorCAST: ${_head}${_more}`);
        }

        // VectorCAST는 함수(subprogram) 단위로 롤업해 SUTS와 동일 granularity로 맞춘다.
        // per-실행(수천 행)을 그대로 보내면 한 요구사항에 수백~수천 셀이 붙어 렌더가
        // 무거워지고 추적성 가독성이 떨어진다(함수의 TC 중 하나라도 fail이면 fail).
        // 요구사항 매핑은 backend(generate_uds_traceability_matrix)가 SUTS·SDS 함수명
        // bridge로 수행한다: SwUFn → (SUTS)함수명 → (SDS)SRS. 그래서 requirement_id=''.
        // (과거엔 여기서 UDS 설계레벨 매핑(SwSTR)으로 미리 join했는데, 그 ID는 SRS
        //  매트릭스 행(SwTR/SwEI 등)과 namespace가 달라 전부 누락되는 원인이었다.)
        // backend 소비 필드(subprogram/testcase/result/unit/report)만 추려 payload 슬림화.
        const FAIL_R = new Set(['fail', 'failed', 'false', '0', 'ng']);
        const vcByFunc = new Map();
        for (const row of rawRows) {
          const sub = (row.subprogram || '').trim();
          if (!sub) continue;
          const res = String(row.result || '').toLowerCase();
          let agg = vcByFunc.get(sub);
          if (!agg) { agg = { sub, report: row.report || '', unit: row.unit || '', tc: 0, fail: 0 }; vcByFunc.set(sub, agg); }
          agg.tc += 1;
          if (FAIL_R.has(res)) agg.fail += 1;
        }
        let vcastAdded = 0;
        for (const agg of vcByFunc.values()) {
          const label = agg.tc > 1 ? `${agg.sub} (${agg.tc} TC${agg.fail ? `, ${agg.fail} fail` : ''})` : agg.sub;
          vcastRows.push({
            subprogram: agg.sub,
            testcase: label,
            result: agg.fail > 0 ? 'fail' : 'pass',
            unit: agg.unit,
            report: agg.report,
            requirement_id: '',
            source: 'VectorCAST',
            confidence: 'fuzzy',
          });
          vcastAdded++;
        }
        if (vcastAdded > 0) dataSources.push(`VectorCAST: ${vcastAdded}개 함수`);
      } catch (e) {
        stepWarnings.push(`VectorCAST 수집 실패: ${e.message}`);
      }

      // Warn if no data sources contributed
      if (reqItems.length === 0) {
        stepWarnings.push('SRS에서 요구사항을 추출하지 못했습니다. SRS 경로를 확인하세요.');
        toast('warning', 'SRS 요구사항이 없어 매트릭스를 생성할 수 없습니다.');
        setWarnings(stepWarnings);
        setLoading(false);
        setLoadProgress('');
        return;
      }
      if (vcastRows.length === 0 && sitsRows.length === 0 && mappingPairs.length === 0 && sdsPairs.length === 0) {
        stepWarnings.push('설계/테스트 매핑 데이터가 없습니다. SW(SDS·UDS·STS·SUTS·SITS)·시스템(HSIS·SyTS·SyITS)·VectorCAST 연결을 확인하세요.');
      }

      // Step 4: Generate full traceability matrix (V-model 6-level)
      setLoadProgress(`매트릭스 생성 중 (${reqItems.length}개 요구사항)...`);
      const data = await post('/api/jenkins/uds/traceability-matrix', {
        requirement_items: reqItems,
        mapping_pairs: mappingPairs,
        uds_function_ids: udsFunctionIds,
        vcast_rows: vcastRows,
        sds_pairs: sdsPairs,
        hsis_pairs: hsisPairs,  // 시스템 레벨 인터페이스 밴드(design-arm)
        sits_rows: sitsRows,
        component_asil: componentAsil,  // ASIL 결합(P5) — 요구사항별 ASIL 도출용
        // Required for server-side summary cache (dashboard TraceSummaryCard)
        job_url: job?.url || '',
        cache_root: cacheRoot || '.devops_pro_cache',
        build_selector: cfg?.buildSelector || 'lastSuccessfulBuild',
      });
      // 이 시점까지의 경고 = 실제 step 실패(SUTS/SITS/VectorCAST 추출 실패·매핑 없음).
      // 아래 untraced 경고는 정보성이므로 캐시 가드 판단에서 제외하기 위해 먼저 스냅샷.
      const hadStepFailure = stepWarnings.length > 0;
      // VectorCAST bridge 가시성: SRS에 연결된 함수 수 / 미연결(이 SRS 범위 밖 함수).
      // 미연결엔 단위시험된 함수(SDS 명세 공백 후보)도 포함 — 트리 'SRS 미추적 시험'에서 확인.
      const vcSum = (data?.matrix?.summary) || data?.summary || {};
      if (typeof vcSum.vcast_input_rows === 'number' && vcSum.vcast_input_rows > 0) {
        const untraced = vcSum.vcast_untraced_rows ?? 0;
        if (untraced > 0) {
          const sutsTested = vcSum.unmapped_suts_tested ?? 0;
          const tail = sutsTested > 0 ? ` 이 중 ${sutsTested}개는 단위시험까지 됨(SDS 명세 공백 가능) — 트리 'SRS 미추적 시험'에서 확인하세요.` : ' 부트로더·ISR 등 — 정상이나, 이 수가 급증하면 SUTS/SDS 매핑을 확인하세요.';
          stepWarnings.push(`VectorCAST ${vcSum.vcast_traced_rows}/${vcSum.vcast_input_rows} 함수가 SRS에 연결됨. ${untraced}개는 이 SRS 범위 밖.${tail}`);
        }
      }
      // Attach metadata
      data._dataSources = dataSources;
      setMatrix(data);
      // 부분 실패(step 실패) 시 캐시 저장 안 함 — 불완전 매트릭스가 '캐시 사용'으로 굳어
      // 시험 evidence 누락을 silent 은폐하는 것 방지(deep-analyze WARNING). 정상 시에만 캐시.
      if (!hadStepFailure) {
        matrixCacheRef.current = { key: cacheKey, data };
      }
      if (dataSources.length > 0) {
        toast('success', `매트릭스 생성 완료: ${dataSources.join(', ')}`);
      }
    } catch (e) {
      toast('error', `추적성 매트릭스 조회 실패: ${e.message}`);
    } finally {
      setLoading(false);
      setLoadProgress('');
      if (stepWarnings.length > 0) setWarnings(stepWarnings);
    }
  }, [job, cfg, cacheRoot, docPaths, linkedDocs, scmId, toast]);

  // focus(영향도 → 추적성)를 갖고 진입하면 매트릭스를 자동 생성한다(1회).
  useEffect(() => {
    if (traceFocus && !_autoLoadedRef.current) {
      _autoLoadedRef.current = true;
      loadMatrix(false);
    }
  }, [traceFocus, loadMatrix]);

  const impactData = analysisResult?.impactData;
  const impacts = impactData?.impacts ?? impactData?.impact_items ?? [];
  const changedFiles = impactData?.changed_files ?? [];
  const impactedDocs = impactData?.impacted_docs ?? impactData?.impacted_documents ?? [];

  return (
    <div>
      {/* Input doc status */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">입력 문서 현황</span>
        </div>
        <div className="field-group">
          {/* 추적성 매트릭스 입력 문서 11종 — 설계(SRS/SDS/UDS)·인터페이스(HSIS)·SW시험(STS/SUTS/SITS)
              ·시스템(SyRS상위/SyTS/SyITS)·계획(STP). 경로는 localStorage 우선, 없으면 SCM linked_docs. */}
          {[
            { label: 'SRS', key: 'srs', grp: 'design' },
            { label: 'SDS', key: 'sds', grp: 'design' },
            { label: 'UDS', key: 'uds', grp: 'design' },
            { label: 'HSIS', key: 'hsis', grp: 'interface' },
            { label: 'STS', key: 'sts', grp: 'test' },
            { label: 'SUTS', key: 'suts', grp: 'test' },
            { label: 'SITS', key: 'sits', grp: 'test' },
            { label: 'SyRS↑', key: 'syrs', grp: 'system' },
            { label: 'SyTS', key: 'syts', grp: 'system' },
            { label: 'SyITS', key: 'syits', grp: 'system' },
            { label: 'STP', key: 'stp', grp: 'plan' },
          ].map(({ label, key, grp }) => {
            const path = localDocPaths[key] || scmLinked[key] || '';
            const fromScm = !localDocPaths[key] && !!scmLinked[key];
            const dot = { design: '#0d9488', interface: '#0e7490', test: '#2563eb', system: '#9333ea', plan: '#6b7280' }[grp];
            return (
            <div key={label} className="artifact-item" style={{ background: 'var(--bg)', overflow: 'hidden' }}>
              <span className="pill" style={{ minWidth: 46, textAlign: 'center', flexShrink: 0, background: dot, color: '#fff', fontWeight: 600 }}>{label}</span>
              {path ? (
                <>
                  <span className="artifact-name" title={path} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {path.split(/[\\/]/).pop()}
                  </span>
                  {fromScm && <span className="pill pill-info" style={{ fontSize: 9 }}>SCM</span>}
                  <StatusBadge tone="success">등록됨</StatusBadge>
                </>
              ) : (
                <>
                  <span className="text-muted text-sm">{grp === 'system' ? '시스템 문서(선택) — 설정/SCM에서 등록' : '설정 탭 또는 SCM에서 경로를 등록하세요'}</span>
                  <StatusBadge tone="neutral">미등록</StatusBadge>
                </>
              )}
            </div>
            );
          })}
          {/* VectorCAST 결과 로그 (Cloudium) — Jenkins 빌드에 RAG 없을 때 폴백.
              부트로더/FBL/APP 등 결과가 별도로 나올 때 설정 → SCM '연결 문서 경로'에서
              복수 경로 등록. 여기서는 read-only 표시만. */}
          <div
            className="artifact-item"
            style={{ background: 'var(--bg)', overflow: 'hidden', flexDirection: 'column', alignItems: 'stretch', gap: 4 }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span className="pill pill-purple" style={{ minWidth: 40, textAlign: 'center', flexShrink: 0 }}>VC로그</span>
              {vcastPaths.length > 0 ? (
                <>
                  <span className="artifact-name" style={{ flex: 1, minWidth: 0 }}>
                    {vcastPaths.length === 1 ? '경로 1개 등록됨' : `경로 ${vcastPaths.length}개 등록됨`}
                  </span>
                  <span className="pill pill-info" style={{ fontSize: 9 }}>SCM</span>
                  <StatusBadge tone="success">지정됨</StatusBadge>
                </>
              ) : (
                <>
                  <span className="text-muted text-sm" style={{ flex: 1, minWidth: 0 }}>설정 → SCM &lsquo;연결 문서 경로&rsquo;에서 VectorCAST 경로 등록 (미등록 시 Jenkins 빌드 사용)</span>
                  <StatusBadge tone="neutral">Jenkins</StatusBadge>
                </>
              )}
            </div>
            {vcastPaths.length > 0 && (
              <ul style={{ margin: 0, paddingLeft: 46, listStyle: 'none' }}>
                {vcastPaths.map((p, i) => (
                  <li
                    key={i}
                    title={p}
                    style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)', wordBreak: 'break-all', padding: '1px 0' }}
                  >
                    <span style={{ color: 'var(--text-muted)', marginRight: 4 }}></span>{p}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      {/* Impact data: changed files and impacted documents */}
      {impactData && (changedFiles.length > 0 || impactedDocs.length > 0) && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">영향 분석 결과</span>
          </div>

          {/* Stats row */}
          <div className="stats-row" style={{ marginBottom: 12 }}>
            <div className="stat-card">
              <div className="text-muted text-sm">변경 파일</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{changedFiles.length}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">영향 문서</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{impactedDocs.length}</div>
            </div>
            {impacts.length > 0 && (
              <div className="stat-card">
                <div className="text-muted text-sm">영향 요구사항</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{impacts.length}</div>
              </div>
            )}
          </div>

          {/* Changed files */}
          {changedFiles.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>변경 파일</div>
              <div className="artifact-list">
                {changedFiles.map((f, i) => {
                  const path = typeof f === 'string' ? f : f.path;
                  const action = typeof f === 'object' ? f.action : undefined;
                  return (
                    <div key={i} className="artifact-item" style={{ overflow: 'hidden' }}>
                      <span style={{ fontSize: 11, marginRight: 4, flexShrink: 0 }}>
                        {action === 'A' ? '🟢' : action === 'D' ? '🔴' : '🟡'}
                      </span>
                      <span className="artifact-name" style={{ fontFamily: 'monospace', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{path}</span>
                      {action && <span className="pill pill-neutral">{action}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Impacted documents */}
          {impactedDocs.length > 0 && (
            <div>
              <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>영향받는 문서</div>
              <table className="impact-table">
                <thead>
                  <tr><th>문서명</th><th>유형</th><th>상태</th></tr>
                </thead>
                <tbody>
                  {impactedDocs.map((doc, i) => {
                    const name = doc.name ?? doc.doc_name ?? doc.path ?? '-';
                    const type = doc.type ?? doc.doc_type ?? '-';
                    const status = doc.status ?? 'unknown';
                    const tone = status === 'updated' ? 'success'
                      : status === 'outdated' ? 'danger'
                      : status === 'review_needed' ? 'warning'
                      : 'neutral';
                    return (
                      <tr key={i}>
                        <td className="text-sm">{name}</td>
                        <td><span className="pill pill-purple">{type.toUpperCase()}</span></td>
                        <td><StatusBadge tone={tone}>{status}</StatusBadge></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Impact summary - requirement level */}
      {impacts.length > 0 && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">영향받는 요구사항</span>
            <StatusBadge tone="warning">{impacts.length}건</StatusBadge>
          </div>
          <table className="impact-table">
            <thead>
              <tr><th>요구사항 ID</th><th>설명</th><th>문서</th><th>영향 수준</th></tr>
            </thead>
            <tbody>
              {impacts.map((item, i) => (
                <tr key={i}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{item.req_id ?? item.id ?? '-'}</td>
                  <td className="text-sm">{item.description ?? item.desc ?? '-'}</td>
                  <td className="text-sm">{item.doc ?? item.document ?? '-'}</td>
                  <td>
                    <StatusBadge tone={item.level === 'high' ? 'danger' : item.level === 'medium' ? 'warning' : 'info'}>
                      {item.level ?? '-'}
                    </StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Traceability matrix */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">추적성 매트릭스</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {loading && loadProgress && (
              <span className="text-muted text-sm">{loadProgress}</span>
            )}
            <button className="btn-sm" onClick={() => loadMatrix(false)} disabled={loading}>
              {loading ? <span className="spinner" /> : '매트릭스 생성'}
            </button>
            {matrix && (
              <button className="btn-sm" onClick={() => loadMatrix(true)} disabled={loading}
                title="캐시를 무시하고 새로 생성" style={{ fontSize: 11 }}>
                새로고침
              </button>
            )}
          </div>
        </div>

        {/* Partial failure warnings */}
        {warnings.length > 0 && (
          <div style={{ margin: '8px 0', padding: '8px 12px', background: '#fef3c7', border: '1px solid #fcd34d', borderRadius: 6, fontSize: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>일부 데이터 소스에서 경고가 발생했습니다:</div>
            {warnings.map((w, i) => <div key={i} style={{ color: '#92400e' }}>• {w}</div>)}
          </div>
        )}

        {matrix ? (
          <TraceMatrix matrix={matrix} focusFunctions={traceFocus?.functions || null} onClearFocus={() => setTraceFocus(null)}
            job={job} cacheRoot={cacheRoot} buildSelector={cfg?.buildSelector || 'lastSuccessfulBuild'}
            sourceRoot={activeScm?.source_root || ''} toast={toast} />
        ) : (
          <div className="text-muted text-sm">
            SRS/SDS 경로를 설정 탭에서 등록한 후 매트릭스 생성 버튼을 클릭하세요.
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Coverage helpers ── */
const COVERAGE_COLORS = {
  covered:   { bg: '#dcfce7', fg: '#166534', border: '#86efac' },
  partial:   { bg: '#fef9c3', fg: '#854d0e', border: '#fde047' },
  uncovered: { bg: '#fee2e2', fg: '#991b1b', border: '#fca5a5' },
};

function coverageTone(status) {
  if (status === 'covered')   return 'success';
  if (status === 'partial')   return 'warning';
  if (status === 'uncovered') return 'danger';
  return 'neutral';
}

function CoverageBar({ covered, partial, total, onFilter }) {
  if (!total) return null;
  const covPct = Math.round((covered / total) * 100);
  const partPct = Math.round((partial / total) * 100);
  const uncovPct = Math.max(0, 100 - covPct - partPct);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 200 }}>
      <div style={{ display: 'flex', height: 12, borderRadius: 4, overflow: 'hidden', background: 'var(--border, #e5e7eb)', cursor: 'pointer' }}>
        {covPct > 0 && <div onClick={() => onFilter?.('covered')} title="Covered만 보기" style={{ width: `${covPct}%`, background: COVERAGE_COLORS.covered.border }} />}
        {partPct > 0 && <div onClick={() => onFilter?.('partial')} title="Partial만 보기" style={{ width: `${partPct}%`, background: COVERAGE_COLORS.partial.border }} />}
        {uncovPct > 0 && <div onClick={() => onFilter?.('uncovered')} title="Uncovered만 보기" style={{ width: `${uncovPct}%`, background: COVERAGE_COLORS.uncovered.border }} />}
      </div>
      <div className="text-sm text-muted" style={{ display: 'flex', gap: 10 }}>
        <span style={{ color: COVERAGE_COLORS.covered.fg, cursor: 'pointer' }} onClick={() => onFilter?.('covered')}>Covered {covPct}%</span>
        {partial > 0 && <span style={{ color: COVERAGE_COLORS.partial.fg, cursor: 'pointer' }} onClick={() => onFilter?.('partial')}>Partial {partPct}%</span>}
        <span style={{ color: COVERAGE_COLORS.uncovered.fg, cursor: 'pointer' }} onClick={() => onFilter?.('uncovered')}>Uncovered {uncovPct}%</span>
        <span style={{ cursor: 'pointer', opacity: 0.5 }} onClick={() => onFilter?.('all')}>전체</span>
      </div>
    </div>
  );
}

// Truthy check mirroring Python's bool() on collections — non-empty array,
// non-empty object, or non-falsy scalar. Arrays that exist but are empty do
// NOT count as "has data". This has to match backend _cache_trace_summary so
// the dashboard Quality Gate and the UncoveredTopList agree on the same
// uncovered set.
function _hasData(v) {
  if (v == null) return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'object') return Object.keys(v).length > 0;
  return Boolean(v);
}

// Field lists aligned with backend _cache_trace_summary (jenkins.py, has_design/has_tests).
// Any divergence here will cause the Dashboard trace summary card to disagree
// with the Matrix / UncoveredTopList counts — keep the two in lockstep.
const DESIGN_FIELDS = [
  // sds_functions: 추적 정화 후 인터페이스 함수가 sds_components에서 분리됐다. 함수로만 추적되는
  // 요구사항이 '설계 없음(uncovered)'으로 회귀하지 않도록 hasDesign 판정에 포함(백엔드 lockstep).
  // hsis_signals: 시스템 인터페이스(HSIS) realization — SwEI 등 인터페이스 요구 커버(결정1, 백엔드 has_design lockstep).
  'source_ids', 'sds_components', 'sds_functions', 'hsis_signals', 'functions', 'mapping', 'sds', 'source_mapping',
];
const TEST_FIELDS = [
  // syts_tests/syits_tests: 시스템 레벨 시험 — 비기능/안전 요구의 검증으로 covered 인정(결정1, 백엔드 has_tests lockstep).
  'tests', 'sts_tests', 'suts_tests', 'sits_tests', 'syts_tests', 'syits_tests', 'vcast_tests', 'test_ids',
];

function hasDesignData(r) {
  return DESIGN_FIELDS.some(f => _hasData(r[f]));
}

function hasTestData(r) {
  return TEST_FIELDS.some(f => _hasData(r[f]));
}

// 요구사항 유형 분류 — pair-gap 정직화(진짜갭 vs 대체검증) + deriveStatus 비기능 판정 공용 SSOT.
//  - nonfunctional(SwNTR/SwNTSR): 설계 분해 없이 시험으로 직접 검증(결정1) → UDS/SITS 구조적 불요.
//  - interface(SwEI/SwEIF): SDS→HSIS 실현·시스템 통합시험(SyITS)으로 검증 → SITS 구조적 불요.
// RAW 철자(정규화 전)라 Sy* 접두도 인정(백엔드 jenkins/local lockstep).
export function _reqClass(rid) {
  const s = String(rid || '').toUpperCase();
  if (['SWNTR', 'SWNTSR', 'SYNTR', 'SYNTSR'].some(p => s.startsWith(p))) return 'nonfunctional';
  if (['SWEI', 'SWEIF', 'SYEI', 'SYEIF'].some(p => s.startsWith(p))) return 'interface';
  return 'functional';
}

// Derive coverage status from row data (pure function, shared across useMemo/filters)
export function deriveStatus(r) {
  const hasDesign = hasDesignData(r);
  const hasTest = hasTestData(r);
  // 비기능/안전 요구(SwNTR/SwNTSR)는 설계 분해 없이 시험으로 직접 검증(결정1, 백엔드 lockstep).
  const rid = String(r.requirement_id || '').toUpperCase();
  // RAW 철자(정규화 전)라 SyNTR_/SyNTSR_도 인정 — 분류는 _reqClass SSOT 재사용(백엔드 lockstep).
  const isNonFunctional = _reqClass(rid) === 'nonfunctional';
  // Full: 시험 + (설계 OR 비기능 요구)
  if (hasTest && (hasDesign || isNonFunctional)) return 'covered';
  // Partial: any one layer present
  if (hasDesign || hasTest) return 'partial';
  if (r.status && r.status !== 'uncovered') return r.status;
  return 'uncovered';
}

const PAGE_SIZES = [30, 50, 100];
const SOURCE_ICONS = { STS: 'S', SUTS: 'U', SITS: 'I', SyTS: 'T', SyITS: 'Y', VectorCAST: 'V' };
const SOURCE_COLORS = { STS: '#2563eb', SUTS: '#7c3aed', SITS: '#0891b2', SyTS: '#9333ea', SyITS: '#c026d3', VectorCAST: '#ea580c' };
const CONFIDENCE_LABELS = { exact: 'Exact', direct: 'Direct', indirect: 'Indirect', fuzzy: 'Fuzzy', mixed: 'Mixed' };
const CONFIDENCE_COLORS = { exact: '#16a34a', direct: '#16a34a', indirect: '#d97706', fuzzy: '#9ca3af', mixed: '#2563eb' };

// 안정 빈 배열 참조 — unmapped_vcast 키 부재(로컬 파일모드) 시 매 렌더 새 [] 리터럴이
// 생성돼 gapStats useMemo가 매번 재계산되던 것을 방지(재검증 I3, 정확성 무관·성능 미세).
const _EMPTY_ARR = [];

// 추적성 공백 배지 — 정/역방향 공백 카운트를 상시 노출(0이면 녹색, >0이면 amber).
function GapBadge({ label, value, tone, title, sub }) {
  const warn = tone === 'warn';
  const c = warn ? COVERAGE_COLORS.partial : COVERAGE_COLORS.covered;
  return (
    <span title={title} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 16,
      background: warn ? c.bg : '#f0fdf4', border: `1px solid ${c.border}`, whiteSpace: 'nowrap' }}>
      <span style={{ color: 'var(--fg)' }}>{label}</span>
      <span style={{ fontWeight: 700, fontSize: 13, color: warn ? c.fg : COVERAGE_COLORS.covered.fg }}>{value}</span>
      {sub ? <span style={{ fontSize: 10, color: c.fg, fontWeight: 600 }}>({sub})</span> : null}
    </span>
  );
}

// ── V-model 수평쌍 완성도 요약 (상단 상시 노출) ──
// 각 쌍: 좌(설계) 밴드 present 요구 중 우(검증) 밴드가 채워진 비율을 막대+판정으로.
// covered(any-design AND any-test) 녹색이 통합/시스템 시험 미완을 가리는 것을 상단에서 한눈에 표면화.
function _pairTone(gapGenuine) {
  // 진짜 결핍 0 = 완결(green), 있으면 약함(amber). 대체검증분은 결핍으로 세지 않음(정직화 lockstep).
  return gapGenuine === 0 ? 'ok' : 'warn';
}

function VModelPairSummary({ pg }) {
  // 좌 분모 0(해당 설계 밴드를 쓰는 요구 없음)이면 그 쌍은 'N/A'로 회색 표시(거짓 100% 방지).
  const pairs = [
    { key: 'src', label: 'Source → VectorCAST', side: '실행 결과', left: pg.srcLeft, gap: pg.srcNoVc, genuine: pg.srcNoVc },
    { key: 'uds', label: 'UDS → SUTS', side: 'SW 단위시험', left: pg.udsLeft, gap: pg.udsNoSuts, genuine: pg.udsNoSuts },
    { key: 'sds', label: 'SDS → SITS', side: 'SW 통합시험', left: pg.sdsLeft, gap: pg.sdsNoSits, genuine: pg.sdsNoSitsGenuine, alt: pg.sdsNoSitsAlt },
    { key: 'hsis', label: 'HSIS → SyITS', side: '시스템 통합시험', left: pg.hsisLeft, gap: pg.hsisNoSyits, genuine: pg.hsisNoSyits },
    { key: 'syrs', label: 'SyRS → SyTS', side: '시스템 시험', left: pg.syrsLeft, gap: pg.syrsNoSyts, genuine: pg.syrsNoSyts },
  ];
  return (
    <div style={{ marginBottom: 12, border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', background: 'var(--bg)' }}>
      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 8, color: 'var(--fg)' }}>
        V-model 수평쌍 완성도 <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)' }}>— 설계(좌) 대비 대응 검증(우) 채움 · 진짜 결핍만 '약함'</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {pairs.map(p => {
          const na = !p.left;
          const done = na ? 0 : p.left - p.genuine;
          const pct = na ? 0 : Math.round((done / p.left) * 100);
          const tone = _pairTone(p.genuine);
          const barC = na ? '#cbd5e1' : (tone === 'ok' ? COVERAGE_COLORS.covered.border : COVERAGE_COLORS.partial.border);
          const fg = na ? 'var(--text-muted)' : (tone === 'ok' ? COVERAGE_COLORS.covered.fg : COVERAGE_COLORS.partial.fg);
          return (
            <div key={p.key} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}
              title={na ? '이 설계 밴드를 쓰는 요구사항이 없어 해당 없음' :
                `${p.label}: 설계 ${p.left}건 중 ${done}건 검증 완료` +
                (p.alt ? ` · 대체검증 ${p.alt}건 제외` : '') +
                (p.genuine ? ` · 진짜 결핍 ${p.genuine}건` : ' · 진짜 결핍 없음')}>
              <span style={{ width: 168, fontWeight: 600, color: 'var(--fg)', whiteSpace: 'nowrap' }}>
                {na ? '⊘' : (tone === 'ok' ? '✅' : '⚠')} {p.label}
              </span>
              <span style={{ width: 92, fontSize: 10, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{p.side}</span>
              <div style={{ flex: 1, minWidth: 80, height: 8, background: '#e5e7eb', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: barC }} />
              </div>
              <span style={{ width: 116, textAlign: 'right', color: fg, fontWeight: 700, whiteSpace: 'nowrap' }}>
                {na ? '해당 없음' : `${done}/${p.left} (${pct}%)`}
                {!na && p.genuine ? <span style={{ fontWeight: 600, fontSize: 10 }}> · 결핍 {p.genuine}</span> : null}
              </span>
            </div>
          );
        })}
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8 }}>
        비율 = (설계 요구 − 진짜 결핍) / 설계 요구. 비기능(SyTS/STS)·인터페이스(HSIS/SyITS)로 검증되는 요구는 '대체검증'으로 결핍에서 제외(은폐 아님 — 상세는 아래 공백 패널·finding 시트).
      </div>
    </div>
  );
}

// ── 추적성 요약 상세 (상태 총계 카드 · ASIL 등급별 분포/커버리지 · 밴드별 추적 현황) ──
// 전부 rows(전체·필터 무관)에서 파생 — CoverageBar와 동일 소스라 수치 lockstep. 백엔드 무변경.
// _STAGE_COLORS/_ASIL_COLORS/COVERAGE_COLORS/_TRACE_BANDS(모듈 상수)는 렌더 시점 접근이라 TDZ 무관.
function TraceExtraSummary({ coverage, extra, onFilter }) {
  if (!coverage || !extra) return null;
  const total = coverage.total || 0;
  const cards = [
    { key: 'all', label: '전체 요구사항', val: total, fg: 'var(--fg)', bg: 'var(--bg-elevated)', border: 'var(--border)' },
    { key: 'covered', label: '충족 (covered)', val: coverage.covered, fg: COVERAGE_COLORS.covered.fg, bg: COVERAGE_COLORS.covered.bg, border: COVERAGE_COLORS.covered.border },
    { key: 'partial', label: '부분 (partial)', val: coverage.partial, fg: COVERAGE_COLORS.partial.fg, bg: COVERAGE_COLORS.partial.bg, border: COVERAGE_COLORS.partial.border },
    { key: 'uncovered', label: '미충족 (uncovered)', val: coverage.uncovered, fg: COVERAGE_COLORS.uncovered.fg, bg: COVERAGE_COLORS.uncovered.bg, border: COVERAGE_COLORS.uncovered.border },
  ];
  const asilLabel = (g) => (g === '미상' ? '미상' : g === 'QM' ? 'QM' : `ASIL ${g}`);
  return (
    <div style={{ marginBottom: 12, border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', background: 'var(--bg)' }}>
      <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 10, color: 'var(--fg)' }}>
        추적성 요약 상세 <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)' }}>— 상태 총계 · ASIL 분포 · 밴드별 추적 (전체 {total}건 기준)</span>
      </div>

      {/* 1) 상태 총계 카드 — 클릭 시 매트릭스 상태 필터 (CoverageBar와 동일 onFilter) */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14 }}>
        {cards.map(c => {
          const pct = total ? Math.round((c.val / total) * 100) : 0;
          return (
            <button key={c.key} type="button" onClick={() => onFilter?.(c.key)}
              title={`${c.label} — 클릭하면 매트릭스를 이 상태로 필터`}
              style={{ flex: '1 1 130px', minWidth: 118, textAlign: 'left', padding: '9px 12px', borderRadius: 8,
                border: `1px solid ${c.border}`, background: c.bg, cursor: 'pointer' }}>
              <div style={{ fontSize: 11, color: c.fg, fontWeight: 600, marginBottom: 2 }}>{c.label}</div>
              <div style={{ fontSize: 22, fontWeight: 800, color: c.fg, lineHeight: 1.1 }}>{c.val}</div>
              {c.key !== 'all' && <div style={{ fontSize: 11, color: c.fg, opacity: 0.85 }}>{pct}%</div>}
            </button>
          );
        })}
      </div>

      {/* 2) ASIL 등급별 분포·커버리지 */}
      {extra.asilRows.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 6, color: 'var(--fg)' }}>
            ASIL 등급별 분포·커버리지 <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)' }}>— 등급별 요구사항 수와 검증(충족) 비율</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {extra.asilRows.map(a => {
              const pct = a.total ? Math.round((a.covered / a.total) * 100) : 0;
              const col = _ASIL_COLORS[a.grade] || '#6b7280';
              const pctFg = pct >= 70 ? COVERAGE_COLORS.covered.fg : pct >= 30 ? COVERAGE_COLORS.partial.fg : COVERAGE_COLORS.uncovered.fg;
              return (
                <div key={a.grade} style={{ flex: '1 1 150px', minWidth: 138, border: '1px solid var(--border)', borderRadius: 8, padding: '8px 10px', background: 'var(--bg-elevated)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#fff', background: col, padding: '1px 7px', borderRadius: 8, whiteSpace: 'nowrap' }}>{asilLabel(a.grade)}</span>
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>{a.total}</span>
                    <span style={{ flex: 1 }} />
                    <span style={{ fontSize: 11, fontWeight: 700, color: pctFg }}>{pct}%</span>
                  </div>
                  <div style={{ height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: col }} />
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 3 }}>검증 {a.covered}/{a.total}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 3) 밴드별 추적 현황 — 각 V-model 밴드에 연결된 요구사항 수 */}
      <div>
        <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 6, color: 'var(--fg)' }}>
          밴드별 추적 현황 <span style={{ fontWeight: 400, fontSize: 11, color: 'var(--text-muted)' }}>— 각 V-model 밴드에 연결된 요구사항 수 (전체 {total} 대비)</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {_TRACE_BANDS.map(b => {
            const cnt = extra.bandMap[b] || 0;
            const pct = total ? Math.round((cnt / total) * 100) : 0;
            const col = _STAGE_COLORS[b] || '#64748b';
            return (
              <div key={b} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                <span style={{ width: 84, fontWeight: 600, color: col, whiteSpace: 'nowrap' }}>{b}</span>
                <div style={{ flex: 1, minWidth: 80, height: 8, background: '#e5e7eb', borderRadius: 4, overflow: 'hidden' }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: col }} />
                </div>
                <span style={{ width: 104, textAlign: 'right', color: cnt ? 'var(--fg)' : 'var(--text-muted)', fontWeight: cnt ? 700 : 400, whiteSpace: 'nowrap' }}>{cnt}건 · {pct}%</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── hiMA식 교차 추적성 매트릭스 (additive '매트릭스' 뷰) ──
// 행=요구사항(target), 열=SDS 컴포넌트(related), 셀=O/공백. 추적 0건 행은 핑크 강조
// (hiMA 0카운트 밴드 대응). 데이터는 filtered rows에서 클라이언트 파생(필터 반영),
// '링크 테이블 ↓'는 서버 파생 link_table(감사 baseline)을 그대로 내보낸다.
const _TRACE_BANDS = ['SyRS', 'SDS', 'HSIS', 'UDS', 'STS', 'SUTS', 'SITS', 'SyTS', 'SyITS', 'VectorCAST'];

function _testId(t) {
  if (!t || typeof t !== 'object') return '';
  return String(t.testcase || t.subprogram || t.unit || t.id || '').trim();
}
// 백엔드 build_link_table 의 밴드 추출과 동일 규칙 — 화면/내보내기 일관성.
function _rowBands(row) {
  const tids = (arr) => (Array.isArray(arr) ? arr : []).map(_testId).filter(Boolean);
  return {
    SyRS: (Array.isArray(row.syrs_parents) ? row.syrs_parents : []).map(String).filter(Boolean),
    SDS: (Array.isArray(row.sds_components) ? row.sds_components : []).map(String).filter(Boolean),
    HSIS: (Array.isArray(row.hsis_signals) ? row.hsis_signals : []).map(String).filter(Boolean),
    UDS: (Array.isArray(row.source_ids) ? row.source_ids : []).map(String).filter(Boolean),
    STS: tids(row.sts_tests),
    SUTS: tids(row.suts_tests),
    SITS: tids(row.sits_tests),
    SyTS: tids(row.syts_tests),
    SyITS: tids(row.syits_tests),
    VectorCAST: (Array.isArray(row.tests) ? row.tests : [])
      .filter(t => t && t.source === 'VectorCAST').map(_testId).filter(Boolean),
  };
}

// ASIL 등급별 색(ISO 26262) — 셀 강조용. 미상/QM은 muted.
const _ASIL_COLORS = { D: '#991b1b', C: '#dc2626', B: '#b45309', A: '#2563eb', QM: '#6b7280' };

function CrossMatrixView({ rows, linkTable, fullMatrix, exportMeta }) {
  const { built, cols, hasAsil, byBand, asilSummary, gapCount, unknownCount } = useMemo(() => {
    const list = Array.isArray(rows) ? rows : [];
    // ASIL 결합(P5) — link_table.asil_coverage의 갭/등급 요약을 행에 join.
    const ac = linkTable?.asil_coverage || null;
    const gapMap = {};
    (ac?.gaps || []).forEach(g => { if (g?.target_id) gapMap[g.target_id] = Array.isArray(g.missing) ? g.missing : []; });
    const sdsCols = new Set();
    const b = list.map(row => {
      const rid = String(row?.requirement_id || '').trim();
      const bands = _rowBands(row || {});
      bands.SDS.forEach(c => sdsCols.add(c));
      // SyRS는 상위(부모) provenance라 하위 커버리지 total/핑크(0추적) 판정에서 제외(상위만 있는 요구를
      // covered로 오인 방지). 밴드 칩(byBand)엔 SyRS도 집계됨.
      const total = _TRACE_BANDS.reduce((n, bd) => n + (bd === 'SyRS' ? 0 : bands[bd].length), 0);
      const asil = String(row?.asil || row?.requirement_asil || row?.ASIL || '').trim().toUpperCase();
      return { rid, name: String(row?.requirement_name || '').trim(), bands, total, asil, gap: gapMap[rid] || null };
    }).filter(r => r.rid);
    const bb = {};
    _TRACE_BANDS.forEach(bd => {
      const linked = b.filter(r => r.bands[bd].length > 0).length;
      // 부동소수 % (소수 1자리) — hiMA 정수나눗셈 절삭 회피
      bb[bd] = { linked, total: b.length, pct: b.length ? Math.round(linked * 1000 / b.length) / 10 : 0 };
    });
    return {
      built: b, cols: Array.from(sdsCols).sort(), hasAsil: b.some(r => r.asil), byBand: bb,
      asilSummary: ac?.by_level || null,
      // 갭 수 — link_table 우선, 없으면(구 백엔드) 클라 파생 폴백(폴백 시 gapMap 비어 0).
      gapCount: ac?.gaps?.length ?? b.filter(r => r.gap?.length).length,
      // ASIL 미상(안전등급 미할당) 요구사항 수 — 갭과 별개 표면화(서버 파생).
      unknownCount: ac?.unknown_count ?? 0,
    };
  }, [rows, linkTable]);

  const downloadLinkTable = useCallback(() => {
    const payload = linkTable || { note: 'link_table 미제공(구버전 백엔드) — 화면은 filtered rows에서 파생됨' };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'trace_link_table.json';
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [linkTable]);

  // xlsx 내보내기(hiMA TrMatrixReport 대응) — 전체 매트릭스를 서버에서 xlsx로 렌더.
  // 바이너리 응답이라 api() 헬퍼 대신 raw fetch지만 X-User 헤더 + res.ok 검사 명시(X9).
  const [xlsxBusy, setXlsxBusy] = useState(false);
  const exportXlsx = useCallback(async () => {
    setXlsxBusy(true);
    try {
      const user = getUsername();
      const payload = { matrix: fullMatrix || { rows, link_table: linkTable }, meta: exportMeta || {} };
      const res = await fetch(buildUrl('/api/jenkins/uds/traceability-matrix/export-xlsx'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(user ? { 'X-User': user } : {}) },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const t = await res.text().catch(() => '');
        throw new Error(`HTTP ${res.status} ${t.slice(0, 140)}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = 'traceability_matrix.xlsx';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      alert(`Excel 내보내기 실패: ${e.message}`);
    } finally {
      setXlsxBusy(false);
    }
  }, [fullMatrix, rows, linkTable, exportMeta]);

  // ID 정합성 감사(trace_integrity) — fullMatrix.integrity에서 직접 읽음(link_table 아님).
  // hiMA exact-match가 silent하게 오인하는 클래스(정규화 충돌·dangling·placeholder)를 칩으로 표면화.
  const integ = fullMatrix?.integrity || null;
  const integStats = integ?.stats || {};
  // '정합성 ✓'는 진짜 결함(충돌·오참조 의심·placeholder)이 0일 때 표시. foreign(계층참조)은
  // 구조적이라 결함 아님 → 그것만 있으면 ✓ 유지(stats.clean과 별개의 '결함 없음' 판정).
  const integNoDefect = integ
    ? !(integStats.collision_count || integStats.dangling_suspect_count || integStats.placeholder_count)
    : true;
  const collisionTitle = (integ?.id_collisions || []).slice(0, 8)
    .map(c => `${c.canonical} ← raw ${c.variant_count}종`).join('  ·  ');
  const danglingTitle = Object.entries(integ?.dangling_by_namespace || {})
    .map(([band, ns]) => `${band}: ${Object.entries(ns || {}).map(([k, v]) => `${k}×${v}`).join(', ')}`).join('   ');
  // foreign(계층참조)의 V-model 계층 분포 — "어느 계층 ID인가" 명시(예: SwDS(설계)).
  const layerSummary = integ?.dangling_layer_summary || {};
  const layerEntries = Object.entries(layerSummary).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]);
  const layerTitle = layerEntries.map(([k, v]) => `${k} ${v}건`).join(' · ');
  // 단일 계층이 foreign 전부를 차지하면 칩 라벨에 그 계층명을 직접 노출(예: 'SwDS(설계) 참조').
  const foreignLayerLabel = layerEntries.length === 1 ? layerEntries[0][0] : null;

  if (built.length === 0) {
    return <div style={{ padding: 24, textAlign: 'center', color: 'var(--text-muted)' }}>표시할 요구사항이 없습니다.</div>;
  }

  const pink = COVERAGE_COLORS.uncovered;
  const Cell = ({ on }) => on
    ? <td style={{ textAlign: 'center', color: COVERAGE_COLORS.covered.fg, fontWeight: 700 }}>O</td>
    : <td style={{ textAlign: 'center', color: 'var(--border)' }}>·</td>;

  return (
    <div>
      {/* 밴드 커버리지 칩 + 링크테이블 내보내기 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '8px 0' }}>
        {_TRACE_BANDS.map(bd => (
          <span key={bd} title={`${bd}: ${byBand[bd].linked}/${byBand[bd].total} 요구사항 추적`}
            style={{ fontSize: 11, padding: '3px 8px', borderRadius: 12, border: '1px solid var(--border)', background: 'var(--bg)' }}>
            {bd} <strong>{byBand[bd].pct}%</strong>
          </span>
        ))}
        {hasAsil && (
          <span
            title={asilSummary
              ? Object.entries(asilSummary).map(([k, v]) => `${k}: ${v.targets}건(시험추적 ${v.test_covered}, 갭 ${v.gap})`).join('  ·  ')
              : 'ASIL 등급별 추적성 충족/갭'}
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 12, fontWeight: 600,
              border: `1px solid ${gapCount > 0 ? COVERAGE_COLORS.uncovered.border : COVERAGE_COLORS.covered.border}`,
              background: gapCount > 0 ? COVERAGE_COLORS.uncovered.bg : '#f0fdf4',
              color: gapCount > 0 ? COVERAGE_COLORS.uncovered.fg : COVERAGE_COLORS.covered.fg,
            }}>
            ASIL 갭 {gapCount}{gapCount > 0 ? ' ⚠' : ' ✓'}
          </span>
        )}
        {hasAsil && unknownCount > 0 && (
          <span title="연결 설계요소에 ASIL 등급이 없는 요구사항 — 안전등급 미할당(확인 요망). 갭과는 별개."
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 12, fontWeight: 600,
              border: `1px solid ${COVERAGE_COLORS.partial.border}`,
              background: COVERAGE_COLORS.partial.bg, color: COVERAGE_COLORS.partial.fg,
            }}>
            ASIL 미상 {unknownCount}
          </span>
        )}
        {/* ID 정합성 감사 칩 — hiMA WrongRelatedID/WrongName 대응(현재 빌더가 log로 삼키던 것 표면화) */}
        {integ && integStats.collision_count > 0 && (
          <span title={`정규화 충돌 — 서로 다른 raw 철자가 같은 ID로 silent 병합(표시 1개만 유지). ${collisionTitle}`}
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 12, fontWeight: 600,
              border: `1px solid ${COVERAGE_COLORS.uncovered.border}`,
              background: COVERAGE_COLORS.uncovered.bg, color: COVERAGE_COLORS.uncovered.fg,
            }}>
            ID 충돌 {integStats.collision_count} ⚠
          </span>
        )}
        {/* 오참조 의심(suspect) — SRS에 쓰이는 namespace인데 이 ID만 부재(오타/오참조, hiMA WrongRelatedID 본류) */}
        {integ && integStats.dangling_suspect_count > 0 && (
          <span title={`오참조 의심 — SRS에 쓰이는 namespace인데 해당 ID만 부재(오타/잘못된 RelatedID 가능성). namespace 분포 → ${danglingTitle}`}
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 12, fontWeight: 600,
              border: `1px solid ${COVERAGE_COLORS.uncovered.border}`,
              background: COVERAGE_COLORS.uncovered.bg, color: COVERAGE_COLORS.uncovered.fg,
            }}>
            오참조 의심 {integStats.dangling_suspect_count} ⚠
          </span>
        )}
        {/* 계층참조(foreign) — SRS에 없는 namespace = 다른 V-model 계층 ID(예 SwDS 설계). 구조적 정상, 정보성 */}
        {integ && integStats.dangling_foreign_count > 0 && (
          <span title={`계층참조 — SRS에 없는 namespace의 ID 참조. V-model상 다른 계층(예: SwSTR/SwST/SwTK는 SDS가 정의하는 설계 ID로 SRS 요구사항이 아님 → 정상). 결함 아니라 정보성.${layerTitle ? `\n계층 분포 → ${layerTitle}` : ''}\nnamespace → ${danglingTitle}`}
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 12, fontWeight: 600,
              border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text-muted)',
            }}>
            {foreignLayerLabel ? `${foreignLayerLabel} 참조` : '계층참조'} {integStats.dangling_foreign_count}
          </span>
        )}
        {integ && integStats.placeholder_count > 0 && (
          <span title="placeholder 참조 ID — 미완성 템플릿 토큰(SwCom_XX/TBD/?? 등). 설계/시험 미완 신호."
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 12, fontWeight: 600,
              border: `1px solid ${COVERAGE_COLORS.partial.border}`,
              background: COVERAGE_COLORS.partial.bg, color: COVERAGE_COLORS.partial.fg,
            }}>
            placeholder {integStats.placeholder_count}
          </span>
        )}
        {integ && integNoDefect && (
          <span title="ID 정합성 감사 통과 — 정규화 충돌·오참조 의심·placeholder 없음(계층참조는 구조적이라 결함 아님)"
            style={{
              fontSize: 11, padding: '3px 8px', borderRadius: 12, fontWeight: 600,
              border: `1px solid ${COVERAGE_COLORS.covered.border}`,
              background: '#f0fdf4', color: COVERAGE_COLORS.covered.fg,
            }}>
            정합성 ✓
          </span>
        )}
        <button className="btn-sm" onClick={downloadLinkTable}
          title="명시 RelatedID 링크 테이블(JSON) 내보내기 — 감사 baseline">링크 테이블 ↓</button>
        <button className="btn-sm" onClick={exportXlsx} disabled={xlsxBusy}
          title="추적성 매트릭스 전체를 xlsx로 내보내기 (교차표 + 링크테이블 + 커버리지 + ASIL 갭 + 정합성 감사)">
          {xlsxBusy ? '생성 중…' : 'Excel 내보내기 ↓'}</button>
      </div>
      <div style={{ overflow: 'auto', maxHeight: 600, border: '1px solid var(--border)', borderRadius: 6 }}>
        <table className="impact-table" style={{ minWidth: 700, fontSize: 11, borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={{ position: 'sticky', left: 0, background: 'var(--bg)', zIndex: 2 }}>요구사항</th>
              {hasAsil && <th>ASIL</th>}
              <th title="상위 시스템 요구(SyRS) — SR→SyRS→SwRS 체인. 이 요구가 유도된 상위 요구 수">SyRS↑</th>
              {cols.map(c => (
                <th key={c} title={c}
                  style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', whiteSpace: 'nowrap', maxHeight: 140 }}>{c}</th>
              ))}
              <th title="HW-SW 인터페이스(HSIS) 신호 수">HSIS</th>
              <th title="SDS→UDS 단위함수 수">UDS</th>
              <th title="SW 시험">STS</th><th title="단위 시험">SUTS</th><th title="통합 시험">SITS</th>
              <th title="시스템 시험(SyTS)">SyTS</th><th title="시스템 통합시험(SyITS)">SyITS</th>
              <th title="VectorCAST 실행추적">VC</th><th>합계</th>
            </tr>
          </thead>
          <tbody>
            {built.map(r => {
              const uncovered = r.total === 0;
              const gapRow = Array.isArray(r.gap) && r.gap.length > 0;
              const sdsSet = new Set(r.bands.SDS);
              // 우선순위: 추적0건(핑크) > ASIL 갭(앰버). 둘 다면 핑크가 더 심각.
              const rowBg = uncovered ? pink.bg : (gapRow ? COVERAGE_COLORS.partial.bg : undefined);
              return (
                <tr key={r.rid} style={rowBg ? { background: rowBg } : undefined}>
                  <td title={r.name} style={{ position: 'sticky', left: 0, background: rowBg || 'var(--bg)', whiteSpace: 'nowrap', fontWeight: 600 }}>{r.rid}</td>
                  {hasAsil && (
                    <td style={{ textAlign: 'center', color: _ASIL_COLORS[r.asil] || 'var(--text-muted)', fontWeight: 700 }}
                      title={gapRow ? `ASIL ${r.asil}: 시험 추적 부족 — ${r.gap.join(', ')}` : (r.asil ? `ASIL ${r.asil}` : 'ASIL 미상')}>
                      {r.asil || '–'}{gapRow ? ' ⚠' : ''}
                    </td>
                  )}
                  <td style={{ textAlign: 'center', color: r.bands.SyRS.length ? _STAGE_COLORS.UDS : 'var(--text-muted)' }}
                    title={r.bands.SyRS.length ? `상위 시스템 요구: ${r.bands.SyRS.join(', ')}` : '상위 요구 미추적'}>{r.bands.SyRS.length || ''}</td>
                  {cols.map(c => <Cell key={c} on={sdsSet.has(c)} />)}
                  <td style={{ textAlign: 'center' }}>{r.bands.HSIS.length || ''}</td>
                  <td style={{ textAlign: 'center' }}>{r.bands.UDS.length || ''}</td>
                  <Cell on={r.bands.STS.length > 0} />
                  <Cell on={r.bands.SUTS.length > 0} />
                  <Cell on={r.bands.SITS.length > 0} />
                  <Cell on={r.bands.SyTS.length > 0} />
                  <Cell on={r.bands.SyITS.length > 0} />
                  <Cell on={r.bands.VectorCAST.length > 0} />
                  <td style={{ textAlign: 'center', fontWeight: 700, color: uncovered ? pink.fg : 'var(--fg)' }}>{r.total}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '6px 0' }}>
        O = 추적됨 · 핑크 행 = 추적 0건(공백){hasAsil ? ' · 앰버 행 = ASIL 갭(안전등급 대비 시험 추적 부족) ⚠' : ''}{cols.length > 80 ? ` · SDS 열 ${cols.length}개(가로 스크롤)` : ''}
      </div>
    </div>
  );
}

// ── 모자이크 뷰 (additive '모자이크' 뷰) — hiMA TrMosaicReport 대응 ──────────────
// 교차표(매트릭스)가 req×SDS 상세 O/공백이라면, 모자이크는 req×밴드를 색상 셀(히트맵)로
// 압축 조망 — 추적 패턴/공백/FAIL을 한눈에. 셀 진하기=연결 수, 빨강=VectorCAST FAIL.
// 밴드 추출은 _rowBands(매트릭스/내보내기/백엔드 link_table과 lockstep) 재사용.
const _MOSAIC_BANDS = [
  { key: 'SDS', label: 'SDS' }, { key: 'HSIS', label: 'HSIS' }, { key: 'UDS', label: 'UDS' },
  { key: 'STS', label: 'STS' }, { key: 'SUTS', label: 'SUTS' }, { key: 'SITS', label: 'SITS' },
  { key: 'SyTS', label: 'SyTS' }, { key: 'SyITS', label: 'SyITS' }, { key: 'VectorCAST', label: 'VC' },
];
const _MOSAIC_FAIL_RE = /^(fail|failed|false|0|ng)$/i;
const TraceMosaicView = React.memo(function TraceMosaicView({ rows }) {
  // 행별 셀 데이터 사전 파생(메모이즈) — CrossMatrixView 패턴과 통일, rows 불변 시(비필터 리렌더) 재계산 회피.
  const cells = useMemo(() => {
    const list = Array.isArray(rows) ? rows : [];
    return list.map((r, idx) => {
      const bands = _rowBands(r || {});
      // FAIL은 cnt와 독립으로 도출 — 빈 testId FAIL이 cnt=0으로 은폐(회색)되지 않게 셀에서 우선 적용(I2).
      const vcFail = (Array.isArray(r.tests) ? r.tests : []).some(t => t && t.source === 'VectorCAST' && _MOSAIC_FAIL_RE.test(String(t.result || '')));
      return {
        rid: _rowReqId(r) || `row-${idx}`,
        name: String(r.requirement_name || ''),
        status: deriveStatus(r),
        bandCells: _MOSAIC_BANDS.map(b => ({ key: b.key, cnt: (bands[b.key] || []).length, isFail: b.key === 'VectorCAST' && vcFail })),
      };
    });
  }, [rows]);
  if (!cells.length) {
    return <div className="text-muted text-sm" style={{ padding: '16px 4px' }}>표시할 요구사항이 없습니다.</div>;
  }
  const headBg = 'var(--bg)';
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'auto', maxHeight: '72vh' }}>
      {/* 범례 — 셀 색=밴드별(상단 헤더 색), 진할수록 다건. 공백=테두리만(다크 적응), FAIL=빨강 고정. */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, padding: '8px 12px', background: headBg, borderBottom: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)' }}>
        <span style={{ fontWeight: 600 }}>모자이크 — 요구사항×밴드 추적 히트맵 (hiMA TrMosaicReport 대응)</span>
        <span>연결 = <b>밴드색</b>(상단 헤더), 진할수록 다건</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: 'transparent', border: '1px solid var(--border)', marginRight: 4, verticalAlign: 'middle' }} />공백</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#dc2626', marginRight: 4, verticalAlign: 'middle' }} />VectorCAST FAIL</span>
      </div>
      <table style={{ borderCollapse: 'collapse', fontSize: 10 }}>
        <thead>
          <tr style={{ background: headBg }}>
            <th style={{ position: 'sticky', left: 0, top: 0, background: headBg, padding: '4px 8px', textAlign: 'left', borderBottom: '1px solid var(--border)', zIndex: 3 }}>요구사항 ({cells.length})</th>
            <th style={{ position: 'sticky', top: 0, background: headBg, padding: '4px 6px', borderBottom: '1px solid var(--border)', zIndex: 2 }} title="추적 상태(deriveStatus)">상태</th>
            {_MOSAIC_BANDS.map(b => (
              <th key={b.key} title={b.key} style={{ position: 'sticky', top: 0, background: headBg, padding: '4px 3px', borderBottom: '1px solid var(--border)', color: _STAGE_COLORS[b.key] || 'var(--fg)', fontWeight: 700, fontSize: 9, minWidth: 26, zIndex: 2 }}>{b.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {cells.map((c) => {
            const sc = COVERAGE_COLORS[c.status] || {};
            return (
              <tr key={c.rid}>
                <td title={c.name ? `${c.rid} — ${c.name}` : c.rid}
                  style={{ position: 'sticky', left: 0, background: headBg, padding: '2px 8px', fontFamily: 'monospace', whiteSpace: 'nowrap', borderBottom: '1px solid var(--border)', maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis', zIndex: 1 }}>{c.rid}</td>
                <td style={{ padding: '2px 4px', textAlign: 'center', borderBottom: '1px solid var(--border)' }}>
                  <span title={c.status} style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: sc.border || '#9ca3af' }} />
                </td>
                {c.bandCells.map(bc => {
                  const base = _STAGE_COLORS[bc.key] || '#16a34a';
                  // FAIL=빨강 고정(불투명, cnt 독립) · 공백=토큰 테두리만(다크 적응) · 그 외 밴드색+연결수 진하기.
                  const op = (bc.isFail || bc.cnt === 0) ? 1 : Math.min(1, 0.4 + Math.log2(bc.cnt + 1) * 0.2);
                  return (
                    <td key={bc.key} title={`${c.rid} · ${bc.key}: ${bc.cnt}건${bc.isFail ? ' (FAIL 포함)' : ''}`}
                      style={{ padding: '1px 2px', borderBottom: '1px solid var(--border)' }}>
                      <div style={{ width: 22, height: 14, margin: '0 auto', borderRadius: 2,
                        background: bc.isFail ? '#dc2626' : bc.cnt === 0 ? 'transparent' : base, opacity: op,
                        border: bc.isFail ? '1px solid #991b1b' : bc.cnt === 0 ? '1px solid var(--border)' : 'none' }} />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
});

function TraceMatrix({ matrix, focusFunctions = null, onClearFocus = null,
  job = null, cacheRoot = '', buildSelector = 'lastSuccessfulBuild', sourceRoot = '', toast = () => {} }) {
  const inner = matrix?.matrix ?? matrix;
  const rows = Array.isArray(inner?.rows) ? inner.rows : (Array.isArray(inner?.items) ? inner.items : []);
  const summary = inner?.summary ?? matrix?.summary;
  const dataSources = matrix?._dataSources || [];
  // 역방향 추적성 공백 — 시험은 됐으나 이 SRS에 안 닿는 VectorCAST 함수(백엔드 unmapped_vcast).
  // 트리 'SRS 미추적 시험 포함' 토글이 의미 3버킷으로 묶어 별도 루트로 표시한다.
  // unmappedSupported: 키 자체 부재(로컬 파일모드 — 미계산)와 빈 배열(공백 0)을 구분(deep-analyze).
  const unmappedVcast = Array.isArray(inner?.unmapped_vcast) ? inner.unmapped_vcast : _EMPTY_ARR;
  const unmappedSupported = inner != null && inner.unmapped_vcast !== undefined;

  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');   // STS/SUTS/VectorCAST
  const [reqTypeFilter, setReqTypeFilter] = useState('all'); // SwRS/SwTR/etc
  const [testResultFilter, setTestResultFilter] = useState('all'); // pass/fail/all
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [currentPage, setCurrentPage] = useState(0);
  const [sortKey, setSortKey] = useState(null);    // 'req_id' | 'func_count' | 'test_count' | 'status'
  const [sortAsc, setSortAsc] = useState(true);
  const [expandedReqId, setExpandedReqId] = useState(null); // expanded row by requirement_id
  const [viewMode, setViewMode] = useState('table');        // 'table' | 'tree' — additive tree view (기존 표는 무변경)
  // 표의 UDS 함수 클릭 → 함수그래프/콜트리로 이동(검색 입력 없이 바로). 탭 직접 클릭 시엔 시드 비워 첫 함수로.
  const [funcGraphSeed, setFuncGraphSeed] = useState('');
  const [callTreeSeed, setCallTreeSeed] = useState('');
  const [reqGraphSeed, setReqGraphSeed] = useState('');     // '그래프' 탭 전체뷰 진입 시드(요구사항 ID). ''=첫 항목
  // 표 행 인라인 뷰 — 펼친 행 안에서 한 번에 하나(콜트리/함수그래프/추적그래프)를 탭 전환 없이 표시. null=닫힘.
  const [inlineView, setInlineView] = useState(null);       // { type:'calltree'|'funcgraph'|'reqgraph', key:string } | null
  const [expandedTreeNodes, setExpandedTreeNodes] = useState(() => new Set()); // 트리 노드 id 집합 (다중 펼침)
  const [includeUnmapped, setIncludeUnmapped] = useState(false); // 트리: SRS 미추적 시험 별도 루트 표시 토글

  // 콜트리 진입 함수(entry) 자동 시드 후보 — 매트릭스 row의 source_ids(UDS 함수)에서 함수명
  // 토큰만 추출해 datalist로 제안한다(콜트리 entry는 빌드의 known 함수명과 일치해야 적중).
  const callTreeSeeds = useMemo(() => {
    const set = new Set();
    for (const r of (rows || [])) {
      for (const s of (Array.isArray(r.source_ids) ? r.source_ids : [])) {
        const fn = String(s || '').split(/[\s(]/)[0].trim();
        if (fn) set.add(fn);
      }
    }
    return Array.from(set).slice(0, 500);
  }, [rows]);

  // 표 UDS 함수 클릭 → 해당 함수 뷰로 이동. funcgraph는 원문(display) 매칭(_normFn), 콜트리는 빌드 함수명(괄호 앞 토큰).
  const gotoFuncView = useCallback((fn, mode) => {
    const raw = String(fn || '').trim();
    if (!raw) return;
    if (mode === 'calltree') {
      const bare = raw.split(/[\s(]/)[0].trim();
      if (bare) { setCallTreeSeed(bare); setViewMode('calltree'); }
    } else {
      setFuncGraphSeed(raw); setViewMode('funcgraph');
    }
  }, []);

  // 표 행 인라인 뷰 토글 — 같은 (type,key,reqId)를 다시 누르면 닫고, 다르면 그것으로 교체(한 번에 하나).
  // reqId(소유 행)를 함께 담아, 인접 행 펼침 시 렌더 가드가 '이 행 소속'을 선언적으로 판정 →
  // 행 전환 리셋 effect가 paint 후 실행되더라도 이전 행 패널이 새 행에 마운트(헛 fetch·깜빡임)되지 않음.
  const toggleInline = useCallback((type, key, reqId) => {
    setInlineView(prev => (prev && prev.type === type && prev.key === key && prev.reqId === reqId) ? null : { type, key, reqId });
  }, []);

  // Reset page when rows change (e.g., new matrix data)
  useEffect(() => { setCurrentPage(0); setExpandedReqId(null); setExpandedTreeNodes(new Set()); }, [rows]);

  // 펼친 행이 바뀌면(다른 행 열기·현재 행 접기) 인라인 뷰도 닫는다 — 이전 행 함수/요구사항의 뷰가 남는 것 방지.
  useEffect(() => { setInlineView(null); }, [expandedReqId]);

  // 트리 펼침은 page-absolute nodeId를 쓰므로 페이지 이동엔 유지되지만, 행 집합/정렬/
  // 페이지크기가 바뀌면 절대 인덱스가 다른 행을 가리킬 수 있어(특히 anonymous 행) 초기화한다.
  useEffect(() => { setExpandedTreeNodes(new Set()); },
    [searchTerm, statusFilter, sourceFilter, reqTypeFilter, testResultFilter, sortKey, sortAsc, pageSize]);

  // 트리 노드 펼침 토글 — 불변 업데이트(새 Set)로 React 리렌더 보장
  const toggleTreeNode = useCallback((nodeId) => {
    setExpandedTreeNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return next;
    });
  }, []);

  // Drill-down: jump the matrix straight to the uncovered row the user clicked
  // in the Top-N list. Uses the existing filter+search+expand state so the UX
  // mirrors a manual click; no scrollIntoView gymnastics needed.
  const handlePickUncovered = useCallback((reqId) => {
    setStatusFilter('uncovered');
    setSearchTerm(reqId);
    setCurrentPage(0);
    setExpandedReqId(reqId);
  }, []);

  // Extract unique requirement types (SwRS, SwTR, SyRS, etc.)
  // _rowReqId returns String(id).trim() — protects against numeric ids (e.g. r.id=42)
  // that would crash on .match/.toUpperCase if used directly.
  const reqTypes = useMemo(() => {
    const types = new Set();
    for (const r of rows) {
      const id = _rowReqId(r);
      const m = id.match(/^(Sw[A-Z]{1,4}|Sy[A-Z]{1,4})/i);
      if (m) types.add(m[1].toUpperCase());
    }
    return [...types].sort();
  }, [rows]);

  // Extract unique data sources present in rows
  const availableSources = useMemo(() => {
    const srcs = new Set();
    for (const r of rows) {
      for (const t of (r.tests || [])) {
        if (t.source) srcs.add(t.source);
      }
    }
    // V-model 정준 순서(알파벳 대신) — SW시험(STS→SUTS→SITS) 다음 시스템시험(SyTS→SyITS),
    // 마지막 VectorCAST. 알파벳 정렬은 SyITS/SyTS를 SUTS 뒤에 흩어 놓아 발견성이 떨어짐.
    const ORDER = ['STS', 'SUTS', 'SITS', 'SyTS', 'SyITS', 'VectorCAST'];
    return [...srcs].sort((a, b) => {
      const ia = ORDER.indexOf(a), ib = ORDER.indexOf(b);
      return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || String(a).localeCompare(String(b));
    });
  }, [rows]);

  // Coverage statistics
  const coverage = useMemo(() => {
    if (!rows.length) return null;
    let covered = 0, partial = 0, uncovered = 0;
    let partialWithDesign = 0; // partial 중 설계 데이터가 있는 것
    for (const r of rows) {
      const st = deriveStatus(r);
      if (st === 'covered') covered++;
      else if (st === 'partial') {
        partial++;
        if (hasDesignData(r)) partialWithDesign++;
      }
      else uncovered++;
    }
    const total = rows.length;
    // SW 구현 대상: 설계가 존재하는 요구사항 (covered + partial with design)
    const designTotal = covered + partialWithDesign;
    return { covered, partial, uncovered, total, partialWithDesign, designTotal, pct: total > 0 ? Math.round((covered / total) * 100) : 0 };
  }, [rows]);

  // ASIL 등급별 분포 + 밴드별 추적 현황 (TraceExtraSummary용) — 전체 rows 파생, coverage와 동일 소스.
  const extraSummary = useMemo(() => {
    if (!rows.length) return null;
    const asilMap = {};   // grade -> { total, covered }
    const bandMap = {};   // band -> 연결 요구사항 수
    for (const bk of _TRACE_BANDS) bandMap[bk] = 0;
    for (const r of rows) {
      const raw = String(r.asil || r.requirement_asil || r.ASIL || '').toUpperCase().trim();
      const g = (raw === 'D' || raw === 'C' || raw === 'B' || raw === 'A' || raw === 'QM') ? raw : '미상';
      const cell = asilMap[g] || (asilMap[g] = { total: 0, covered: 0 });
      cell.total++;
      if (deriveStatus(r) === 'covered') cell.covered++;
      const bands = _rowBands(r);
      for (const bk of _TRACE_BANDS) if (bands[bk] && bands[bk].length) bandMap[bk]++;
    }
    const order = ['D', 'C', 'B', 'A', 'QM', '미상'];
    const asilRows = order.filter(g => asilMap[g]).map(g => ({ grade: g, total: asilMap[g].total, covered: asilMap[g].covered }));
    return { asilRows, bandMap };
  }, [rows]);

  // V-Model 단계별 추적성 공백 — 정방향(설계 단절)·역방향(미추적 시험)을 viewMode와
  // 무관하게 항상 노출(deep-analyze WARNING: 공백이 covered 녹색/토글 뒤에 묻힘).
  //  - sdsNoUds: SRS→SDS는 됐으나 SDS→UDS 끊김(설계 단절). 단 HSIS 실현(인터페이스 요구)은 제외.
  //  - udsUntestedFns: UDS 함수 중 SUTS 단위시험 미연결(정방향 검증 공백)
  //  - orphanSuts: 어느 UDS 함수에도 안 붙는 SUTS(역방향: 시험有 설계無)
  //  - unmappedTotal/Suts: VectorCAST 미추적(역방향) — 백엔드 summary 우선
  const gapStats = useMemo(() => {
    let sdsNoUds = 0, sdsNoUdsGenuine = 0, sdsNoUdsAlt = 0, udsUntestedFns = 0, udsFnTotal = 0, orphanSuts = 0;
    // V-model 수평쌍 공백: 설계(좌) 밴드는 있으나 대응 시험(우) 밴드가 없는 요구사항 수.
    // covered=any-design AND any-test라 쌍 불일치(예: SDS 설계는 있는데 SITS 통합시험 없음)가
    // covered 녹색에 가려진다 → 밴드 SSOT(_rowBands)로 쌍별 결핍을 표면화(감사 신호).
    // ★모드 게이트: local 파일모드(local_traceability)는 band별 *_tests/VectorCAST를 안 채우고
    //   flat tests[]만 쓴다 → _rowBands 시험밴드가 전부 빈 배열이라 쌍 공백이 '문서 미로드'를
    //   '진짜 공백'으로 오인해 전 설계 요구를 거짓 집계한다. band 필드가 실제로 채워지는 전체
    //   Jenkins 매트릭스(unmappedSupported)에서만 산출한다. rightPresent로는 '미로드'와 '100%
    //   실공백'을 구분 못 하므로(둘 다 빈 밴드) 모드 신호를 쓴다.
    const supportsPairs = unmappedSupported;
    // 각 수평쌍: 결핍 카운트 + 좌(설계) 밴드 present 분모(*Left) — 상단 V-model 요약 카드의 완성비율용.
    const pg = {
      sdsNoSits: 0, sdsNoSitsGenuine: 0, sdsNoSitsAlt: 0, sdsLeft: 0,
      udsNoSuts: 0, udsLeft: 0, hsisNoSyits: 0, hsisLeft: 0,
      syrsNoSyts: 0, syrsLeft: 0, srcNoVc: 0, srcLeft: 0,
    };
    for (const r of rows) {
      const sds = Array.isArray(r.sds_components) ? r.sds_components : [];
      const uds = Array.isArray(r.source_ids) ? r.source_ids : [];
      // HSIS 크레딧: 인터페이스 요구(SwEI 등)는 SDS→HSIS로 실현되어 UDS 함수가 없는 게 정상.
      // HSIS 신호가 있으면 SDS→UDS 단절이 아니라 인터페이스 실현이므로 설계 단절에서 제외.
      const hsis = Array.isArray(r.hsis_signals) ? r.hsis_signals : [];
      if (sds.length > 0 && uds.length === 0 && hsis.length === 0) {
        sdsNoUds++;
        // 정직화: 비기능 요구는 UDS 분해 없이 시험으로 직접 검증(결정1)되므로 '설계 단절'이 아님 —
        // 실제 시험이 있을 때만 대체검증으로 크레딧(증거 기반, 은폐 방지). 나머지는 진짜 갭.
        if (_reqClass(r.requirement_id) === 'nonfunctional' && hasTestData(r)) sdsNoUdsAlt++;
        else sdsNoUdsGenuine++;
      }
      const m = _unitTestMap(r);
      udsFnTotal += uds.length;
      for (const fn of uds) if (!((m.get(_normFn(fn)) || []).length)) udsUntestedFns++;
      const udsSet = new Set(uds.map(_normFn));
      for (const t of _stageMembers(r, 'SUTS').items) {
        const u = _normFn(t && t.unit);
        if (u && !udsSet.has(u)) orphanSuts++;
      }
      // 수평쌍 공백 (밴드 추출은 매트릭스/링크테이블과 동일 SSOT _rowBands 재사용) — 전체 매트릭스 모드만.
      if (supportsPairs) {
        const b = _rowBands(r);
        if (b.SDS.length && !b.SITS.length) {
          pg.sdsNoSits++;
          // 정직화: 비기능(SyTS/STS로 검증)·인터페이스(HSIS/SyITS로 실현·통합)는 SITS 구조적 불요 —
          // 대체 밴드가 실제 존재할 때만 크레딧. 나머지(기능요구·상위검증 없음)는 진짜 통합시험 갭.
          const _cls = _reqClass(r.requirement_id);
          const _alt = (_cls === 'nonfunctional' && (b.SyTS.length || b.STS.length))
            || (_cls === 'interface' && (b.HSIS.length || b.SyITS.length));
          if (_alt) pg.sdsNoSitsAlt++; else pg.sdsNoSitsGenuine++;
        }
        if (b.UDS.length && !b.SUTS.length) pg.udsNoSuts++;
        if (b.HSIS.length && !b.SyITS.length) pg.hsisNoSyits++;
        if (b.SyRS.length && !b.SyTS.length) pg.syrsNoSyts++;
        if (b.UDS.length && !b.VectorCAST.length) pg.srcNoVc++;
        // 좌(설계) 밴드 present 분모 — 완성비율(=(좌−결핍)/좌) 계산용.
        if (b.SDS.length) pg.sdsLeft++;
        if (b.UDS.length) { pg.udsLeft++; pg.srcLeft++; }
        if (b.HSIS.length) pg.hsisLeft++;
        if (b.SyRS.length) pg.syrsLeft++;
      }
    }
    const unmappedTotal = summary?.unmapped_vcast_count ?? unmappedVcast.length;
    const unmappedSuts = summary?.unmapped_suts_tested ?? unmappedVcast.filter(u => u && u.category === 'suts_tested').length;
    const pairHasAny = supportsPairs && !!(pg.sdsNoSits || pg.udsNoSuts || pg.hsisNoSyits || pg.syrsNoSyts || pg.srcNoVc);
    const hasAny = sdsNoUds || udsUntestedFns || orphanSuts || unmappedTotal || pairHasAny;
    return { sdsNoUds, sdsNoUdsGenuine, sdsNoUdsAlt, udsUntestedFns, udsFnTotal, orphanSuts, unmappedTotal, unmappedSuts, pairGaps: pg, pairSupported: supportsPairs, pairHasAny, hasAny };
  }, [rows, summary, unmappedVcast, unmappedSupported]);

  // Filter + sort
  const filtered = useMemo(() => {
    let result = rows;

    // 영향도 연동 focus — 변경 영향 함수(source_ids 교집합)가 닿는 요구사항 행만.
    if (focusFunctions && focusFunctions.length) {
      const fset = new Set(focusFunctions.map(f => String(f).trim().toLowerCase()));
      result = result.filter(r =>
        (r.source_ids ?? []).some(s => fset.has(String(s).trim().toLowerCase()))
      );
    }

    // Status filter
    if (statusFilter !== 'all') {
      result = result.filter(r => deriveStatus(r) === statusFilter);
    }

    // Source filter — show only rows that have tests from the selected source
    if (sourceFilter !== 'all') {
      result = result.filter(r =>
        (r.tests || []).some(t => t.source === sourceFilter)
      );
    }

    // Requirement type filter
    if (reqTypeFilter !== 'all') {
      result = result.filter(r => {
        const id = _rowReqId(r).toUpperCase();
        return id.startsWith(reqTypeFilter);
      });
    }

    // Test result filter
    if (testResultFilter === 'pass') {
      result = result.filter(r => (r.pass_count ?? 0) > 0);
    } else if (testResultFilter === 'fail') {
      result = result.filter(r => (r.fail_count ?? 0) > 0);
    } else if (testResultFilter === 'no_test') {
      result = result.filter(r => (r.test_count ?? 0) === 0);
    }

    // Text search
    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      result = result.filter(r =>
        _rowReqId(r).toLowerCase().includes(q) ||
        (r.source_ids ?? []).join(' ').toLowerCase().includes(q) ||
        (r.test_ids ?? []).join(' ').toLowerCase().includes(q)
      );
    }

    // Sort
    if (sortKey) {
      result = [...result].sort((a, b) => {
        let va, vb;
        if (sortKey === 'req_id') {
          va = _rowReqId(a);
          vb = _rowReqId(b);
          return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        if (sortKey === 'func_count') {
          va = (a.source_ids ?? []).length; vb = (b.source_ids ?? []).length;
        } else if (sortKey === 'test_count') {
          va = a.test_count ?? 0; vb = b.test_count ?? 0;
        } else if (sortKey === 'status') {
          const order = { covered: 0, partial: 1, uncovered: 2 };
          va = order[deriveStatus(a)] ?? 3; vb = order[deriveStatus(b)] ?? 3;
        } else {
          va = 0; vb = 0;
        }
        return sortAsc ? va - vb : vb - va;
      });
    }

    return result;
  }, [rows, searchTerm, statusFilter, sourceFilter, reqTypeFilter, testResultFilter, sortKey, sortAsc, focusFunctions]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(currentPage, totalPages - 1);
  const displayedRows = filtered.slice(safePage * pageSize, (safePage + 1) * pageSize);

  // Sort toggle handler
  const toggleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  };
  const sortIcon = (key) => sortKey === key ? (sortAsc ? ' \u25B2' : ' \u25BC') : '';

  // CSV export (RFC 4180 compliant)
  const csvEscape = (val) => {
    const s = String(val ?? '');
    return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const exportCSV = () => {
    // 감사 증빙: Pass/Fail은 VectorCAST 실행 결과만(STS/SUTS/SITS는 매핑·통과 아님).
    // 설계단절·단위시험미연결 공백 플래그 + 역방향 미추적 섹션을 포함해 완전 스냅샷으로 만든다.
    const header = ['요구사항 ID', '요구사항명', 'SDS 컴포넌트(T1)', 'UDS 함수(T2)', '함수 수', 'STS TC(T3)', 'SUTS TC(T4)', 'SITS TC(T5)', 'VectorCAST', '테스트 매핑 수', 'VectorCAST실행 Pass', 'VectorCAST실행 Fail', '상태(매핑)', '설계단절(SDS有UDS無)', 'UDS함수 단위시험미연결', '신뢰도'];
    const csvRows = [header.join(',')];
    // 화면 필터와 무관하게 전체 rows를 내보낸다(필터 종속 재현성 문제 해소 — deep-analyze).
    for (const r of rows) {
      const status = deriveStatus(r);
      const rawTests = Array.isArray(r.tests) ? r.tests : [];
      const stsCount = (r.sts_tests ?? rawTests.filter(t => t.source === 'STS')).length;
      const sutsCount = (r.suts_tests ?? rawTests.filter(t => t.source === 'SUTS')).length;
      const sitsCount = (r.sits_tests ?? rawTests.filter(t => t.source === 'SITS')).length;
      const vcastCount = rawTests.filter(t => t.source === 'VectorCAST').length;
      const sds = Array.isArray(r.sds_components) ? r.sds_components : [];
      const uds = Array.isArray(r.source_ids) ? r.source_ids : [];
      const designBreak = sds.length > 0 && uds.length === 0 ? 'Y' : '';
      const m = _unitTestMap(r);
      const untestedFns = uds.filter(fn => !((m.get(_normFn(fn)) || []).length)).length;
      csvRows.push([
        csvEscape(r.requirement_id ?? ''),
        csvEscape(r.requirement_name ?? ''),
        csvEscape(sds.join('; ')),
        csvEscape(uds.join('; ')),
        uds.length,
        stsCount,
        sutsCount,
        sitsCount,
        vcastCount,
        r.test_count ?? 0,
        r.pass_count ?? 0,
        r.fail_count ?? 0,
        status,
        designBreak,
        untestedFns,
        r.confidence ?? '-',
      ].join(','));
    }
    // 역방향 추적성 공백 — 'SRS 미추적 시험'(시험됐으나 이 SRS에 안 닿음) 별도 섹션.
    if (unmappedVcast.length > 0) {
      csvRows.push('');
      csvRows.push(csvEscape(`# SRS 미추적 시험 (역방향 공백 ${unmappedVcast.length}종 — 시험됐으나 이 SRS 요구사항 미명세)`));
      csvRows.push(['Subprogram', '해석된 함수', 'SDS 설계', 'UDS 설계', 'ISO계층', '분류', 'VectorCAST 결과'].join(','));
      for (const u of unmappedVcast) {
        const sr = Array.isArray(u.sds_reqs) ? u.sds_reqs : [];
        const uf = Array.isArray(u.uds_funcs) ? u.uds_funcs : [];
        csvRows.push([
          csvEscape(u.subprogram ?? ''),
          csvEscape((Array.isArray(u.resolved_funcs) ? u.resolved_funcs : []).join('; ')),
          csvEscape(sr.length ? sr.join('; ') : '미명세'),
          csvEscape(u.in_uds === true ? (uf.length ? uf.join('; ') : '설계됨') : (u.in_uds === false ? '미설계' : '')),
          csvEscape(LAYER_LABELS[u.layer] ?? ''),
          csvEscape(u.category ?? ''),
          csvEscape(u.result ?? ''),
        ].join(','));
      }
    }
    const blob = new Blob(['\uFEFF' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `traceability_matrix_${new Date().toISOString().slice(0,10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  if (!rows.length) {
    return (
      <div className="text-muted text-sm" style={{ padding: 12, background: 'var(--bg)', borderRadius: 6 }}>
        매트릭스 데이터에 요구사항이 없습니다. SRS 경로를 확인하세요.
      </div>
    );
  }

  return (
    <div>
      {/* 영향도 분석 연동 — 변경 영향 함수로 필터 중임을 명시 + 해제 */}
      {focusFunctions && focusFunctions.length > 0 && (
        <div style={{ margin: '0 0 12px', padding: '8px 12px', borderRadius: 6, border: '1px solid var(--accent)',
          background: 'var(--color-info-soft, rgba(59,130,246,0.08))', display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12 }}>
            🔗 <b>영향도 분석 연동</b> — 변경 영향 함수 <b>{focusFunctions.length}개</b>가 닿는 요구사항만 표시 중
            <span className="text-muted" style={{ marginLeft: 6, fontSize: 11 }}>
              ({filtered.length}/{rows.length}행) — 이 함수들의 추적성·커버리지·공백을 확인하세요
            </span>
          </span>
          <span style={{ flex: 1 }} />
          {onClearFocus && (
            <button className="btn-sm" onClick={onClearFocus} title="필터 해제하고 전체 매트릭스 보기">필터 해제</button>
          )}
        </div>
      )}
      {/* Coverage summary table */}
      {coverage && (
        <div style={{ marginBottom: 16, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', background: 'var(--bg)', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 13, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>추적성 요약</span>
            {summary?.total_tests > 0 && (
              <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }} title="P/F는 VectorCAST 실행 결과만. SW시험(STS/SUTS/SITS)·시스템시험(SyTS/SyITS)은 '매핑 존재'(중립)이며 시험 통과 아님 — 매핑 엔트리는 Total에 포함되나 P/F 대상이 아님.">
                실행검증(VectorCAST) {summary.total_pass ?? 0}P / {summary.total_fail ?? 0}F · 매핑 {summary.total_tests}건(SW시험 STS/SUTS/SITS·시스템시험 SyTS/SyITS=매핑·통과 아님)
              </span>
            )}
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg)' }}>
                <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>구분</th>
                <th style={{ padding: '8px 12px', textAlign: 'center', borderBottom: '1px solid var(--border)', width: 80 }}>건수</th>
                <th style={{ padding: '8px 12px', textAlign: 'center', borderBottom: '1px solid var(--border)', width: 80 }}>비율</th>
                <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>설명</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ padding: '6px 12px', fontWeight: 600 }}>전체 요구사항 (SRS)</td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14 }}>{coverage.total}</td>
                <td style={{ padding: '6px 12px', textAlign: 'center' }}>100%</td>
                <td style={{ padding: '6px 12px', color: 'var(--text-muted)' }}>SRS 문서에서 추출된 요구사항</td>
              </tr>
              <tr style={{ background: COVERAGE_COLORS.covered.bg }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: COVERAGE_COLORS.covered.fg }}>
                  Covered (설계·비기능 + 시험 <em>매핑</em>)
                </td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.covered.fg }}>{coverage.covered}</td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.covered.fg }}>{coverage.pct}%</td>
                <td style={{ padding: '6px 12px', fontSize: 11 }}>설계[SW: SDS·UDS / 인터페이스: HSIS] 또는 비기능요구 + 시험[SW: STS·SUTS·SITS / 시스템: SyTS·SyITS / 실행: VectorCAST] <strong>매핑</strong> 존재 — 매핑일 뿐 시험 통과 아님(P/F는 VectorCAST만)</td>
              </tr>
              {coverage.partial > 0 && (
                <tr style={{ background: COVERAGE_COLORS.partial.bg }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600, color: COVERAGE_COLORS.partial.fg }}>
                    Partial (설계·시험 중 한쪽만)
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.partial.fg }}>{coverage.partial}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.partial.fg }}>{coverage.total > 0 ? Math.round(coverage.partial / coverage.total * 100) : 0}%</td>
                  <td style={{ padding: '6px 12px', fontSize: 11 }}>설계·시험 중 한쪽만 매핑 — 예: 시험(STS·SUTS·SITS·SyTS·SyITS) 있으나 설계(SDS·UDS) 없음. 기능요구는 partial 유지(비기능요구 SwNTR/SyNTR은 covered 승격)</td>
                </tr>
              )}
              {coverage.uncovered > 0 && (
                <tr style={{ background: COVERAGE_COLORS.uncovered.bg }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600, color: COVERAGE_COLORS.uncovered.fg }}>
                    Uncovered (미추적)
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.uncovered.fg }}>{coverage.uncovered}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.uncovered.fg }}>{coverage.total > 0 ? Math.round(coverage.uncovered / coverage.total * 100) : 0}%</td>
                  <td style={{ padding: '6px 12px', fontSize: 11 }}>설계 및 테스트 매핑 모두 없음</td>
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr style={{ borderTop: '2px solid var(--border)', background: 'var(--bg)' }}>
                <td style={{ padding: '8px 12px', fontWeight: 700 }}>SW 구현 대상 커버리지</td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {coverage.covered}/{coverage.designTotal}
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {coverage.designTotal > 0 ? Math.round(coverage.covered / coverage.designTotal * 100) : 0}%
                </td>
                <td style={{ padding: '8px 12px', fontSize: 11, color: 'var(--text-muted)' }}>
                  검증 완료 또는 설계(SDS·UDS·HSIS) 매핑이 존재하는 요구사항 중 검증 완료 비율
                </td>
              </tr>
              <tr style={{ background: 'var(--bg)' }}>
                <td style={{ padding: '8px 12px', fontWeight: 700 }}>테스트 추적 커버리지</td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {summary?.mapped_test_count ?? (coverage.covered + coverage.partial)}/{coverage.total}
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {Math.round(((summary?.mapped_test_count ?? (coverage.covered + coverage.partial)) / coverage.total) * 100)}%
                </td>
                <td style={{ padding: '8px 12px', fontSize: 11, color: 'var(--text-muted)' }}>
                  SW시험(STS·SUTS·SITS)·시스템시험(SyTS·SyITS)·실행(VectorCAST) 테스트 매핑 기준
                </td>
              </tr>
            </tfoot>
          </table>
          {/* 시스템 레벨 밴드 연결 카운트 (정보성) — SW V-model 외 시스템·인터페이스 레벨 추적. 0건이면 숨김(데이터 부재 환경 graceful) */}
          {(() => {
            const sysBands = [
              { label: 'HSIS', n: summary?.mapped_hsis_count ?? 0, color: '#0e7490', t: 'HW-SW 인터페이스 명세' },
              { label: 'SyTS', n: summary?.mapped_syts_count ?? 0, color: '#9333ea', t: '시스템 시험' },
              { label: 'SyITS', n: summary?.mapped_syits_count ?? 0, color: '#c026d3', t: '시스템 통합시험' },
              { label: '상위(SyRS)', n: summary?.mapped_syrs_count ?? 0, color: '#64748b', t: '시스템 요구사항(상위 추적·커버리지 분모 제외)' },
            ].filter(b => b.n > 0);
            if (!sysBands.length) return null;
            return (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', padding: '8px 14px', borderTop: '1px solid var(--border)', background: 'var(--bg)', fontSize: 11 }}>
                <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>시스템 레벨 연결</span>
                {sysBands.map(b => (
                  <span key={b.label} title={b.t} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 12, background: b.color + '26', color: b.color, border: `1px solid ${b.color}59`, fontWeight: 600 }}>
                    {b.label} {b.n}
                  </span>
                ))}
                <span style={{ color: 'var(--text-muted)' }}>요구사항 — SW V-model(SRS→…→SITS) 위 시스템·인터페이스 레벨 추적</span>
              </div>
            );
          })()}
        </div>
      )}

      {/* V-model 수평쌍 완성도 요약 — 상단 상시 노출(전체 매트릭스 모드만; local은 밴드 미채움).
          통합/시스템 시험 미완이 covered 녹색에 가려지지 않게 한눈 판정으로 표면화. */}
      {gapStats.pairSupported && rows.length > 0 ? (
        <VModelPairSummary pg={gapStats.pairGaps} />
      ) : null}

      {/* 추적성 공백 (양방향) — viewMode 무관 상시 노출. 정방향 설계 단절 + 역방향 미명세 시험.
          deep-analyze: 공백이 covered 녹색·토글 뒤에 묻혀 감사에서 누락되는 문제 해소. */}
      {gapStats.hasAny ? (
        <div style={{ marginBottom: 12, border: `1px solid ${COVERAGE_COLORS.partial.border}`, borderLeft: `4px solid ${COVERAGE_COLORS.partial.border}`, borderRadius: 8, padding: '10px 14px', background: COVERAGE_COLORS.partial.bg + '40' }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6, color: COVERAGE_COLORS.partial.fg }}>
            ⚠ 추적성 공백 (양방향 — 매핑 존재만으로 가려지지 않게 상시 표시)
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 12 }}>
            <GapBadge label="SDS有·UDS無 (설계 단절, HSIS 실현 제외)" value={gapStats.sdsNoUds} tone={gapStats.sdsNoUdsGenuine ? 'warn' : 'ok'}
              sub={gapStats.sdsNoUds ? `진짜 ${gapStats.sdsNoUdsGenuine}${gapStats.sdsNoUdsAlt ? ` · 비기능 ${gapStats.sdsNoUdsAlt}` : ''}` : ''}
              title="SRS→SDS는 추적됐으나 SDS→UDS(단위설계)가 끊긴 행. 인터페이스 요구(HSIS 신호로 실현, SwEI 등)는 UDS 없음이 정상이므로 제외. '진짜'=기능요구 설계단절(보강 대상), '비기능'=SwNTR 등 시험으로 직접 검증돼 UDS 불요(정상)." />
            <GapBadge label="UDS함수 단위시험 미연결" value={gapStats.udsUntestedFns} tone={gapStats.udsUntestedFns ? 'warn' : 'ok'}
              title={`SUTS 단위시험이 안 붙은 (요구사항×UDS함수) 쌍 — 여러 요구사항이 공유하는 함수는 요구사항마다 합산(중복 포함). 분모 ${gapStats.udsFnTotal}도 동일 기준`} />
            <GapBadge label="orphan SUTS (시험有 설계無)" value={gapStats.orphanSuts} tone={gapStats.orphanSuts ? 'warn' : 'ok'}
              title="어느 UDS 함수에도 매핑되지 않는 SUTS 단위시험(역방향 공백) — (요구사항×시험) 쌍 기준, 공유 시험은 중복 합산" />
            {unmappedSupported ? (
              <GapBadge label="SRS 미추적 시험 (역방향)" value={gapStats.unmappedTotal} tone={gapStats.unmappedTotal ? 'warn' : 'ok'}
                title="시험은 됐으나 이 SRS 요구사항에 안 닿는 VectorCAST 함수(종, 중복 제거)"
                sub={gapStats.unmappedSuts ? `단위시험됨 ${gapStats.unmappedSuts}` : ''} />
            ) : (
              <span title="로컬 파일모드는 VectorCAST 역방향 추적(미추적 시험)을 계산하지 않습니다 — Jenkins 경로에서 확인하세요"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', borderRadius: 16, background: '#f3f4f6', border: '1px solid #e5e7eb', whiteSpace: 'nowrap', color: '#9ca3af' }}>
                SRS 미추적 시험 (역방향) <span style={{ fontWeight: 700 }}>미지원</span>
              </span>
            )}
          </div>
          {gapStats.pairHasAny ? (
            <div style={{ marginTop: 10, paddingTop: 8, borderTop: `1px dashed ${COVERAGE_COLORS.partial.border}` }}>
              <div style={{ fontSize: 12, fontWeight: 700, marginBottom: 6, color: COVERAGE_COLORS.partial.fg }}>
                V-model 수평쌍 공백 — 설계(좌) 있으나 대응 시험(우) 없음 (covered 녹색에 가려지는 쌍 불일치)
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 12 }}>
                <GapBadge label="SDS→SITS (SW통합시험)" value={gapStats.pairGaps.sdsNoSits} tone={gapStats.pairGaps.sdsNoSitsGenuine ? 'warn' : 'ok'}
                  sub={gapStats.pairGaps.sdsNoSits ? `진짜 ${gapStats.pairGaps.sdsNoSitsGenuine}${gapStats.pairGaps.sdsNoSitsAlt ? ` · 대체검증 ${gapStats.pairGaps.sdsNoSitsAlt}` : ''}` : ''}
                  title="SW 아키텍처(SDS) 설계는 있으나 대응 SW 통합시험(SITS)이 없는 요구사항. '진짜'=기능요구·상위검증도 없음(통합시험 보강 또는 정당화 필요), '대체검증'=비기능(SyTS/STS)·인터페이스(HSIS/SyITS)로 검증돼 SITS 구조적 불요." />
                <GapBadge label="UDS→SUTS (SW단위시험)" value={gapStats.pairGaps.udsNoSuts} tone={gapStats.pairGaps.udsNoSuts ? 'warn' : 'ok'}
                  title="단위 상세설계(UDS) 함수는 있으나 대응하는 SW 단위시험(SUTS)이 없는 요구사항 수" />
                <GapBadge label="Source→VectorCAST" value={gapStats.pairGaps.srcNoVc} tone={gapStats.pairGaps.srcNoVc ? 'warn' : 'ok'}
                  title="소스(UDS 함수)는 있으나 VectorCAST 실행 결과가 없는 요구사항 수" />
                <GapBadge label="HSIS→SyITS (시스템통합)" value={gapStats.pairGaps.hsisNoSyits} tone={gapStats.pairGaps.hsisNoSyits ? 'warn' : 'ok'}
                  title="HW-SW 인터페이스(HSIS)는 있으나 대응하는 시스템 통합시험(SyITS)이 없는 요구사항 수 — 두 밴드가 같은 요구를 공유해야 성립" />
                <GapBadge label="SyRS→SyTS (시스템시험)" value={gapStats.pairGaps.syrsNoSyts} tone={gapStats.pairGaps.syrsNoSyts ? 'warn' : 'ok'}
                  title="상위 시스템요구(SyRS)는 연결됐으나 대응하는 시스템 시험(SyTS)이 없는 요구사항 수" />
              </div>
            </div>
          ) : null}
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
            정방향(요구사항→설계→시험)·역방향(시험→요구사항) 공백. ISO 26262 양방향 추적성 신호 — 0이 아니면 보강 검토. 역방향 상세는 트리 뷰 'SRS 미추적 시험'.
            <br />상단 행은 SW 레벨(SDS→UDS 설계 단절·VectorCAST 함수 역추적) 공백, 'V-model 수평쌍 공백' 행은 각 설계 밴드↔대응 시험 밴드(시스템 레벨 HSIS→SyITS·SyRS→SyTS 포함)가 같은 요구사항에서 짝을 이루는지의 공백입니다.
          </div>
        </div>
      ) : null}

      {/* Coverage bar */}
      {coverage && (
        <div style={{ marginBottom: 12 }}>
          <CoverageBar covered={coverage.covered} partial={coverage.partial} total={coverage.total}
            onFilter={(status) => { setStatusFilter(status === 'all' ? 'all' : status); setCurrentPage(0); }} />
        </div>
      )}

      {/* 추적성 요약 상세 — 상태 총계 카드 · ASIL 분포/커버리지 · 밴드별 추적 현황 (CoverageBar 아래 상시 노출) */}
      {coverage && extraSummary && (
        <TraceExtraSummary coverage={coverage} extra={extraSummary}
          onFilter={(k) => { setStatusFilter(k === 'all' ? 'all' : k); setCurrentPage(0); }} />
      )}

      {/* Data sources */}
      {summary && coverage && (
        <details style={{ marginBottom: 12 }}>
          <summary className="text-sm" style={{ cursor: 'pointer', fontWeight: 600 }}>데이터 소스 상세</summary>
          {(() => {
            const total = coverage.total || 1;
            const traceRows = [
              { label: 'T1: SRS \u2192 SDS', type: '\uC124\uACC4', count: summary.mapped_sds_count, desc: 'SDS SwCom \uB9E4\uD551' },
              { label: 'T2: SDS \u2192 UDS', type: '\uC0C1\uC138\uC124\uACC4', count: summary.mapped_source_count ?? coverage.covered, desc: 'UDS \uD568\uC218 \uB9E4\uD551' },
              { label: 'T3: SRS \u2192 STS', type: '\uC9C1\uC811', count: summary.mapped_sts_count, direct: summary.mapped_sts_direct, desc: 'SW \uD14C\uC2A4\uD2B8' },
              { label: 'T4: UDS \u2192 SUTS', type: '\uC9C1\uC811+\uACBD\uC720', count: summary.mapped_suts_count, direct: summary.mapped_suts_direct, indirect: summary.mapped_suts_indirect, desc: '\uB2E8\uC704 \uD14C\uC2A4\uD2B8' },
              { label: 'T5: SDS \u2192 SITS', type: '\uC9C1\uC811+\uACBD\uC720', count: summary.mapped_sits_count, direct: summary.mapped_sits_direct, indirect: summary.mapped_sits_indirect, desc: '\uD1B5\uD569 \uD14C\uC2A4\uD2B8' },
              { label: '\uC804\uCCB4 \uAC80\uC99D', type: '\uD1B5\uD569', count: summary.mapped_test_count ?? (coverage.covered + coverage.partial), desc: 'STS+SUTS+SITS+SyTS+SyITS+VectorCAST' },
            ];
            const statusDot = (pct) => {
              const color = pct > 70 ? '#16a34a' : pct >= 30 ? '#d97706' : '#dc2626';
              return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: color, marginRight: 4 }} />;
            };
            return (
              <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse', marginTop: 8 }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)', background: 'var(--bg)' }}>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>{'\uCD94\uC801 \uAD00\uACC4'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uB9E4\uD551 \uC720\uD615'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uCEE4\uBC84\uB41C \uC694\uAD6C\uC0AC\uD56D'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uBE44\uC728'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uC0C1\uD0DC'}</th>
                  </tr>
                </thead>
                <tbody>
                  {traceRows.map((tr, i) => {
                    const cnt = tr.count ?? 0;
                    const pct = Math.round((cnt / total) * 100);
                    const typeDetail = tr.indirect != null
                      ? `${tr.type} (${tr.direct ?? 0}\uC9C1\uC811 + ${tr.indirect ?? 0}\uACBD\uC720)`
                      : tr.direct != null ? `${tr.type} (${tr.direct}\uC9C1\uC811)` : tr.type;
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border)', background: i === traceRows.length - 1 ? 'var(--bg)' : undefined }}>
                        <td style={{ padding: '5px 8px', fontWeight: i === traceRows.length - 1 ? 700 : 400 }}>{tr.label}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center', fontSize: 10 }}>{typeDetail}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center', fontWeight: 600 }}>{cnt} / {total}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center', fontWeight: 600 }}>{pct}%</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center' }}>{statusDot(pct)}{pct > 70 ? 'Good' : pct >= 30 ? 'Warn' : 'Low'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            );
          })()}
          {/* Source breakdown */}
          {summary?.source_stats && typeof summary.source_stats === 'object' && Object.keys(summary.source_stats).length > 0 && (
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              {Object.entries(summary.source_stats).map(([src, cnt]) => (
                <div key={src} style={{ padding: '4px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
                  background: (SOURCE_COLORS[src] || '#6b7280') + '18', color: SOURCE_COLORS[src] || '#6b7280',
                  border: `1px solid ${SOURCE_COLORS[src] || '#6b7280'}40` }}>
                  {SOURCE_ICONS[src] || src} {src}: {cnt}건
                </div>
              ))}
            </div>
          )}
          {dataSources.length > 0 && (
            <div className="text-muted text-sm" style={{ marginTop: 6 }}>
              수집: {dataSources.join(' | ')}
            </div>
          )}
        </details>
      )}

      {/* Uncovered drill-down — shows the first N missing requirements with
         a reason. Clicking a row pins the matrix filter/search to that ID so
         the user lands on it without manual scrolling. */}
      <UncoveredTopList rows={rows} onPick={handlePickUncovered} />

      {/* Search and filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          placeholder="요구사항 ID, 함수, 파일 검색..."
          value={searchTerm}
          onChange={e => { setSearchTerm(e.target.value); setCurrentPage(0); }}
          style={{
            flex: 1, minWidth: 160, padding: '6px 10px', fontSize: 13,
            border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)',
            color: 'var(--fg)',
          }}
        />
        <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setCurrentPage(0); }}
          style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
          <option value="all">전체 상태</option>
          <option value="covered">Covered</option>
          <option value="partial">Partial</option>
          <option value="uncovered">Uncovered</option>
        </select>
        {availableSources.length > 1 && (
          <select value={sourceFilter} onChange={e => { setSourceFilter(e.target.value); setCurrentPage(0); }}
            style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
            <option value="all">전체 소스</option>
            {availableSources.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        {reqTypes.length > 1 && (
          <select value={reqTypeFilter} onChange={e => { setReqTypeFilter(e.target.value); setCurrentPage(0); }}
            style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
            <option value="all">전체 타입</option>
            {reqTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <select value={testResultFilter} onChange={e => { setTestResultFilter(e.target.value); setCurrentPage(0); }}
          style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
          <option value="all">테스트 결과</option>
          <option value="pass">Pass 있음</option>
          <option value="fail">Fail 있음</option>
          <option value="no_test">테스트 없음</option>
        </select>
        {/* 보기 방식 토글: 표(기존) | 트리(신규 ID 기준 추적성 트리) */}
        <div role="group" aria-label="보기 방식" style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          <button type="button" onClick={() => setViewMode('table')} aria-pressed={viewMode === 'table'} title="표 보기"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', cursor: 'pointer',
              background: viewMode === 'table' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'table' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'table' ? 700 : 400 }}>
            표
          </button>
          <button type="button" onClick={() => setViewMode('tree')} aria-pressed={viewMode === 'tree'} title="ID 기준 추적성 트리 보기"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'tree' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'tree' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'tree' ? 700 : 400 }}>
            트리
          </button>
          <button type="button" onClick={() => setViewMode('matrix')} aria-pressed={viewMode === 'matrix'} title="hiMA식 교차 매트릭스 (요구사항×SDS, O/공백, 0추적 강조)"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'matrix' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'matrix' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'matrix' ? 700 : 400 }}>
            매트릭스
          </button>
          <button type="button" onClick={() => setViewMode('mosaic')} aria-pressed={viewMode === 'mosaic'} title="모자이크 — 요구사항×밴드 추적 히트맵 (hiMA TrMosaicReport 대응 · 색=밴드, 진하기=연결 수, 빨강=VectorCAST FAIL)"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'mosaic' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'mosaic' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'mosaic' ? 700 : 400 }}>
            모자이크
          </button>
          <button type="button" onClick={() => { setCallTreeSeed(''); setViewMode('calltree'); }} aria-pressed={viewMode === 'calltree'} title="함수 호출 트리 (tree-sitter 정밀 분석 · ASIL 강조) — 또는 표 행 펼쳐 함수의 '콜트리' 클릭"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'calltree' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'calltree' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'calltree' ? 700 : 400 }}>
            콜트리
          </button>
          <button type="button" onClick={() => { setReqGraphSeed(''); setViewMode('graph'); }} aria-pressed={viewMode === 'graph'} title="요구사항 1개의 하위 추적 그래프 — SW: SDS→UDS→STS/SUTS/SITS · 시스템: HSIS·SyTS·SyITS · 실행: VectorCAST (ASIL 강조 · UDS↔SUTS 매핑)"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'graph' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'graph' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'graph' ? 700 : 400 }}>
            그래프
          </button>
          <button type="button" onClick={() => { setFuncGraphSeed(''); setViewMode('funcgraph'); }} aria-pressed={viewMode === 'funcgraph'} title="함수 1개의 V-model 추적 그래프 — 함수→구현 요구사항/설계 + 그 함수의 단위시험(SUTS)·VectorCAST 실행결과 — 또는 표 행 펼쳐 함수명 클릭"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'funcgraph' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'funcgraph' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'funcgraph' ? 700 : 400 }}>
            함수그래프
          </button>
        </div>
        {/* 트리 전용: SRS 미추적 시험(역방향 공백) 별도 루트 표시 토글 — 데이터 있을 때만 노출 */}
        {viewMode === 'tree' && unmappedVcast.length > 0 && (
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, cursor: 'pointer', color: 'var(--fg)', userSelect: 'none' }}
            title="시험은 됐지만 이 SRS 요구사항에 추적되지 않는 VectorCAST 함수를 트리 하단에 별도 루트로 표시 (역방향 추적성 공백)">
            <input type="checkbox" checked={includeUnmapped} onChange={e => setIncludeUnmapped(e.target.checked)} style={{ cursor: 'pointer' }} />
            SRS 미추적 시험 포함 ({unmappedVcast.length})
          </label>
        )}
        <button className="btn-sm" onClick={exportCSV} title="CSV 내보내기" style={{ fontSize: 11 }}>
          CSV
        </button>
        <span className="text-muted text-sm">
          {filtered.length}건{filtered.length !== rows.length ? ` / ${rows.length}건` : ''}
        </span>
      </div>

      {/* Matrix table (표 보기 — 기존 그대로) */}
      {viewMode === 'table' && (
      <div style={{ overflowX: 'auto' }}>
      <table className="impact-table" style={{ minWidth: 950 }}>
        <thead>
          <tr>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 100, cursor: 'pointer' }} onClick={() => toggleSort('req_id')}>
              요구사항 ID{sortIcon('req_id')}
            </th>
            <th colSpan={3} style={{ textAlign: 'center', background: '#eff6ff', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => toggleSort('func_count')}>
              설계 (T1,T2 + 인터페이스){sortIcon('func_count')}
            </th>
            <th colSpan={6} style={{ textAlign: 'center', background: '#f0fdf4', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => toggleSort('test_count')}>
              검증 (T3,T4,T5 + 시스템){sortIcon('test_count')}
            </th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 50, textAlign: 'center' }}>P/F</th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 55, textAlign: 'center' }}>신뢰도</th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 75, cursor: 'pointer' }} onClick={() => toggleSort('status')}>
              상태{sortIcon('status')}
            </th>
          </tr>
          <tr>
            <th style={{ fontSize: 10, background: '#eff6ff' }} title="T1: SRS→SDS">SDS 컴포넌트</th>
            <th style={{ fontSize: 10, background: '#eff6ff' }} title="인터페이스: SRS→HSIS (HW-SW 인터페이스 신호)">HSIS 신호</th>
            <th style={{ fontSize: 10, background: '#eff6ff' }} title="T2: SDS→UDS">UDS 함수</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T3: SRS→STS">STS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T4: UDS→SUTS">SUTS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T5: SDS→SITS">SITS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="시스템 시험(SyTS)">SyTS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="시스템 통합시험(SyITS)">SyITS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }}>VectorCAST</th>
          </tr>
        </thead>
        <tbody>
          {displayedRows.map((r, idx) => {
            const reqId = _rowReqId(r) || `row-${idx}`;
            const rgId = _reqGraphId(r);   // 추적 그래프 시드용 순수 요구사항 ID(익명 행이면 '' → 그래프 버튼 숨김)
            const status = deriveStatus(r);
            const colors = COVERAGE_COLORS[status] || {};
            const sdsComps = r.sds_components ?? [];
            const hsisSigs = r.hsis_signals ?? [];
            const srcFuncs = r.source_ids ?? [];
            const rawTests = Array.isArray(r.tests) ? r.tests : [];
            // ISO 26262 추적 관계별 분리: T3(STS), T4(SUTS), T5(SITS)
            const stsOnlyTests = Array.isArray(r.sts_tests) ? r.sts_tests : rawTests.filter(t => t.source === 'STS');
            const sutsOnlyTests = Array.isArray(r.suts_tests) ? r.suts_tests : rawTests.filter(t => t.source === 'SUTS');
            const sitsTests = Array.isArray(r.sits_tests) ? r.sits_tests : rawTests.filter(t => t.source === 'SITS');
            const vcastTests = rawTests.filter(t => t.source === 'VectorCAST');
            const sytsTests = Array.isArray(r.syts_tests) ? r.syts_tests : rawTests.filter(t => t.source === 'SyTS');
            const syitsTests = Array.isArray(r.syits_tests) ? r.syits_tests : rawTests.filter(t => t.source === 'SyITS');
            const otherTests = rawTests.filter(t => !['STS','SUTS','SITS','SyTS','SyITS','VectorCAST'].includes(t.source));
            const stsCount = stsOnlyTests.length;
            const sutsCount = sutsOnlyTests.length;
            const sitsCount = sitsTests.length;
            const sytsCount = sytsTests.length;
            const syitsCount = syitsTests.length;
            const vcastCount = vcastTests.length + otherTests.length;
            const passCount = r.pass_count ?? 0;
            const failCount = r.fail_count ?? 0;
            const hasExact = stsCount > 0 || sutsCount > 0 || sitsCount > 0;
            const confidence = r.confidence ?? (hasExact && vcastCount === 0 ? 'exact' : vcastCount > 0 && !hasExact ? 'fuzzy' : hasExact ? 'mixed' : null);
            const isExpanded = expandedReqId === reqId;

            return (
              <React.Fragment key={reqId}>
                <tr style={{ background: colors.bg, cursor: 'pointer' }}
                    onClick={() => setExpandedReqId(isExpanded ? null : reqId)}>
                  <td style={{ fontSize: 11, fontWeight: 600 }}>
                    <span style={{ fontFamily: 'monospace' }}>{isExpanded ? '\u25BC' : '\u25B6'} {reqId}</span>
                    {r.requirement_name && <span style={{ fontWeight: 400, color: 'var(--text-muted)', marginLeft: 6 }} title={r.requirement_name}>{r.requirement_name}</span>}
                  </td>
                  <td style={{ fontSize: 10, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={sdsComps.join(', ')}>
                    {sdsComps.length > 0
                      ? <><span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 8, background: '#dbeafe', color: '#1e40af', fontWeight: 600 }}>{sdsComps.length}</span> {sdsComps.slice(0, 2).join(', ')}{sdsComps.length > 2 ? '...' : ''}</>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={hsisSigs.join(', ')}>
                    {hsisSigs.length > 0
                      ? <><span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 8, background: '#cffafe', color: _STAGE_COLORS.HSIS, fontWeight: 600 }}>{hsisSigs.length}</span> {hsisSigs.slice(0, 2).join(', ')}{hsisSigs.length > 2 ? '...' : ''}</>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={srcFuncs.join(', ')}>
                    {srcFuncs.length > 0
                      ? <><span className="pill pill-info" style={{ fontSize: 9 }}>{srcFuncs.length}</span> {srcFuncs.slice(0, 2).join(', ')}{srcFuncs.length > 2 ? '...' : ''}</>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="T3: SRS→STS">
                    {stsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.STS + '20', color: SOURCE_COLORS.STS, fontWeight: 600 }}>{stsCount} TC</span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="T4: UDS→SUTS">
                    {sutsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.SUTS + '20', color: SOURCE_COLORS.SUTS, fontWeight: 600 }} title={`\uC9C1\uC811: ${r.suts_direct || 0}, \uACBD\uC720: ${r.suts_indirect || 0}`}>
                          {sutsCount} TC
                          {r.suts_indirect > 0 && <span style={{ fontSize: 8, color: 'var(--text-muted)' }}> ({r.suts_direct || 0}+{r.suts_indirect || 0})</span>}
                        </span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="T5: SDS→SITS">
                    {sitsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.SITS + '20', color: SOURCE_COLORS.SITS, fontWeight: 600 }} title={`\uC9C1\uC811: ${r.sits_direct || 0}, \uACBD\uC720: ${r.sits_indirect || 0}`}>
                          {sitsCount} TC
                          {r.sits_indirect > 0 && <span style={{ fontSize: 8, color: 'var(--text-muted)' }}> ({r.sits_direct || 0}+{r.sits_indirect || 0})</span>}
                        </span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="시스템 시험(SyTS)">
                    {sytsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: _STAGE_COLORS.SyTS + '20', color: _STAGE_COLORS.SyTS, fontWeight: 600 }}>{sytsCount} TC</span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="시스템 통합시험(SyITS)">
                    {syitsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: _STAGE_COLORS.SyITS + '20', color: _STAGE_COLORS.SyITS, fontWeight: 600 }}>{syitsCount} TC</span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }}>
                    {vcastCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.VectorCAST + '20', color: SOURCE_COLORS.VectorCAST, fontWeight: 600 }}>{vcastCount}</span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }}>
                    {(passCount > 0 || failCount > 0) ? (
                      <span style={{ fontSize: 9 }}>
                        {passCount > 0 && <span style={{ color: '#16a34a', fontWeight: 600 }}>{passCount}P</span>}
                        {passCount > 0 && failCount > 0 && '/'}
                        {failCount > 0 && <span style={{ color: '#dc2626', fontWeight: 600 }}>{failCount}F</span>}
                      </span>
                    ) : <span className="text-muted">-</span>}
                  </td>
                  <td style={{ fontSize: 9, textAlign: 'center' }}>
                    {confidence && (
                      <span style={{ padding: '1px 5px', borderRadius: 6, fontWeight: 600,
                        color: CONFIDENCE_COLORS[confidence] || '#6b7280',
                        background: (CONFIDENCE_COLORS[confidence] || '#6b7280') + '18' }}>
                        {CONFIDENCE_LABELS[confidence] || confidence}
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <StatusBadge tone={coverageTone(status)}>{status}</StatusBadge>
                  </td>
                </tr>

                {/* Expanded detail row — drilldown */}
                {isExpanded && (
                  <tr style={{ background: '#f8fafc' }}>
                    {/* 13컬럼: ID + 설계(SDS/HSIS/UDS)3 + 검증(STS/SUTS/SITS/SyTS/SyITS/VC)6 + P/F + 신뢰도 + 상태 */}
                    <td colSpan={13} style={{ padding: '10px 16px' }}>
                      {/* 요구사항 단위 추적 시각화 툴바 — 확장 즉시 보이도록 최상단 배치(함수 단위 함수그래프/콜트리는 UDS 함수 목록에 별도) */}
                      {rgId && (() => {
                        const rgOpen = inlineView?.type === 'reqgraph' && inlineView.reqId === reqId && inlineView.key === rgId;
                        return (
                          <div style={{ marginBottom: 10, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
                            <span style={{ fontSize: 11, fontWeight: 600, color: '#475569' }}>이 요구사항 추적 시각화</span>
                            <button type="button" onClick={(e) => { e.stopPropagation(); toggleInline('reqgraph', rgId, reqId); }}
                              aria-pressed={rgOpen}
                              title="이 요구사항의 하위 추적 그래프(SDS→UDS→시험→VectorCAST)를 이 자리에서 바로 펼침 (다시 누르면 닫힘)"
                              style={{ fontSize: 10, padding: '2px 9px', border: `1px solid ${rgOpen ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 4, background: rgOpen ? 'var(--accent)' : 'var(--bg)', cursor: 'pointer', color: rgOpen ? '#fff' : 'var(--fg)', fontWeight: 600 }}>추적 그래프 {rgOpen ? '▴' : '▾'}</button>
                          </div>
                        );
                      })()}
                      {/* 상위(SyRS) provenance — 표 컬럼엔 없는 상위 시스템요구 추적(SR→SyRS→SwRS). 매트릭스 뷰엔 SyRS↑ 컬럼 별도 존재. */}
                      {Array.isArray(r.syrs_parents) && r.syrs_parents.length > 0 && (
                        <div style={{ marginBottom: 10, paddingBottom: 8, borderBottom: '1px solid #e5e7eb', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, fontSize: 11 }}>
                          <span style={{ fontWeight: 600, color: '#475569' }}>상위 시스템요구 (SyRS↑) {r.syrs_parents.length}</span>
                          {r.syrs_parents.map((p, pi) => (
                            <span key={pi} title="이 요구가 유도된 상위 시스템 요구 — SR→SyRS→SwRS 체인 (상위 추적, 커버리지 분모 제외)"
                              style={{ fontFamily: 'monospace', fontSize: 10, padding: '1px 6px', borderRadius: 8, background: '#47556918', color: '#475569', border: '1px solid #47556940' }}>{String(p)}</span>
                          ))}
                        </div>
                      )}
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 12 }}>
                        {/* SDS components */}
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 11, marginBottom: 6 }}>SDS 컴포넌트 ({sdsComps.length})</div>
                          {sdsComps.length > 0 ? (
                            <div style={{ maxHeight: 150, overflowY: 'auto', fontSize: 11 }}>
                              {sdsComps.map((c, ci) => (
                                <div key={ci} style={{ padding: '2px 0', fontFamily: 'monospace', borderBottom: '1px solid #e5e7eb' }}>{c}</div>
                              ))}
                            </div>
                          ) : <div className="text-muted text-sm">매핑된 컴포넌트 없음</div>}
                        </div>
                        {/* UDS Functions list */}
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 11, marginBottom: 6 }}>UDS 함수 ({srcFuncs.length})</div>
                          {srcFuncs.length > 0 ? (
                            <div style={{ maxHeight: 150, overflowY: 'auto', fontSize: 11 }}>
                              {srcFuncs.map((fn, fi) => {
                                const bareFn = String(fn).split(/[\s(]/)[0].trim();
                                const ctOpen = inlineView?.type === 'calltree' && inlineView.reqId === reqId && inlineView.key === bareFn;
                                const fgOpen = inlineView?.type === 'funcgraph' && inlineView.reqId === reqId && inlineView.key === fn;
                                return (
                                <div key={fi} style={{ padding: '2px 0', display: 'flex', alignItems: 'center', gap: 6, borderBottom: '1px solid #e5e7eb' }}>
                                  <code title={fn} style={{ flex: 1, minWidth: 0, fontFamily: 'monospace', fontSize: 11, color: _STAGE_COLORS.UDS, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{fn}</code>
                                  <button type="button" onClick={(e) => { e.stopPropagation(); toggleInline('funcgraph', fn, reqId); }}
                                    aria-pressed={fgOpen}
                                    title="이 함수의 V-model 추적 그래프(함수그래프)를 이 자리에서 바로 펼침 — 함수→요구사항/설계/단위시험/VectorCAST (다시 누르면 닫힘)"
                                    style={{ flexShrink: 0, fontSize: 9, padding: '1px 5px', border: `1px solid ${fgOpen ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 4, background: fgOpen ? 'var(--accent)' : 'var(--bg)', cursor: 'pointer', color: fgOpen ? '#fff' : 'var(--fg)', fontWeight: 600 }}>함수그래프 {fgOpen ? '▴' : '▾'}</button>
                                  <button type="button" onClick={(e) => { e.stopPropagation(); toggleInline('calltree', bareFn, reqId); }}
                                    aria-pressed={ctOpen}
                                    title="이 함수의 호출 트리(콜트리)를 이 자리에서 바로 펼침 — 호출/역호출 방향 전환 가능 (다시 누르면 닫힘)"
                                    style={{ flexShrink: 0, fontSize: 9, padding: '1px 5px', border: `1px solid ${ctOpen ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 4, background: ctOpen ? 'var(--accent)' : 'var(--bg)', cursor: 'pointer', color: ctOpen ? '#fff' : 'var(--fg)', fontWeight: 600 }}>콜트리 {ctOpen ? '▴' : '▾'}</button>
                                </div>
                                );
                              })}
                            </div>
                          ) : <div className="text-muted text-sm">매핑된 함수 없음</div>}
                        </div>
                        {/* Tests list */}
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 11, marginBottom: 6 }}>테스트 ({rawTests.length})</div>
                          {rawTests.length > 0 ? (
                            <div style={{ maxHeight: 150, overflowY: 'auto', fontSize: 11 }}>
                              <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
                                <thead>
                                  <tr style={{ background: '#e5e7eb' }}>
                                    <th style={{ padding: '3px 6px', textAlign: 'left' }}>TC</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>결과</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 55 }}>소스</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>추적</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>신뢰</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {rawTests.map((t, ti) => {
                                    const isPass = (t.result || '').toLowerCase().match(/^(pass|passed|true|1)$/);
                                    const isFail = (t.result || '').toLowerCase().match(/^(fail|failed|false|0)$/);
                                    return (
                                      <tr key={ti} style={{ borderBottom: '1px solid #e5e7eb' }}>
                                        <td style={{ padding: '3px 6px', fontFamily: 'monospace' }}>{t.testcase || '-'}</td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center', fontWeight: 600,
                                          color: isPass ? '#16a34a' : isFail ? '#dc2626' : '#6b7280' }}>
                                          {t.result || '-'}
                                        </td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center' }}>
                                          <span style={{ fontSize: 9, padding: '0 4px', borderRadius: 4,
                                            background: (SOURCE_COLORS[t.source] || '#6b7280') + '18',
                                            color: SOURCE_COLORS[t.source] || '#6b7280', fontWeight: 600 }}>
                                            {t.source || '-'}
                                          </span>
                                        </td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center', fontSize: 9,
                                          color: t.trace_type === 'direct' ? '#16a34a' : t.trace_type === 'indirect' ? '#d97706' : '#6b7280' }}>
                                          {t.trace_type === 'direct' ? '\uC9C1\uC811' : t.trace_type === 'indirect' ? '\uACBD\uC720' : '-'}
                                        </td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center', fontSize: 9,
                                          color: CONFIDENCE_COLORS[t.confidence] || '#6b7280' }}>
                                          {t.confidence || '-'}
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          ) : <div className="text-muted text-sm">매핑된 테스트 없음</div>}
                        </div>
                      </div>
                      {/* V-Model trace path summary */}
                      <div style={{ marginTop: 10, padding: 8, background: 'var(--bg)', borderRadius: 6, borderLeft: '3px solid var(--accent)' }}>
                        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 4 }}>V-Model {'\uCD94\uC801 \uACBD\uB85C'}</div>
                        <div style={{ fontSize: 10 }}>
                          T1: SDS → {sdsComps.length}{'\uAC1C \uCEF4\uD3EC\uB10C\uD2B8'} | T2: UDS → {srcFuncs.length}{'\uAC1C \uD568\uC218'} | T3: STS → {stsCount} TC ({'\uC9C1\uC811'}) | T4: SUTS → {r.suts_direct || 0} {'\uC9C1\uC811'} + {r.suts_indirect || 0} {'\uACBD\uC720'} | T5: SITS → {r.sits_direct || 0} {'\uC9C1\uC811'} + {r.sits_indirect || 0} {'\uACBD\uC720'}
                        </div>
                      </div>
                      {/* 인라인 뷰 — 표 행에서 함수그래프/콜트리/추적그래프 클릭 시 탭 전환 없이 이 자리에서 표시 */}
                      {inlineView?.type === 'calltree' && inlineView.reqId === reqId && srcFuncs.some(f => String(f).split(/[\s(]/)[0].trim() === inlineView.key) ? (
                        <InlineCallTree key={`ct:${inlineView.key}`} fn={inlineView.key} job={job} cacheRoot={cacheRoot} buildSelector={buildSelector}
                          sourceRoot={sourceRoot}
                          onOpenFull={() => gotoFuncView(inlineView.key, 'calltree')}
                          onClose={() => setInlineView(null)} />
                      ) : null}
                      {inlineView?.type === 'funcgraph' && inlineView.reqId === reqId && srcFuncs.some(f => f === inlineView.key) ? (
                        <InlineGraphFrame title="함수그래프" badge={inlineView.key}
                          onOpenFull={() => gotoFuncView(inlineView.key, 'funcgraph')}
                          onClose={() => setInlineView(null)}>
                          <TraceFuncGraphView key={`fg:${inlineView.key}`} rows={rows} focusFunctions={focusFunctions} initialFn={inlineView.key} embedded />
                        </InlineGraphFrame>
                      ) : null}
                      {inlineView?.type === 'reqgraph' && inlineView.reqId === reqId && rgId && inlineView.key === rgId ? (
                        <InlineGraphFrame title="추적 그래프" badge={rgId}
                          onOpenFull={() => { setReqGraphSeed(rgId); setViewMode('graph'); }}
                          onClose={() => setInlineView(null)}>
                          <TraceReqGraphView key={`rg:${rgId}`} rows={rows} focusFunctions={focusFunctions} linkTable={inner?.link_table} initialReqId={rgId} embedded />
                        </InlineGraphFrame>
                      ) : null}
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
      </div>
      )}

      {/* 트리 보기 (ID 기준 추적성 트리). 트리는 추적성 '전체 조망'이 목적이므로 페이지 슬라이스가
          아닌 filtered 전체를 넘긴다(접힘 기본이라 DOM 비용 낮음). 미추적 루트도 1회만 렌더됨
          (페이지별 중복 제거 — deep-analyze). baseIndex=0: nodeId는 filtered 절대 인덱스 기준. */}
      {viewMode === 'tree' && (
        <TraceTree rows={filtered} baseIndex={0} expanded={expandedTreeNodes} onToggle={toggleTreeNode}
          unmapped={includeUnmapped ? unmappedVcast : null} />
      )}

      {/* 매트릭스 보기 (신규 — hiMA식 교차표. filtered 반영, link_table 내보내기) */}
      {viewMode === 'matrix' && (
        <CrossMatrixView rows={filtered} linkTable={inner?.link_table} fullMatrix={inner}
          exportMeta={{ job_url: matrix?.job_url || inner?.job_url || '' }} />
      )}

      {/* 모자이크 보기 (신규 — hiMA TrMosaicReport 대응. 요구사항×밴드 색상 히트맵, filtered 반영) */}
      {viewMode === 'mosaic' && (
        <TraceMosaicView rows={filtered} />
      )}

      {/* 콜트리 보기 (신규 — tree-sitter 정밀 함수 호출 트리. entry 기반 깊이탐색 + ASIL 강조) */}
      {viewMode === 'calltree' && (
        <CallTreeView job={job} cacheRoot={cacheRoot} buildSelector={buildSelector}
          sourceRoot={sourceRoot} seedFns={callTreeSeeds} toast={toast} initialEntry={callTreeSeed} />
      )}

      {/* 그래프 보기 (신규 — 요구사항 1개의 하위 추적 그래프. SVG 노드-엣지, filtered row로 완결.
          focusFunctions=영향도 연동 변경함수 → 그래프 안 해당 UDS/시험 노드 강조) */}
      {viewMode === 'graph' && (
        <TraceReqGraphView rows={filtered} focusFunctions={focusFunctions} linkTable={inner?.link_table} initialReqId={reqGraphSeed} />
      )}

      {/* 함수중심 그래프 (신규 — 함수 1개의 V-model 추적. root=함수, 요구사항/설계는 함수가 구현한
          요구사항 경유, 단위시험(SUTS)·VectorCAST 실행결과는 함수 직접 연결. hiMA UCOneIDTrace 함수판) */}
      {viewMode === 'funcgraph' && (
        <TraceFuncGraphView rows={rows} focusFunctions={focusFunctions} initialFn={funcGraphSeed} />
      )}

      {/* Pagination (표 모드 전용 — 트리는 filtered 전체를 한 번에 조망하므로 페이지네이션 불필요) */}
      {viewMode === 'table' && (
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="text-sm text-muted">페이지당</span>
          <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(0); }}
            style={{ padding: '3px 6px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--fg)' }}>
            {PAGE_SIZES.map(s => <option key={s} value={s}>{s}건</option>)}
          </select>
          <span className="text-sm text-muted">
            {filtered.length === 0 ? '(0건)' : `(${safePage * pageSize + 1}-${Math.min((safePage + 1) * pageSize, filtered.length)} / ${filtered.length}건)`}
          </span>
        </div>
        {totalPages > 1 && (
          <div style={{ display: 'flex', gap: 4 }}>
            <button className="btn-sm" disabled={safePage === 0} onClick={() => setCurrentPage(0)} style={{ fontSize: 11 }}>&laquo;</button>
            <button className="btn-sm" disabled={safePage === 0} onClick={() => setCurrentPage(p => p - 1)} style={{ fontSize: 11 }}>&lsaquo;</button>
            <span className="text-sm" style={{ padding: '4px 8px', fontWeight: 600 }}>
              {safePage + 1} / {totalPages}
            </span>
            <button className="btn-sm" disabled={safePage >= totalPages - 1} onClick={() => setCurrentPage(p => p + 1)} style={{ fontSize: 11 }}>&rsaquo;</button>
            <button className="btn-sm" disabled={safePage >= totalPages - 1} onClick={() => setCurrentPage(totalPages - 1)} style={{ fontSize: 11 }}>&raquo;</button>
          </div>
        )}
      </div>
      )}
    </div>
  );
}

/* ── UncoveredTopList ──────────────────────────────────────────────────
 * Surfaces the first N missing requirements (derived via deriveStatus) so
 * reviewers can act on gaps without scrolling through the full matrix.
 * Clicking an item calls onPick(reqId) — the parent wires that to the
 * existing statusFilter + searchTerm state so the matrix snaps to it. */
const TOP_N = 10;

function reasonForUncovered(r) {
  // Must use the same detectors as deriveStatus; otherwise a row that
  // deriveStatus flagged as uncovered could show "설계·테스트 없음" while
  // deriveStatus thought one side was present (or vice versa).
  const hasDesign = hasDesignData(r);
  const hasTest = hasTestData(r);
  if (!hasDesign && !hasTest) return '설계·테스트 없음';
  if (!hasDesign) return '설계 누락';
  if (!hasTest) return '테스트 누락';
  return '미커버';
}

// Pull a stable identifier from a matrix row. Returns '' when nothing
// usable is present — those rows must NOT be exposed in the drill-down,
// because the matrix search/filter has no key to seek to and the click
// would silently do nothing. Accepts numeric ids too — a backend that
// returns `id: 42` must not be silently dropped from ASIL traceability.
function _rowReqId(r) {
  const id = r?.requirement_id ?? r?.req_id ?? r?.id;
  if (id == null) return '';
  return String(id).trim();
}

export function UncoveredTopList({ rows, onPick }) {
  const uncovered = useMemo(() => {
    const out = [];
    let droppedAnonymous = 0;
    for (const r of rows || []) {
      if (deriveStatus(r) !== 'uncovered') continue;
      // Skip rows without a stable requirement identifier — clicking such an
      // entry could not steer the matrix to it, so surfacing it would just
      // produce dead clicks.
      if (!_rowReqId(r)) {
        droppedAnonymous++;
        continue;
      }
      out.push(r);
    }
    out._anonymousCount = droppedAnonymous;
    return out;
  }, [rows]);

  if (!uncovered.length) return null;

  const shown = uncovered.slice(0, TOP_N);
  const more = uncovered.length - shown.length;
  const anonymousNote = uncovered._anonymousCount > 0
    ? ` (식별자 없는 ${uncovered._anonymousCount}건은 매트릭스에서 직접 확인)`
    : '';

  return (
    <div
      style={{
        marginBottom: 12,
        border: `1px solid ${COVERAGE_COLORS.uncovered.border}`,
        borderRadius: 8,
        background: COVERAGE_COLORS.uncovered.bg + '30',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '8px 12px',
          background: COVERAGE_COLORS.uncovered.bg,
          borderBottom: `1px solid ${COVERAGE_COLORS.uncovered.border}`,
          fontSize: 12,
          fontWeight: 700,
          color: COVERAGE_COLORS.uncovered.fg,
          display: 'flex',
          justifyContent: 'space-between',
        }}
      >
        <span>미커버 요구사항 (Top {shown.length})</span>
        <span style={{ fontWeight: 400, fontSize: 11 }}>
          총 {uncovered.length}건{anonymousNote}
        </span>
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {shown.map((r, i) => {
          // _rowReqId is guaranteed non-empty here — anonymous rows were
          // filtered out in the `uncovered` memo above.
          const reqId = _rowReqId(r);
          const reason = reasonForUncovered(r);
          return (
            <li key={reqId}>
              <button
                type="button"
                onClick={() => onPick?.(reqId)}
                aria-label={`미커버 요구사항 ${reqId}로 이동`}
                style={{
                  width: '100%',
                  textAlign: 'left',
                  padding: '6px 12px',
                  background: 'transparent',
                  border: 'none',
                  borderBottom: i < shown.length - 1 ? '1px solid var(--border)' : 'none',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  fontSize: 12,
                }}
                onMouseEnter={e => { e.currentTarget.style.background = COVERAGE_COLORS.uncovered.bg + '60'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                <span style={{ fontFamily: 'monospace', fontWeight: 600, minWidth: 120 }}>{reqId}</span>
                <span
                  style={{
                    fontSize: 10,
                    padding: '1px 6px',
                    borderRadius: 8,
                    background: COVERAGE_COLORS.uncovered.border,
                    color: COVERAGE_COLORS.uncovered.fg,
                    fontWeight: 600,
                    whiteSpace: 'nowrap',
                  }}
                >
                  {reason}
                </span>
                <span style={{ color: 'var(--text-muted)', marginLeft: 'auto', fontSize: 11 }}>
                  매트릭스로 이동 →
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      {more > 0 && (
        <div
          style={{
            padding: '6px 12px',
            borderTop: `1px solid ${COVERAGE_COLORS.uncovered.border}`,
            fontSize: 11,
            color: 'var(--text-muted)',
            textAlign: 'center',
          }}
        >
          + {more}개 더 — 아래 매트릭스에서 Uncovered 필터로 전체 확인
        </div>
      )}
    </div>
  );
}

/* ── TraceTree — ID 기준 추적성 트리 뷰 ───────────────────────────────────
 * 기존 flat 매트릭스 표(TraceMatrix)는 그대로 두고, 같은 row 데이터를
 * SRS-ID 루트 → 문서 단계(SW: SDS/UDS/STS/SUTS/SITS · 시스템: HSIS/SyTS/SyITS · VectorCAST) 트리로 재구성한다.
 * 한 요구사항이 어느 단계까지 추적됐고 어디서 끊겼는지(빈 단계 = 회색 칩)를
 * 펼치지 않아도 한눈에 본다.
 *  - 상태 분류: deriveStatus 재사용 → 표/대시보드/백엔드 _cache_trace_summary와 lockstep.
 *  - P/F: 표(L1246-1252)와 동일 규칙. STS/SUTS/SITS·SyTS/SyITS의 result='mapped'는 '시험 통과'가
 *    아니라 '매핑 존재'이므로 중립색 유지(ISO 26262: 매핑 존재 ≠ 시험 통과).
 *  - SDS↔UDS 정확 부모-자식 엣지는 row 데이터에 없으므로(평탄 배열) 거짓 중첩 대신
 *    SRS 직속 단계 노드로 평면 배치한다. VectorCAST만 실행 P/F 보유. */

const TREE_STAGES = [
  { key: 'SDS',  label: 'SDS',  kind: 'design' },
  { key: 'HSIS', label: 'HSIS', kind: 'design' },
  { key: 'UDS',  label: 'UDS',  kind: 'design' },
  { key: 'STS',  label: 'STS',  kind: 'test' },
  { key: 'SUTS', label: 'SUTS', kind: 'test' },
  { key: 'SITS', label: 'SITS', kind: 'test' },
  { key: 'SyTS', label: 'SyTS', kind: 'test' },
  { key: 'SyITS', label: 'SyITS', kind: 'test' },
  { key: 'VectorCAST', label: 'VectorCAST', kind: 'test' },
];

// STS/SUTS/SITS·SyTS/SyITS는 'mapped' 리터럴(실 P/F 아님) → 중립. VectorCAST만 실제 결과.
function _testResultColor(result) {
  const r = (result || '').toLowerCase();
  if (/^(pass|passed|true|1)$/.test(r)) return '#16a34a';
  if (/^(fail|failed|false|0)$/.test(r)) return '#dc2626';
  return '#6b7280'; // mapped/unknown — 중립
}

// 단계별 멤버 추출 — 표(L1109-1121)의 분리 규칙과 동일.
// VectorCAST 단계는 표의 vcastCount 의미(VectorCAST + 분류 안 된 other source)와 일치시킨다.
function _stageMembers(r, stageKey) {
  if (stageKey === 'SDS') return { type: 'ids', items: Array.isArray(r.sds_components) ? r.sds_components : [] };
  if (stageKey === 'HSIS') return { type: 'ids', items: Array.isArray(r.hsis_signals) ? r.hsis_signals : [] };
  if (stageKey === 'UDS') return { type: 'ids', items: Array.isArray(r.source_ids) ? r.source_ids : [] };
  const raw = Array.isArray(r.tests) ? r.tests : [];
  if (stageKey === 'STS')  return { type: 'tests', items: Array.isArray(r.sts_tests)  ? r.sts_tests  : raw.filter(t => t.source === 'STS') };
  if (stageKey === 'SUTS') return { type: 'tests', items: Array.isArray(r.suts_tests) ? r.suts_tests : raw.filter(t => t.source === 'SUTS') };
  if (stageKey === 'SITS') return { type: 'tests', items: Array.isArray(r.sits_tests) ? r.sits_tests : raw.filter(t => t.source === 'SITS') };
  if (stageKey === 'SyTS') return { type: 'tests', items: Array.isArray(r.syts_tests) ? r.syts_tests : raw.filter(t => t.source === 'SyTS') };
  if (stageKey === 'SyITS') return { type: 'tests', items: Array.isArray(r.syits_tests) ? r.syits_tests : raw.filter(t => t.source === 'SyITS') };
  if (stageKey === 'VectorCAST') return { type: 'tests', items: raw.filter(t => t.source === 'VectorCAST' || !['STS', 'SUTS', 'SITS', 'SyTS', 'SyITS'].includes(t.source)) };
  return { type: 'ids', items: [] };
}

// 함수명 정규화 — SUTS test.unit(=함수명)을 source_ids(UDS 함수)와 매칭하기 위함.
// VectorCAST 롤업 라벨 'SwUFn_x (N TC)'의 괄호 이후도 안전하게 제거.
function _normFn(x) {
  return String(x ?? '').replace(/\s*\(.*$/, '').trim().toLowerCase();
}

// SUTS 단위시험을 test.unit(=함수명) 기준으로 묶는다. SUTS는 unit=함수명이라 UDS 함수와
// 1:1 매칭된다(실데이터 검증: UDS 2901개 중 2888개 연결). 이 맵으로 "UDS 함수 → 그 함수를
// 시험하는 단위시험(SUTS) TC" 교차문서 연결을 트리에 중첩하고, 매칭 0인 함수는 단위시험 공백으로 본다.
// SUTS 한정 이유: STS/SITS는 unit이 비어 있고 VectorCAST unit은 시험파일명(함수명 아님)이라
// 함수 매칭에 기여하지 않는다 — '단위시험'(=SUTS) 의미와 코드를 1:1로 묶고 false-nesting을 차단.
function _unitTestMap(r) {
  const m = new Map();
  for (const t of _stageMembers(r, 'SUTS').items) {
    const u = _normFn(t && t.unit);
    if (!u) continue;
    if (!m.has(u)) m.set(u, []);
    m.get(u).push(t);
  }
  return m;
}

// 시험 TC 표 — TraceTreeStage(시험 단계)와 TraceTreeFunc(함수별 중첩)가 공유.
// 'mapped'는 _testResultColor가 중립 회색 처리(ISO 26262: 매핑 존재 ≠ 시험 통과).
// 소스 열 없음(의도): 트리의 모든 시험 표는 단일 소스로 그룹화돼 들어온다 — 단계 노드는
// 헤더(STS/SUTS/SITS/SyTS/SyITS/VectorCAST)가 곧 소스이고, 함수 중첩은 _unitTestMap이 SUTS 전용이라
// 전부 SUTS다. 표 모드 drilldown은 소스 혼합이라 소스 열을 갖지만 트리는 불필요(중복 방지).
function TestTable({ tests }) {
  const list = Array.isArray(tests) ? tests : [];
  return (
    <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
      <thead>
        <tr style={{ background: '#e5e7eb' }}>
          <th style={{ padding: '3px 6px', textAlign: 'left' }}>TC</th>
          <th style={{ padding: '3px 6px', textAlign: 'center', width: 60 }}>결과</th>
          <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>추적</th>
          <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>신뢰</th>
        </tr>
      </thead>
      <tbody>
        {list.map((t, ti) => (
          <tr key={ti} style={{ borderBottom: '1px solid var(--border)' }}>
            <td style={{ padding: '3px 6px', fontFamily: 'monospace' }}>{t.testcase || t.unit || '-'}</td>
            <td style={{ padding: '3px 6px', textAlign: 'center', fontWeight: 600, color: _testResultColor(t.result) }}>{t.result || '-'}</td>
            <td style={{ padding: '3px 6px', textAlign: 'center', fontSize: 9,
              color: t.trace_type === 'direct' ? '#16a34a' : t.trace_type === 'indirect' ? '#d97706' : '#6b7280' }}>
              {t.trace_type === 'direct' ? '직접' : t.trace_type === 'indirect' ? '경유' : '-'}
            </td>
            <td style={{ padding: '3px 6px', textAlign: 'center', fontSize: 9, color: CONFIDENCE_COLORS[t.confidence] || '#6b7280' }}>
              {t.confidence || '-'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TraceTree({ rows, baseIndex = 0, expanded, onToggle, unmapped = null }) {
  const list = Array.isArray(rows) ? rows : [];
  const exp = expanded instanceof Set ? expanded : new Set();
  const unmappedList = Array.isArray(unmapped) ? unmapped : [];
  if (list.length === 0 && unmappedList.length === 0) {
    return <div className="text-muted text-sm" style={{ padding: '16px 4px' }}>표시할 요구사항이 없습니다.</div>;
  }
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
      {/* 범례 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, padding: '8px 12px', background: 'var(--bg)', borderBottom: '1px solid var(--border)', fontSize: 11, color: 'var(--text-muted)' }}>
        <span style={{ fontWeight: 600 }}>단계 — SW: SRS→SDS→UDS→STS→SUTS→SITS · 시스템: HSIS·SyTS·SyITS (상위 SyRS) · 실행: VectorCAST</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: COVERAGE_COLORS.covered.border, marginRight: 4, verticalAlign: 'middle' }} />연결됨</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#d1d5db', marginRight: 4, verticalAlign: 'middle' }} />끊김(연결 없음)</span>
        <span>P/F는 VectorCAST 실행 결과만 (STS/SUTS/SITS·SyTS/SyITS는 매핑 존재 표시)</span>
        <span>UDS 펼침 → 함수별 단위시험(SUTS) 중첩(같은 SUTS를 함수축으로 재배치 — 합산 아님) · <span style={{ color: COVERAGE_COLORS.partial.fg }}>⚠ = 단위시험 없는 함수 / 함수 미매핑 SUTS</span></span>
      </div>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
        {list.map((r, idx) => {
          // page-absolute index — 페이지/필터/정렬 전환 시 nodeId 충돌(유령 펼침) 방지.
          // anonymous·중복 reqId 행이 같은 page-local 위치에 와도 절대 인덱스로 구분되고,
          // 펼침 상태(Set)가 페이지 왕복 후에도 정확히 유지된다.
          const absIdx = baseIndex + idx;
          return (
            <TraceTreeRoot key={`${_rowReqId(r) || 'row'}#${absIdx}`} r={r} idx={absIdx} expanded={exp} onToggle={onToggle} />
          );
        })}
        {/* SRS 미추적 시험 — 요구사항 트리 하단의 별도 루트(역방향 추적성 공백). 페이지 무관 전체. */}
        <TraceUnmappedRoot unmapped={unmappedList} expanded={exp} onToggle={onToggle} />
      </ul>
    </div>
  );
}

// 의미 3버킷 정의 — suts_tested(검토 가치 ↑)를 맨 위로. warn=amber 강조.
const _UNMAPPED_BUCKETS = [
  { key: 'suts_tested', label: '단위시험까지 한 미추적 함수', desc: 'SUTS 단위시험은 있으나 이 SRS 요구사항에 안 닿음 — 요구사항 명세 공백 가능, 검토 가치 높음', warn: true },
  { key: 'isr', label: 'ISR·인터럽트·부트 핸들러', desc: '부트로더/ISR 등 SRS 추적 대상이 아닌 게 정상인 인프라 함수', warn: false },
  { key: 'vcast_only', label: 'VectorCAST 단독 커버리지', desc: 'SUTS 단위시험 참조 없이 VectorCAST만 시험한 함수', warn: false },
];

// ISO 26262 SwDS 계층 라벨(라운드112) — 미추적 함수의 layer 코드 → CSV/표시용 한국어.
const LAYER_LABELS = {
  APP_LEAF: '애플리케이션',
  BSW_DRIVER: 'BSW/드라이버',
  BOOT_REPROG: '부트/재프로그래밍',
  LIB_UTIL: '라이브러리',
  TEST_ARTIFACT: '시험산출물',
};

// SRS 미추적 시험 루트 — 시험은 됐으나 이 SRS에 안 닿는 VectorCAST 함수를 의미 버킷으로 묶는다.
// 요구사항 루트와 nodeId 네임스페이스(__unmapped__)를 분리해 펼침 상태 충돌을 막는다.
function TraceUnmappedRoot({ unmapped, expanded, onToggle }) {
  const list = Array.isArray(unmapped) ? unmapped : [];
  // hooks는 조건부 return 이전에 무조건 호출(rules of hooks) — list 빈 경우도 동일 순서 보장.
  const byCat = useMemo(() => {
    const m = { suts_tested: [], isr: [], vcast_only: [] };
    for (const u of list) (m[u.category] || (m[u.category] = [])).push(u);
    return m;
  }, [list]);
  if (list.length === 0) return null;
  const nodeId = '__unmapped__';
  const isOpen = expanded.has(nodeId);
  const failTotal = list.filter(u => /^(fail|failed|false|0)$/i.test(String(u.result || ''))).length;
  const safetyTotal = list.filter(u => u && u.safety).length;  // 안전/진단 토큰 보유(재검증 W4 가시화)
  // SDS 설계엔 명세됐으나 SRS만 끊긴 함수(역방향 부분추적). 정규화 fix 후 KJPDS02=0이나
  // 타 데이터/향후 대비 표기(라운드 109). >0일 때만 노출(safetyTotal 패턴과 동일).
  const sdsLinkedTotal = list.filter(u => u && Array.isArray(u.sds_reqs) && u.sds_reqs.length > 0).length;
  // UDS(단위설계) 연동 — SRS 역추적이 끊겨도 함수가 단위설계엔 존재(시험+단위설계 완료).
  // 사용자 질문("SDS 미추적이어도 UDS엔 연동돼 있나")의 직접 답: 대다수가 UDS엔 존재한다.
  // 미설계(in_uds=false)는 시험만 존재하는 진짜 설계 공백이라 빨강으로 별도 노출.
  // in_uds === false 만 갭으로 카운트(undefined=구 응답은 제외) — 버전 스큐 거짓 갭 방지(X6).
  const udsLinkedTotal = list.filter(u => u && u.in_uds === true).length;
  const designGapTotal = list.filter(u => u && u.in_uds === false).length;
  // ISO 26262 SwDS 계층(라운드112) — '애플리케이션 설계 공백(app_leaf=실 finding)'과
  // '정당한 범위 경계(bsw/boot/lib)'를 분리 표기. 구 응답엔 layer 없어 카운트 0 → 자동 숨김.
  // 기존 버킷/색은 그대로 두고 보조 hint 라인만 추가(보수적 단계 노출).
  const layerCounts = { APP_LEAF: 0, BSW_DRIVER: 0, BOOT_REPROG: 0, LIB_UTIL: 0, TEST_ARTIFACT: 0 };
  for (const u of list) { if (u && u.layer && layerCounts[u.layer] !== undefined) layerCounts[u.layer] += 1; }
  const hasLayers = (layerCounts.APP_LEAF + layerCounts.BSW_DRIVER + layerCounts.BOOT_REPROG + layerCounts.LIB_UTIL + layerCounts.TEST_ARTIFACT) > 0;
  return (
    <li style={{ borderTop: '2px solid var(--accent)' }}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        aria-label={`SRS 미추적 시험 ${list.length}건 ${isOpen ? '접기' : '펼치기'}`}
        onClick={() => onToggle(nodeId)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(nodeId); } }}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', flexWrap: 'wrap', background: COVERAGE_COLORS.partial.bg + '40' }}
      >
        <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{isOpen ? '▼' : '▶'}</span>
        <span style={{ fontWeight: 700, fontSize: 12 }}>🔎 SRS 미추적 시험</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          시험은 했으나 이 SRS 요구사항에 안 닿는 VectorCAST 함수 {list.length}종(중복 제거)
          {failTotal > 0 && <span style={{ color: '#dc2626', fontWeight: 600 }}> · {failTotal} fail</span>}
          {safetyTotal > 0 && <span style={{ color: COVERAGE_COLORS.partial.fg, fontWeight: 700 }}> · ⚠ {safetyTotal} 안전</span>}
          {sdsLinkedTotal > 0 && <span style={{ color: COVERAGE_COLORS.partial.fg, fontWeight: 600 }} title="SDS 설계엔 명세됐으나 그 요구사항이 SRS 추적 매트릭스 밖(부분추적)"> · {sdsLinkedTotal} SDS부분</span>}
          {udsLinkedTotal > 0 && <span style={{ color: COVERAGE_COLORS.covered.fg, fontWeight: 600 }} title="UDS 단위설계엔 함수가 존재 — 시험+단위설계 완료, SDS 아키텍처 roll-up만 누락(정당한 입도차)"> · {udsLinkedTotal} UDS설계</span>}
          {designGapTotal > 0 && <span style={{ color: COVERAGE_COLORS.uncovered.fg, fontWeight: 700 }} title="UDS 단위설계에도 없음 — 시험만 존재하는 진짜 설계 공백(검토 우선순위 높음)"> · {designGapTotal} 미설계</span>}
        </span>
        {hasLayers && (
          <span style={{ flexBasis: '100%', fontSize: 11, color: 'var(--text-muted)', paddingLeft: 22 }}>
            ISO 26262 계층:
            {layerCounts.APP_LEAF > 0 && <span style={{ color: COVERAGE_COLORS.partial.fg, fontWeight: 700 }} title="애플리케이션 구현 leaf 함수가 SDS에 함수단위로 미명세 — 아키텍처→유닛 roll-up 공백(실제 추적성 finding, 검토 권장)"> APP {layerCounts.APP_LEAF}</span>}
            {layerCounts.BOOT_REPROG > 0 && <span title="부트로더/재프로그래밍/EEPROM — SDS에 컴포넌트로 존재(컴포넌트 추적 성립), 별도 부트 설계 범위"> · 부트 {layerCounts.BOOT_REPROG}</span>}
            {layerCounts.BSW_DRIVER > 0 && <span title="기반 SW/드라이버(HAL·LIN/CAN) — BSW 설계명세/플랫폼 범위에서 추적(애플리케이션 SDS 범위 밖)"> · BSW {layerCounts.BSW_DRIVER}</span>}
            {layerCounts.LIB_UTIL > 0 && <span title="범용 라이브러리/연산 유틸 — 호출처 컴포넌트 설계에 라이브러리로 귀속 추적"> · LIB {layerCounts.LIB_UTIL}</span>}
            {layerCounts.TEST_ARTIFACT > 0 && <span title="시험 산출물/스텁 — 추적 대상 아님"> · 시험 {layerCounts.TEST_ARTIFACT}</span>}
            <span style={{ color: COVERAGE_COLORS.partial.fg }} title="APP=애플리케이션 설계 공백(실 finding) / 부트·BSW·LIB=정당한 범위 경계"> ⓘ</span>
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-muted)' }}>역방향 추적성 공백</span>
      </div>
      {isOpen && (
        <ul style={{ listStyle: 'none', margin: 0, padding: '0 12px 8px 30px', background: 'var(--bg)' }}>
          {_UNMAPPED_BUCKETS.map(b => (
            <TraceUnmappedBucket key={b.key} bucket={b} items={byCat[b.key] || []} parentId={nodeId} expanded={expanded} onToggle={onToggle} />
          ))}
        </ul>
      )}
    </li>
  );
}

// 미추적 버킷 1개 — 펼치면 subprogram·해석된 함수명·결과 표. 빈 버킷은 비활성(클릭 불가).
function TraceUnmappedBucket({ bucket, items, parentId, expanded, onToggle }) {
  const list = Array.isArray(items) ? items : [];
  const nodeId = `${parentId}::${bucket.key}`;
  const empty = list.length === 0;
  const isOpen = !empty && expanded.has(nodeId);
  const failN = list.filter(u => /^(fail|failed|false|0)$/i.test(String(u.result || ''))).length;
  const safetyN = list.filter(u => u && u.safety).length;  // 안전/진단 토큰 보유(W4)
  // 안전 항목이 있으면 비-warn 버킷(vcast_only/isr)이라도 amber로 승격 — 검토 신호 보존.
  const warn = (bucket.warn || safetyN > 0) && list.length > 0;
  // 안전 항목을 버킷 상단으로 정렬(잘림/스크롤 시 우선 노출). 안전 없으면 원순서 유지.
  const sorted = safetyN > 0 ? [...list].sort((a, b) => (b && b.safety ? 1 : 0) - (a && a.safety ? 1 : 0)) : list;
  return (
    <li style={{ marginTop: 6 }}>
      <div
        role={empty ? undefined : 'button'}
        tabIndex={empty ? undefined : 0}
        aria-expanded={empty ? undefined : isOpen}
        aria-label={empty ? undefined : `${bucket.label} ${list.length}건 ${isOpen ? '접기' : '펼치기'}`}
        onClick={empty ? undefined : () => onToggle(nodeId)}
        onKeyDown={empty ? undefined : (e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(nodeId); } })}
        title={bucket.desc}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 6, fontSize: 11,
          cursor: empty ? 'default' : 'pointer',
          background: empty ? '#f9fafb' : (warn ? COVERAGE_COLORS.partial.bg + '50' : COVERAGE_COLORS.covered.bg + '30'),
          border: `1px solid ${empty ? '#e5e7eb' : (warn ? COVERAGE_COLORS.partial.border : 'var(--border)')}` }}
      >
        <span style={{ fontFamily: 'monospace', fontSize: 10, width: 12, display: 'inline-block' }}>{empty ? '' : (isOpen ? '▼' : '▶')}</span>
        <span style={{ fontWeight: 700, color: warn ? COVERAGE_COLORS.partial.fg : 'var(--fg)' }}>
          {warn ? '⚠ ' : ''}{bucket.label}
        </span>
        <span style={{ color: empty ? '#9ca3af' : 'var(--text-muted)' }}>
          {list.length}개{failN > 0 ? ` · ${failN} fail` : ''}{safetyN > 0 ? ` · ⚠ ${safetyN} 안전` : ''}
        </span>
      </div>
      {isOpen && (
        <div style={{ margin: '4px 0 0 24px', maxHeight: 300, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6 }}>
          <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: '#e5e7eb' }}>
                <th style={{ padding: '3px 6px', textAlign: 'left' }}>Subprogram</th>
                <th style={{ padding: '3px 6px', textAlign: 'left' }}>해석된 함수</th>
                <th style={{ padding: '3px 6px', textAlign: 'left' }} title="SDS(설계)에 함수명으로 명세된 SRS 요구사항. SRS 미추적이라도 설계엔 닿으면 표기, 없으면 'SRS·SDS 모두 미명세'">SDS 설계</th>
                <th style={{ padding: '3px 6px', textAlign: 'left' }} title="UDS(단위설계) 인벤토리에 함수가 존재하는지. SRS 역추적이 끊겨도 단위설계엔 명세돼 있으면 '시험+단위설계 완료, SDS 아키텍처 roll-up만 누락'(정당한 입도차)이고, 없으면 시험만 존재하는 진짜 설계 공백">UDS 설계</th>
                <th style={{ padding: '3px 6px', textAlign: 'left' }} title="ISO 26262 SwDS 계층. 애플리케이션=구현 leaf가 SDS에 함수단위 미명세(실 finding) / 부트·BSW·라이브러리=정당한 범위 경계(컴포넌트·플랫폼·라이브러리 추적)">ISO계층</th>
                <th style={{ padding: '3px 6px', textAlign: 'center', width: 50 }}>결과</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((u, i) => {
                // SDS 멤버십 — sds_reqs는 (미추적 함수 특성상) 항상 SRS 매트릭스 밖 요구사항이다:
                // SDS엔 명세됐으나 그 요구사항이 SRS 추적 범위(SwFn/SwST 등 타 계층) 밖이라 SRS까진
                // 안 닿음. 녹색(추적됨) 대신 amber(부분추적)로 표기하고 툴팁에 명시(reviewer W2/F3).
                const sr = Array.isArray(u.sds_reqs) ? u.sds_reqs : [];
                // UDS(단위설계) 멤버십 — in_uds면 함수가 단위설계에 존재(uds_funcs 정규명).
                // SRS 역추적이 끊겨도 '시험+단위설계 완료'를 녹색으로 가시화하고, false면
                // 시험만 존재하는 진짜 설계 공백을 빨강으로 강조(사용자 질문: "uds랑은 연동돼 있나").
                const uf = Array.isArray(u.uds_funcs) ? u.uds_funcs : [];
                return (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border)', background: u && u.safety ? COVERAGE_COLORS.partial.bg + '60' : undefined }}>
                    <td style={{ padding: '3px 6px', fontFamily: 'monospace', fontWeight: u && u.safety ? 700 : undefined }}
                      title={u && u.safety ? '안전/진단 토큰 보유 — SRS 미추적이나 백워드 추적성 검토 권장' : undefined}>
                      {u && u.safety ? '⚠ ' : ''}{u.subprogram || '-'}
                    </td>
                    <td style={{ padding: '3px 6px', fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                      {(Array.isArray(u.resolved_funcs) && u.resolved_funcs.length) ? u.resolved_funcs.join(', ') : '—'}
                    </td>
                    {sr.length > 0
                      ? <td style={{ padding: '3px 6px', fontFamily: 'monospace', color: COVERAGE_COLORS.partial.fg, fontWeight: 600 }}
                          title={`SDS 설계엔 명세됨(요구사항 ${sr.join(', ')}) — 단 이 요구사항은 SRS 추적 매트릭스 밖이라 SRS까지 안 닿음(부분추적)`}>△ {sr.join(', ')}</td>
                      : <td style={{ padding: '3px 6px', color: '#9ca3af', fontStyle: 'italic' }}
                          title="SDS 설계에도 함수명으로 명세되지 않음 — SRS·SDS 모두 미명세">미명세</td>}
                    {/* in_uds 미존재(구 백엔드 응답·버전 스큐)는 중립('—')으로 — 미설계(빨강)로
                        오인하면 backend 재시작 전 전이 상태에서 전 항목이 거짓 갭으로 보인다(X6). */}
                    {typeof (u && u.in_uds) !== 'boolean'
                      ? <td style={{ padding: '3px 6px', color: '#9ca3af', fontStyle: 'italic' }}
                          title="UDS 연동 정보 없음(구 응답 형식) — backend 재생성 후 표기됨">—</td>
                      : u.in_uds
                        ? <td style={{ padding: '3px 6px', fontFamily: 'monospace', color: COVERAGE_COLORS.covered.fg, fontWeight: 600 }}
                            title={`UDS 단위설계에 명세됨${uf.length ? ` (${uf.join(', ')})` : ''} — 시험+단위설계 완료, SDS 아키텍처 roll-up만 누락(정당한 입도차)`}>✓ {uf.length ? uf.join(', ') : '설계됨'}</td>
                        : <td style={{ padding: '3px 6px', color: COVERAGE_COLORS.uncovered.fg, fontWeight: 600 }}
                            title="UDS 단위설계에도 함수가 없음 — 시험만 존재하는 진짜 설계 공백(검토 우선순위 높음)">✗ 미설계</td>}
                    {/* ISO 26262 계층(라운드112) — APP=애플리케이션 설계공백(실 finding) amber 강조,
                        부트/BSW/LIB=정당한 범위 경계 muted, 구 응답(layer 없음)은 중립 '—'. */}
                    {u && u.layer
                      ? <td style={{ padding: '3px 6px', color: u.layer === 'APP_LEAF' ? COVERAGE_COLORS.partial.fg : 'var(--text-muted)', fontWeight: u.layer === 'APP_LEAF' ? 700 : 400 }}
                          title={u.layer === 'APP_LEAF' ? '애플리케이션 구현 leaf — SDS에 함수단위 미명세(아키텍처→유닛 roll-up 공백, 검토 권장)' : '정당한 범위 경계 — 컴포넌트/플랫폼/라이브러리 레벨에서 추적'}>{LAYER_LABELS[u.layer] || u.layer}</td>
                      : <td style={{ padding: '3px 6px', color: '#9ca3af', fontStyle: 'italic' }} title="계층 정보 없음(구 응답 형식) — backend 재생성 후 표기됨">—</td>}
                    <td style={{ padding: '3px 6px', textAlign: 'center', fontWeight: 600, color: _testResultColor(u.result) }}>{u.result || '-'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </li>
  );
}

function TraceTreeRoot({ r, idx, expanded, onToggle }) {
  const reqId = _rowReqId(r) || `row-${idx}`;
  const nodeId = `${reqId}#${idx}`;
  const isOpen = expanded.has(nodeId);
  const status = deriveStatus(r);
  const colors = COVERAGE_COLORS[status] || {};
  const passCount = r.pass_count ?? 0;
  const failCount = r.fail_count ?? 0;
  const stageCounts = TREE_STAGES.map(s => ({ ...s, count: _stageMembers(r, s.key).items.length }));
  // 설계 단절: SRS→SDS는 됐으나 SDS→UDS(단위설계) 끊김. deriveStatus는 covered로 보지만
  // V-Model 중간 단계 공백이라 시각 마커로 별도 경고(판정 자체는 불변 — ASIL 안전로직 보존).
  const sdsN = (stageCounts.find(s => s.key === 'SDS') || {}).count || 0;
  const udsN = (stageCounts.find(s => s.key === 'UDS') || {}).count || 0;
  const designBreak = sdsN > 0 && udsN === 0;

  return (
    <li style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        aria-label={`요구사항 ${reqId} 추적성 트리 ${isOpen ? '접기' : '펼치기'}`}
        onClick={() => onToggle(nodeId)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(nodeId); } }}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', cursor: 'pointer', flexWrap: 'wrap', background: colors.bg ? colors.bg + '55' : 'transparent' }}
      >
        <span style={{ fontFamily: 'monospace', fontSize: 11 }}>{isOpen ? '▼' : '▶'}</span>
        <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 12, minWidth: 110 }}>{reqId}</span>
        {r.requirement_name && <span style={{ fontSize: 11, color: 'var(--text-muted)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.requirement_name}>{r.requirement_name}</span>}
        {/* 단계 체인 칩 — 끊긴 곳이 회색으로 드러남 */}
        <span style={{ display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
          {stageCounts.map((s, i) => (
            <React.Fragment key={s.key}>
              {i > 0 && <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{'→'}</span>}
              <span title={`${s.label}: ${s.count > 0 ? s.count + '개 연결' : '연결 없음(끊김)'}`}
                style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, fontWeight: 600, whiteSpace: 'nowrap',
                  background: s.count > 0 ? COVERAGE_COLORS.covered.bg : '#f3f4f6',
                  color: s.count > 0 ? COVERAGE_COLORS.covered.fg : '#9ca3af',
                  border: `1px solid ${s.count > 0 ? COVERAGE_COLORS.covered.border : '#e5e7eb'}` }}>
                {s.label} {s.count > 0 ? s.count : '·'}
              </span>
            </React.Fragment>
          ))}
        </span>
        {(passCount > 0 || failCount > 0) && (
          <span style={{ fontSize: 9, marginLeft: 4 }} title="VectorCAST 실행 결과">
            {passCount > 0 && <span style={{ color: '#16a34a', fontWeight: 600 }}>{passCount}P</span>}
            {passCount > 0 && failCount > 0 && '/'}
            {failCount > 0 && <span style={{ color: '#dc2626', fontWeight: 600 }}>{failCount}F</span>}
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          {designBreak && (
            <span title="SRS→SDS는 추적됐으나 SDS→UDS(단위설계)가 끊김 — 설계 추적 단절(covered 배지와 무관하게 검토 필요)"
              style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, fontWeight: 700, whiteSpace: 'nowrap',
                background: COVERAGE_COLORS.partial.bg, color: COVERAGE_COLORS.partial.fg, border: `1px solid ${COVERAGE_COLORS.partial.border}` }}>
              ⚠ 설계 단절
            </span>
          )}
          <StatusBadge tone={coverageTone(status)}>{status}</StatusBadge>
        </span>
      </div>
      {isOpen && (
        <ul style={{ listStyle: 'none', margin: 0, padding: '0 12px 8px 30px', background: 'var(--bg)' }}>
          {TREE_STAGES.map(s => (
            <TraceTreeStage key={s.key} r={r} stage={s} parentId={nodeId} expanded={expanded} onToggle={onToggle} />
          ))}
        </ul>
      )}
    </li>
  );
}

function TraceTreeStage({ r, stage, parentId, expanded, onToggle }) {
  const { type, items } = _stageMembers(r, stage.key);
  const count = items.length;
  const nodeId = `${parentId}::${stage.key}`;
  const broken = count === 0;
  const isOpen = !broken && expanded.has(nodeId);
  const accent = SOURCE_COLORS[stage.key] || (stage.kind === 'design' ? '#1e40af' : 'var(--fg)');

  // UDS 단계는 함수별로 단위시험(SUTS)을 중첩하고, 단위시험 없는 함수는 공백으로 표시한다.
  // SUTS 단계는 어느 UDS 함수에도 안 붙는 orphan SUTS(역방향 추적 공백)를 라벨에 노출한다.
  const isUds = stage.key === 'UDS';
  const isSuts = stage.key === 'SUTS';
  // 함수↔단위시험 매칭은 row 단위로만 변하므로 메모이즈(displayedRows=filtered.slice라 r 참조 안정
  // → 필터/rows 변경 전까지 유지). 무메모이즈 시 토글마다 row 전체 시험 재순회 비용 발생.
  const { fnMap, untestedFns, orphanSuts } = useMemo(() => {
    if (!isUds && !isSuts) return { fnMap: null, untestedFns: 0, orphanSuts: 0 };
    const m = _unitTestMap(r);
    const srcIds = Array.isArray(r.source_ids) ? r.source_ids : [];
    const untested = isUds ? srcIds.filter(fn => !((m.get(_normFn(fn)) || []).length)).length : 0;
    const udsSet = new Set(srcIds.map(_normFn));
    const orphan = isSuts
      ? _stageMembers(r, 'SUTS').items.filter(t => { const u = _normFn(t && t.unit); return u && !udsSet.has(u); }).length
      : 0;
    return { fnMap: m, untestedFns: untested, orphanSuts: orphan };
  }, [r, isUds, isSuts]);
  const warn = (isUds && untestedFns > 0) || (isSuts && orphanSuts > 0);

  let label;
  if (broken) label = stage.kind === 'design' ? '설계 연결 없음 — 추적 끊김' : '시험 연결 없음';
  else if (isUds) label = `함수 ${count}개${untestedFns ? ` · ⚠ ${untestedFns}개 단위시험 미연결` : ' · 모두 단위시험 연결'}`;
  else if (isSuts) label = `${count}개 연결${orphanSuts ? ` · ⚠ ${orphanSuts}건 함수 미매핑` : ''}`;
  else label = `${count}개 연결`;

  return (
    <li style={{ marginTop: 6 }}>
      <div
        role={broken ? undefined : 'button'}
        tabIndex={broken ? undefined : 0}
        aria-expanded={broken ? undefined : isOpen}
        aria-label={broken ? undefined : `${stage.label} ${label} ${isOpen ? '접기' : '펼치기'}`}
        onClick={broken ? undefined : () => onToggle(nodeId)}
        onKeyDown={broken ? undefined : (e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(nodeId); } })}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 8px', borderRadius: 6, fontSize: 11,
          cursor: broken ? 'default' : 'pointer',
          background: broken ? '#f9fafb' : (warn ? COVERAGE_COLORS.partial.bg + '50' : COVERAGE_COLORS.covered.bg + '40'),
          border: `1px solid ${broken ? '#e5e7eb' : (warn ? COVERAGE_COLORS.partial.border : COVERAGE_COLORS.covered.border)}` }}
      >
        <span style={{ fontFamily: 'monospace', fontSize: 10, width: 12, display: 'inline-block' }}>
          {broken ? '' : (isOpen ? '▼' : '▶')}
        </span>
        <span style={{ fontWeight: 700, minWidth: 78, color: accent }}>{stage.label}</span>
        <span style={{ color: broken ? '#9ca3af' : 'var(--fg)' }}>{label}</span>
      </div>
      {isOpen && (
        <div style={{ margin: '4px 0 0 24px' }}>
          {isUds ? (
            <ul style={{ listStyle: 'none', margin: 0, padding: 0, maxHeight: 260, overflowY: 'auto' }}>
              {items.map((fn, i) => (
                <TraceTreeFunc key={i} fn={String(fn)} tests={fnMap.get(_normFn(fn)) || []}
                  parentId={`${nodeId}#${i}`} expanded={expanded} onToggle={onToggle} />
              ))}
            </ul>
          ) : type === 'ids' ? (
            <div style={{ maxHeight: 180, overflowY: 'auto', fontSize: 11 }}>
              {items.map((id, i) => (
                <div key={i} style={{ padding: '2px 0', fontFamily: 'monospace', borderBottom: '1px solid var(--border)' }}>{String(id)}</div>
              ))}
            </div>
          ) : (
            <div style={{ maxHeight: 200, overflowY: 'auto' }}>
              <TestTable tests={items} />
            </div>
          )}
        </div>
      )}
    </li>
  );
}

// UDS 함수 1개 노드 — 그 함수를 시험하는 단위시험(SUTS) TC를 중첩 표시.
// 매칭 시험 0이면 'ISO 26262 단위시험 미연결' 공백을 amber로 드러낸다(함수 단위 추적 공백).
function TraceTreeFunc({ fn, tests, parentId, expanded, onToggle }) {
  const list = Array.isArray(tests) ? tests : [];
  const has = list.length > 0;
  const nodeId = `${parentId}::fn`;
  const isOpen = has && expanded.has(nodeId);
  return (
    <li>
      <div
        role={has ? 'button' : undefined}
        tabIndex={has ? 0 : undefined}
        aria-expanded={has ? isOpen : undefined}
        aria-label={has ? `함수 ${fn} 단위시험 ${list.length}개 ${isOpen ? '접기' : '펼치기'}` : `함수 ${fn} 단위시험 미연결`}
        onClick={has ? () => onToggle(nodeId) : undefined}
        onKeyDown={has ? (e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(nodeId); } }) : undefined}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '3px 8px', fontSize: 11,
          cursor: has ? 'pointer' : 'default', borderBottom: '1px solid var(--border)',
          background: has ? 'transparent' : COVERAGE_COLORS.partial.bg + '40' }}
      >
        <span style={{ fontFamily: 'monospace', fontSize: 10, width: 12, display: 'inline-block' }}>{has ? (isOpen ? '▼' : '▶') : ''}</span>
        <span style={{ fontFamily: 'monospace', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={fn}>{fn}</span>
        {has ? (
          <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, fontWeight: 600, whiteSpace: 'nowrap',
            background: COVERAGE_COLORS.covered.bg, color: COVERAGE_COLORS.covered.fg, border: `1px solid ${COVERAGE_COLORS.covered.border}` }}>
            단위시험 {list.length}
          </span>
        ) : (
          <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, fontWeight: 600, whiteSpace: 'nowrap',
            background: COVERAGE_COLORS.partial.bg, color: COVERAGE_COLORS.partial.fg, border: `1px solid ${COVERAGE_COLORS.partial.border}` }}>
            ⚠ 단위시험 미연결
          </span>
        )}
      </div>
      {isOpen && (
        <div style={{ margin: '3px 0 4px 24px', maxHeight: 200, overflowY: 'auto' }}>
          <TestTable tests={list} />
        </div>
      )}
    </li>
  );
}

/* ── CallTree — tree-sitter 정밀 함수 호출 트리 (viewMode='calltree') ──────────
 * 추적성 매트릭스와 같은 섹션('요구사항 커버리지') 안에서 함수 호출 관계를 보여준다.
 * 백엔드 POST /api/jenkins/call-tree (engine='precise', build_call_tree_precise)가
 * parse_c_project(tree-sitter)로 호출엣지를 추출하고, 노드에 ASIL/파일/시그니처를 실어준다.
 * - entry(진입 함수)는 빌드 소스의 known 함수명과 일치해야 적중. 매트릭스 source_ids에서 자동완성.
 * - 표준 라이브러리는 백엔드에서 제외. include_external 시 미정의(외부) 호출만 별도 표시.
 * - 루트는 기본 펼침(접기 가능), 하위는 클릭 펼침(깊은 트리 DOM 비용 절감). cycle/truncated 플래그 표시. */
function CallTreeNode({ node, path, expanded, onToggle, depth, includeExternal, switMap }) {
  const children = Array.isArray(node?.calls) ? node.calls : [];
  const externals = includeExternal && Array.isArray(node?.externals) ? node.externals : [];
  const hasChildren = children.length > 0 || externals.length > 0;
  // isOpen 규칙 — expanded Set은 "기본값에서 토글된 노드"를 담는다. 루트(depth 0)는 기본 열림이라
  // Set 포함=접힘, 하위(depth>0)는 기본 닫힘이라 Set 포함=펼침. toggle은 단순 멤버십 flip이라 양 depth 통일.
  // (과거 `depth===0 || has`는 루트를 항상 열림 고정 → ▾ 셰브론 클릭이 무반응인 dead affordance였음)
  const isOpen = expanded.has(path) !== (depth === 0);
  const asil = node?.asil ? String(node.asil).toUpperCase() : '';
  const isRoot = depth === 0;
  // 루트(진입 함수)만 참조 SwITS의 SwIT_SwUFn_ID로 라벨 전환(labelMode='swit' 시 switMap 주입).
  // 매핑 없으면 함수명 유지. 하위 노드는 SwIT 개념이 없어 항상 함수명.
  const switId = (isRoot && switMap && node?.name) ? switMap[String(node.name).trim()] : null;
  // hover 하이라이트는 CSS(.ct-node-row:hover)로 처리 — 노드별 useState 제거(비메모 컴포넌트라
  // 상위 hover가 하위 서브트리 전체 재렌더하던 W2 완화). 루트 배경은 인라인 유지(hover 무관 상시).
  return (
    <li style={{ listStyle: 'none' }}>
      <div
        className="ct-node-row"
        role={hasChildren ? 'button' : undefined}
        tabIndex={hasChildren ? 0 : undefined}
        aria-expanded={hasChildren ? isOpen : undefined}
        onClick={hasChildren ? () => onToggle(path) : undefined}
        onKeyDown={hasChildren ? (e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(path); } }) : undefined}
        title={node?.file || ''}
        style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '4px 8px', fontSize: 13, lineHeight: 1.5,
          cursor: hasChildren ? 'pointer' : 'default', borderRadius: 5,
          background: isRoot ? 'var(--bg-elevated)' : undefined,
          boxShadow: isRoot ? 'inset 3px 0 0 var(--accent)' : 'none', transition: 'background 0.08s' }}
      >
        <span style={{ fontFamily: 'monospace', width: 14, flex: '0 0 auto', textAlign: 'center', fontSize: 12,
          color: hasChildren ? 'var(--accent)' : 'var(--text-muted)' }}>
          {hasChildren ? (isOpen ? '▾' : '▸') : '·'}
        </span>
        <strong style={{ fontFamily: 'monospace', fontSize: isRoot ? 14 : 13, fontWeight: isRoot ? 700 : 600,
          color: isRoot ? _STAGE_COLORS.UDS : 'var(--fg)' }}>{switId || node?.name}</strong>
        {switId && (
          <code style={{ fontFamily: 'monospace', fontSize: 11, color: 'var(--text-muted)', fontWeight: 500 }}
            title="소스 함수명">{node?.name}</code>
        )}
        {node?.via_ref && (
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, fontWeight: 600, color: '#7c3aed', border: '1px dashed #7c3aed' }}
            title="직접 호출이 아니라 함수포인터 참조(&함수 / 대입 / 인자 전달)로 추론된 엣지 — 실제 호출은 런타임에 포인터로 이뤄짐">↪ 참조</span>
        )}
        {asil && (
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, fontWeight: 700, color: '#fff',
            background: _ASIL_COLORS[asil] || '#6b7280' }}>ASIL {asil}</span>
        )}
        {Array.isArray(node?.indirect) && node.indirect.length > 0 && (
          <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 8, fontWeight: 700, color: '#fff', background: '#ea580c' }}
            title={`함수포인터/디스패치 등 대상을 정적으로 못 잇는 간접 호출이 이 함수 본문에 있습니다(트리에 자식으로 안 나타남):\n· ${node.indirect.join('\n· ')}`}>
            ⚡ 간접호출 {node.indirect.length}
          </span>
        )}
        {node?.cycle && <span style={{ fontSize: 10, color: '#d97706', fontWeight: 600 }} title="재귀/순환 호출 — 더 펼치지 않음">↻ 순환</span>}
        {node?.truncated && <span style={{ fontSize: 10, color: '#d97706', fontWeight: 600 }} title="설정한 최대 깊이에 도달해 이 아래 호출은 생략됨 — 헤더의 '깊이'를 높이면 더 깊이까지 표시됩니다.">… 깊이제한</span>}
        {node?.signature && (
          <code style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 340 }}>
            {node.signature}
          </code>
        )}
      </div>
      {isOpen && hasChildren && (
        <ul style={{ margin: 0, paddingLeft: 20, marginLeft: 8, borderLeft: '1px solid var(--border)' }}>
          {children.map((c, i) => (
            <CallTreeNode key={`${path}.${i}`} node={c} path={`${path}.${i}`}
              expanded={expanded} onToggle={onToggle} depth={depth + 1} includeExternal={includeExternal} switMap={switMap} />
          ))}
          {externals.map((e, i) => (
            <li key={`ext-${path}-${i}`} style={{ listStyle: 'none', padding: '3px 8px', fontSize: 11, color: 'var(--text-muted)' }}>
              <span style={{ fontFamily: 'monospace' }}>{e?.name}</span>{' '}
              <em>[{e?.header || '?'} | {e?.library || '?'}]</em>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

// ── 전체 콜트리 루트 정렬/자동펼침 (표시 전용 — 커버리지/집계 무관) ──
// 루트를 진입점(boot) → ISR/인터럽트 → 일반(라이브러리 고아) 순으로 정렬해 main·_Startup을 최상단에
// 노출하고, boot 루트는 첫 레벨을 자동 펼쳐(_Startup→main) 애플리케이션 트리를 바로 보여준다.
// 백엔드는 이름 기반 우선순위만 부여하나(시그니처 부재), 프론트는 노드 signature('ISR (...)')까지
// 활용해 Cpu_* 등 시그니처 기반 ISR도 정확히 그룹핑한다.
const _CT_BOOT_NAMES = new Set(['main', '_start', '__start', '_startup', '_entrypoint', 'reset_handler', 'startup']);
function _ctRootKind(node) {
  const name = String(node?.name || '');
  const sig = String(node?.signature || '');
  if (_CT_BOOT_NAMES.has(name.toLowerCase())) return 0;               // 0 = boot/진입점
  if (/^\s*ISR\b/.test(sig) || /\bISR\s*\(/.test(sig)) return 1;      // 1 = ISR (tree-sitter 시그니처)
  if (/(_Interrupt|_isr|_ISR|_IRQHandler|_IrqHandler|_IRQ)$/.test(name) || /^ISR_/.test(name)) return 1;
  return 2;                                                            // 2 = 일반(라이브러리 고아 등)
}
function _ctSortRoots(trees, reverse = false) {
  // 안정 정렬: (kind, name, 원본 index) — 동일 입력에 동일 순서(결정적). load 시 자동펼침 path 계산과
  // 렌더가 반드시 같은 순서를 써야 하므로(index 정합) 양쪽 다 이 함수를 통과시킨다.
  // 역방향(reverse) 루트는 forward-leaf라 boot/ISR 개념이 대응 안 됨 → kind 비교 생략, 이름순만.
  return (Array.isArray(trees) ? trees : [])
    .map((t, i) => ({ t, i, k: reverse ? 0 : _ctRootKind(t), n: String(t?.name || '') }))
    .sort((a, b) => a.k - b.k || a.n.localeCompare(b.n) || a.i - b.i)
    .map(x => x.t);
}
function _ctBootExpansion(trees, reverse = false) {
  // boot 루트의 직계 자식 path를 펼침 집합에 넣어 _Startup→main 같은 첫 레벨을 자동 노출.
  // 반드시 정렬 후 index로 계산(렌더 path와 일치). boot 없으면 빈 Set(기존 동작 = 루트만 펼침).
  // 역방향은 boot 개념 무의미 → 자동펼침 없음(루트만 펼침).
  if (reverse) return new Set();
  const sorted = _ctSortRoots(trees, false);
  const set = new Set();
  sorted.forEach((t, ri) => {
    if (_ctRootKind(t) !== 0) return;
    const kids = Array.isArray(t?.calls) ? t.calls : [];
    kids.forEach((_, ci) => set.add(`${ri}.${ci}`));
  });
  return set;
}

// 모두 펼치기 — 로드된 트리의 모든 자식(비루트, 자식 보유) path를 펼침 집합에 담는다.
// isOpen 규칙(루트=기본열림, 비루트=기본닫힘)상 비루트 자식 path만 넣으면 전 노드가 열린다.
// 반드시 렌더와 동일한 sortedTrees를 넘겨야 path index가 정합(자식은 node.calls 원순서라 CallTreeNode와 동일).
function _ctAllExpandedPaths(trees) {
  const set = new Set();
  const walk = (node, path, depth) => {
    const kids = Array.isArray(node?.calls) ? node.calls : [];
    if (depth > 0 && kids.length) set.add(path);
    kids.forEach((c, i) => walk(c, `${path}.${i}`, depth + 1));
  };
  (Array.isArray(trees) ? trees : []).forEach((t, i) => walk(t, `${i}`, 0));
  return set;
}

function CallTreeView({ job, cacheRoot, buildSelector, sourceRoot, seedFns, toast, initialEntry = '' }) {
  const [entry, setEntry] = useState(initialEntry || '');
  const [depth, setDepth] = useState(5);
  const [includeExternal, setIncludeExternal] = useState(false);
  // 방향: callee(호출 →) / caller(← 역호출) / both(↕ 양방향 — 한 함수 중심 caller+callee 동시)
  const [direction, setDirection] = useState('callee');
  const reverse = direction === 'caller';
  const bidir = direction === 'both';
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [xlsxBusy, setXlsxBusy] = useState(false);
  const [expanded, setExpanded] = useState(() => new Set());
  const [allOpen, setAllOpen] = useState(false);
  // 라벨 표시 모드: 'func'(함수명) / 'swit'(참조 SwITS의 SwIT_SwUFn_ID). switMap은 {진입함수:ID}.
  const [labelMode, setLabelMode] = useState('func');
  const [switMap, setSwitMap] = useState(null);
  // SwIT ID 뷰: SITS 진입함수를 최상위로 재구성한 별도 트리(원본 data는 보존). null이면 재구성 안 됨(라벨-only 폴백).
  const [switViewData, setSwitViewData] = useState(null);
  const [switBusy, setSwitBusy] = useState(false);
  const mountedRef = useRef(true);
  // 요청 시퀀스 토큰 — 로딩 중 재진입(입력창 Enter/버튼 재클릭) 시 늦게 도착한 이전 응답이 최신 결과를
  // 덮어쓰지 않도록(stale setData 방지). load 진입마다 ++, resolve 시 자기 토큰이 최신일 때만 반영.
  const loadSeq = useRef(0);
  // 라벨 토글(swit 매핑 조회)의 재진입/data변경/언마운트 stale 방지 토큰 — load의 loadSeq와 분리.
  // data 변경 시 reset useEffect가 이 값을 증가시켜 in-flight toggleLabelMode를 무효화한다.
  const switSeq = useRef(0);
  // StrictMode(dev) 더블인보크 대비 — setup에서 true 복원(다른 섹션 동일 패턴). cleanup-only면 마운트 후 false 고착→자동로드 무음 실패.
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const toggle = useCallback((id) => {
    setExpanded(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }, []);

  // allRoots=true면 진입 함수 없이 백엔드가 in-degree 0 함수(+순환 대표)를 자동 루트로 전체 forest 구성.
  const load = useCallback(async (allRoots = false) => {
    const entries = String(entry || '').split(/[\n,]/).map(s => s.trim()).filter(Boolean);
    // 양방향(피벗): 진입 함수 1개 중심으로 callee(정방향)·caller(역방향)를 동시 요청. all_roots 무의미.
    if (bidir) {
      if (!entries.length) { toast('warning', '양방향 뷰는 진입 함수가 필요합니다 (예: main).'); return; }
      setLoading(true);
      const myseq = ++loadSeq.current;
      try {
        const body = (rev) => ({
          job_url: job?.url || '', cache_root: cacheRoot || '.devops_pro_cache',
          build_selector: buildSelector || 'lastSuccessfulBuild', source_root: sourceRoot || '',
          all_roots: false, reverse: rev, entry: entries.join(','),
          max_depth: Math.max(1, Math.min(20, Number(depth) || 5)), include_external: includeExternal, engine: 'precise',
        });
        const [callees, callers] = await Promise.all([
          post('/api/jenkins/call-tree', body(false)),
          post('/api/jenkins/call-tree', body(true)),
        ]);
        if (!mountedRef.current || myseq !== loadSeq.current) return;   // 재진입 stale 응답 무시
        setData({ bidir: true, callers, callees, stats: callees?.stats || {} });
        setExpanded(new Set());
        const st = callees?.stats || {};
        const miss = [...(callees?.missing || []), ...(callers?.missing || [])];
        if (miss.length) toast('warning', `미발견 함수: ${[...new Set(miss)].slice(0, 5).join(', ')} — 함수명을 확인하세요.`);
        else toast('success', `양방향 콜트리 (${st.engine || '?'} · 함수 ${st.functions ?? 0})`);
      } catch (e) {
        if (mountedRef.current && myseq === loadSeq.current) toast('error', e?.status === 404
          ? '캐시된 빌드가 없습니다 — 먼저 Jenkins 빌드를 동기화하세요.'
          : `양방향 콜트리 실패: ${e.message}`);
      } finally { if (mountedRef.current && myseq === loadSeq.current) setLoading(false); }
      return;
    }
    if (!allRoots && !entries.length) { toast('warning', '진입 함수명을 입력하세요 (예: main). 또는 [전체 트리]로 모든 루트를 자동 구성하세요.'); return; }
    setLoading(true);
    const myseq = ++loadSeq.current;
    try {
      const res = await post('/api/jenkins/call-tree', {
        job_url: job?.url || '',
        cache_root: cacheRoot || '.devops_pro_cache',
        build_selector: buildSelector || 'lastSuccessfulBuild',
        source_root: sourceRoot || '',
        all_roots: allRoots,
        reverse,
        entry: allRoots ? '' : entries.join(','),
        max_depth: Math.max(1, Math.min(20, Number(depth) || 5)),
        include_external: includeExternal,
        engine: 'precise',
      });
      if (!mountedRef.current || myseq !== loadSeq.current) return;   // 재진입 stale 응답 무시
      setData(res);
      // boot 루트(main·_Startup)의 첫 레벨을 자동 펼쳐 애플리케이션 트리를 바로 노출. boot가 없거나
      // 역방향이면 빈 Set(루트만 펼침). 정렬/index는 렌더 sortedTrees와 동일 함수·동일 reverse라 정합.
      setExpanded(_ctBootExpansion(res?.trees, res?.stats?.reverse));
      setAllOpen(false);   // 새 트리 로드 시 '모두 펼치기' 상태 초기화(라벨↔실제 펼침 정합)
      const miss = Array.isArray(res?.missing) ? res.missing : [];
      const st = res?.stats || {};
      // 백엔드가 실제 스캔한 소스(build_root/source 체크아웃 사본)의 완전성 신호. 명시적 false일 때만 경고
      // (구버전 백엔드는 undefined → 기존 동작 유지). 부분 체크아웃을 완료로 오인해 undercounted 트리를 신뢰하는 것 방지.
      const incomplete = res?.meta?.source_complete === false;
      if (miss.length) {
        toast('warning', `미발견 함수 ${miss.length}개: ${miss.slice(0, 5).join(', ')}${miss.length > 5 ? '…' : ''} — 빌드 소스의 함수명과 정확히 일치해야 합니다.${incomplete ? ' (체크아웃 소스가 미완 상태 — 빌드 동기화 완료 후 재시도 권장)' : ''}`);
      } else if (incomplete) {
        toast('warning', `콜트리 생성됨 (함수 ${st.functions ?? 0}) — 단, 체크아웃 소스가 미완(부분) 상태라 실제보다 적게 집계됐을 수 있습니다. 빌드 동기화 완료 후 재시도를 권장합니다.`);
      } else if (allRoots) {
        // 전체 트리는 백엔드가 루트 수(200)·포레스트 노드(60K)를 상한한다 — 절단 시 정직하게 경고.
        const trunc = st.roots_truncated || st.nodes_truncated;
        const dir = st.reverse ? '전체 역콜트리(called-by)' : '전체 콜트리';
        toast(trunc ? 'warning' : 'success',
          `${dir} 생성 (루트 ${st.roots ?? 0}${st.roots_truncated ? `/${st.roots_total}` : ''} · 함수 ${st.functions ?? 0} · 엣지 ${st.edges ?? 0})${trunc ? ' — 규모 상한 도달로 일부 절단(트리 깊이를 낮추거나 진입 함수를 지정하세요)' : ''}`);
      } else {
        toast('success', `${st.reverse ? '역콜트리(누가 호출하나)' : '콜트리'} 생성 (${st.engine || '?'} · 함수 ${st.functions ?? 0} · 엣지 ${st.edges ?? 0})`);
      }
    } catch (e) {
      // 404(캐시 빌드 부재)는 raw 영문 대신 안내 메시지 — [콜트리 생성]·[전체 트리] 공통.
      if (mountedRef.current && myseq === loadSeq.current) {
        const msg = e?.status === 404
          ? '캐시된 빌드가 없습니다 — 먼저 Jenkins 빌드를 동기화하거나, 소스가 있는 환경에서 진입 함수로 분석하세요.'
          : `콜트리 생성 실패: ${e.message}`;
        toast('error', msg);
      }
    } finally {
      if (mountedRef.current && myseq === loadSeq.current) setLoading(false);
    }
  }, [entry, depth, includeExternal, reverse, bidir, job, cacheRoot, buildSelector, sourceRoot, toast]);

  // 표에서 함수 클릭 진입(initialEntry) 시 자동 1회 로드 — 검색 입력 없이 바로 콜트리 표시.
  const didAutoLoad = useRef(false);
  useEffect(() => {
    // 소스(Jenkins job 또는 sourceRoot) 있을 때만 자동로드 — 무소스(로컬) 환경의 의도치 않은 404/에러 토스트 방지.
    if (initialEntry && !didAutoLoad.current && (job?.url || sourceRoot)) { didAutoLoad.current = true; load(); }
  }, [initialEntry, load, job, sourceRoot]);

  // xlsx 내보내기 — 현재 콜트리(data: 단방향 trees 또는 양방향 bidir)를 회사 SwITS
  // "2.SW Integration Strategy" 형식(depth 컬럼)으로 서버에서 렌더. 바이너리 응답이라
  // SwIT 매핑 해결 파라미터(설정>입력자료의 SITS 경로 → 기준 SCM → auto) — exportXlsx·fetchSwitMap 공유.
  const resolveSwitParams = useCallback(() => {
    let sitsPath = '';
    try { sitsPath = String((JSON.parse(localStorage.getItem('devops_v2_doc_paths') || '{}').sits) || '').trim(); }
    catch { sitsPath = ''; }
    let scmId = '';
    let autoSwit = false;
    if (!sitsPath) {
      scmId = String(localStorage.getItem('devops_v2_doc_scm') || '').trim();
      if (!scmId) autoSwit = true;
    }
    return { sitsPath, scmId, autoSwit };
  }, []);

  // api() 헬퍼 대신 raw fetch지만 authHeaders(Bearer+X-User) + res.ok 검사 명시(X9).
  // useSwitId=true면 진입 함수 블록 라벨을 참조 SwITS의 SwIT_SwUFn_ID로 치환(설정>입력자료의
  // SITS 경로를 sits_path로 전달, 백엔드가 매핑 추출). false면 함수명 모드(현재 방식). 두 방식 병존.
  const exportXlsx = useCallback(async (useSwitId = false) => {
    if (!data) { toast('warning', '먼저 콜트리를 생성한 뒤 내보내세요.'); return; }
    let sitsPath = '';
    let scmId = '';
    let autoSwit = false;
    if (useSwitId) {
      // sits_path → scm_id(linked_docs.sits) → auto_swit(매칭 최대 SCM). 화면 라벨 토글과 동일 로직.
      // 사전 경고로 차단하지 않고 항상 진행 — 매칭 결과는 X-Swit-Matched 헤더로 사후 표면화한다.
      ({ sitsPath, scmId, autoSwit } = resolveSwitParams());
    }
    setXlsxBusy(true);
    try {
      const meta = {
        job_url: job?.url || '',
        build_selector: buildSelector || '',
        source_root: sourceRoot || '',
        // 감사 provenance — 체크아웃 소스 미완(부분 집계) 신호를 xlsx 헤더에도 전달(W3).
        source_complete: data?.bidir ? data?.callees?.meta?.source_complete : data?.meta?.source_complete,
      };
      const bodyObj = { payload: data, meta };
      if (useSwitId) {
        if (sitsPath) bodyObj.sits_path = sitsPath;
        else if (scmId) bodyObj.scm_id = scmId;
        else if (autoSwit) bodyObj.auto_swit = true;
        // SITS 진입함수 기준으로 콜트리를 재생성해 참조 시트처럼 모든 SwIT 블록이 나오게 함
        // (화면이 전체 트리여도 SwIT ID xlsx는 SITS 진입함수 트리로 구성). 캐시 빌드 없으면 백엔드가 화면 트리 폴백.
        bodyObj.regen_from_sits = true;
        bodyObj.job_url = job?.url || '';
        bodyObj.cache_root = cacheRoot || '.devops_pro_cache';
        bodyObj.build_selector = buildSelector || 'lastSuccessfulBuild';
        bodyObj.source_root = sourceRoot || '';
        bodyObj.max_depth = Math.max(1, Math.min(20, Number(depth) || 5));
      }
      const res = await fetch(buildUrl('/api/jenkins/call-tree/export-xlsx'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(bodyObj),
      });
      if (!res.ok) {
        const t = await res.text().catch(() => '');
        throw new Error(`HTTP ${res.status} ${t.slice(0, 140)}`);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = useSwitId ? 'call_tree_swit_id.xlsx' : 'call_tree_integration_strategy.xlsx';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      if (useSwitId) {
        // W1: 백엔드가 'SwIT_ID 적용 루트 / 전체 SITS 매핑'을 x-swit-matched(예 "35/43")로, 소스에
        // 진입함수 정의가 없어 못 만든 수를 x-swit-missing으로 알림. 0매칭=함수명 폴백(경고), 부분
        // 생성(missing>0)=일부 진입함수 소스 부재(info·시트 하단 목록), 전량=성공. '35/35 다 됨'
        // 위장(실제 43개 중 35개)을 방지 — 감사자가 무엇이 왜 빠졌는지 알 수 있게 정직 표면화.
        const matched = res.headers.get('x-swit-matched') || '';
        const made = parseInt(matched.split('/')[0] || '0', 10) || 0;
        const total = parseInt(matched.split('/')[1] || '0', 10) || 0;
        // W2: X-Swit-Missing은 regen 성공(소스에 진입함수 정의 없어 확정 누락) 시에만 온다. 헤더에만
        // 근거하고 부재 시 미생성 수를 날조하지 않는다 — 폴백(캐시 없어 regen 미수행) 경로에서 없는
        // '시트 하단 목록'을 안내하고 틀린 사유를 대던 오도(감사 정직성 훼손)를 제거.
        const missing = parseInt(res.headers.get('x-swit-missing') || '0', 10) || 0;
        let level = 'success';
        let tail = ' (전량 적용)';
        if (!matched) {
          // I5: swit_map 자체를 못 찾음(SITS 경로/SCM 미해결, 헤더 부재) → 함수명 폴백임을 명시.
          level = 'warning';
          tail = ' — SITS 매핑을 찾지 못해 함수명으로 표시됨(설정>입력자료 SITS 경로/기준 SCM 확인)';
        } else if (made === 0) {
          level = 'warning';
          tail = ' (매칭 0 · 함수명으로 표시됨. 진입 함수 또는 설정>입력자료 SITS 경로 확인)';
        } else if (missing > 0) {
          // regen 성공 + 소스 미정의 누락: 시트 하단에 실제 미생성 목록이 있음.
          level = 'info';
          tail = ` · ${missing}개 미생성(스캔 소스에 진입함수 정의 없음 · 시트 하단 목록 확인)`;
        } else if (total > made) {
          // W2: regen 미수행(캐시 빌드 부재) 폴백 — 화면 트리 기준이라 나머지는 '소스 미정의'가 아님.
          level = 'info';
          tail = ` · 나머지 ${total - made}개는 이 화면 트리에 루트로 없음(진입 함수 기준 재생성 필요 — 캐시 빌드 확인)`;
        }
        toast(level,
          matched
            ? `SwIT ID 엑셀 내보냄 — SITS ${total || '?'}개 중 ${made}개 생성${tail}`
            : `SwIT ID 엑셀 내보냄${tail}`);
      } else {
        toast('success', '엑셀 파일을 내보냈습니다.');
      }
    } catch (e) {
      toast('error', `엑셀 내보내기 실패: ${e.message}`);
    } finally {
      setXlsxBusy(false);
    }
  }, [data, job, buildSelector, sourceRoot, toast, depth, cacheRoot, resolveSwitParams]);

  // 화면 라벨 토글용 매핑 조회(파일 생성 없이 {진입함수:SwIT_ID}만). 빈/실패는 {}.
  const fetchSwitMap = useCallback(async () => {
    if (!data) return {};
    const { sitsPath, scmId, autoSwit } = resolveSwitParams();
    const body = { payload: data };
    if (sitsPath) body.sits_path = sitsPath;
    else if (scmId) body.scm_id = scmId;
    else if (autoSwit) body.auto_swit = true;
    const r = await post('/api/jenkins/call-tree/swit-map', body);
    return (r && r.map && typeof r.map === 'object') ? r.map : {};
  }, [data, resolveSwitParams]);

  // 라벨 함수명 ⇄ SwIT ID 전환. swit로 갈 때 매핑이 없으면 백엔드에서 1회 조회 후 캐시.
  const toggleLabelMode = useCallback(async () => {
    if (labelMode === 'swit') { setLabelMode('func'); return; }   // 원본 트리로 복귀(switViewData 캐시 유지)
    if (switViewData && switMap && Object.keys(switMap).length) { setLabelMode('swit'); return; }  // 캐시 재사용
    const myseq = ++switSeq.current;   // W1: 이 조회 인스턴스 토큰
    setSwitBusy(true);
    try {
      const m = await fetchSwitMap();
      // W1: await 중 언마운트/재진입/data변경(reset useEffect가 switSeq 증가) 시 stale 반영 차단.
      if (!mountedRef.current || myseq !== switSeq.current) return;
      const cnt = m ? Object.keys(m).length : 0;
      if (!cnt) {
        setSwitMap({});
        toast('warning', 'SwIT 매핑을 찾지 못했습니다 — 설정>입력자료의 SITS 경로 또는 기준 SCM을 확인하세요. (함수명 유지)');
        return;
      }
      // SITS 진입함수를 최상위로 재구성(Excel(SwIT ID)와 동일 뷰). 진입함수들로 콜트리 재생성.
      const entries = Object.keys(m);
      let regen = null;
      try {
        regen = await post('/api/jenkins/call-tree', {
          job_url: job?.url || '', cache_root: cacheRoot || '.devops_pro_cache',
          build_selector: buildSelector || 'lastSuccessfulBuild', source_root: sourceRoot || '',
          all_roots: false, reverse: false, entry: entries.join(','),
          max_depth: Math.max(1, Math.min(20, Number(depth) || 5)), include_external: includeExternal, engine: 'precise',
        });
      } catch { regen = null; }
      if (!mountedRef.current || myseq !== switSeq.current) return;   // W1: 재생성 대기 중 stale 차단
      setSwitMap(m);
      if (regen && Array.isArray(regen.trees) && regen.trees.length) {
        setSwitViewData(regen);
        setExpanded(new Set());
        setLabelMode('swit');
        const roots = regen.trees.map(t => String(t?.name || ''));
        const matched = roots.filter(n => m[n]).length;
        toast('success', `SwIT ID 뷰 — 진입 함수 ${roots.length}개를 최상위로 재구성 (${matched}개 SwIT_ID · 참조 SITS ${cnt}개)`);
      } else {
        // 캐시 빌드 부재 등으로 재구성 불가 → 현재 트리에 라벨만(폴백). switViewData 없이 labelMode만 전환.
        setSwitViewData(null);
        setLabelMode('swit');
        const roots = Array.isArray(data?.trees) ? data.trees.map(t => String(t?.name || '')) : [];
        const matched = roots.filter(n => m[n]).length;
        toast('info', `SwIT ID 라벨 — 캐시 빌드가 없어 현재 트리에 라벨만 적용(${matched}/${roots.length}). 진입 함수 재구성은 Jenkins 빌드 캐시가 필요합니다.`);
      }
    } catch (e) {
      if (mountedRef.current && myseq === switSeq.current) toast('error', `SwIT ID 뷰 실패: ${e.message}`);
    } finally {
      if (mountedRef.current && myseq === switSeq.current) setSwitBusy(false);
    }
  }, [labelMode, switViewData, switMap, fetchSwitMap, data, job, cacheRoot, buildSelector, sourceRoot, depth, includeExternal, toast]);

  // 새 콜트리 로드 시 라벨 모드/매핑 초기화(이전 트리 매핑을 새 트리에 잘못 적용 방지).
  useEffect(() => { switSeq.current += 1; setLabelMode('func'); setSwitMap(null); setSwitViewData(null); }, [data]);

  // SwIT ID 뷰 활성 시 재구성 트리(switViewData)를, 아니면 원본 data를 렌더 소스로. 원본은 불변 보존.
  const activeData = (labelMode === 'swit' && switViewData) ? switViewData : data;
  const trees = Array.isArray(activeData?.trees) ? activeData.trees : [];
  const st = activeData?.stats || {};
  // 진입점(boot)→ISR→일반 순 정렬(역방향은 이름순). load의 _ctBootExpansion과 동일 정렬 함수·동일
  // reverse(로드된 데이터 기준 st.reverse)라 자동펼침 path가 정합.
  const sortedTrees = useMemo(() => _ctSortRoots(trees, st.reverse), [trees, st.reverse]);
  // 모두 펼치기/접기 — 클라 측(재조회 없음). 펼침=로드된 전 노드 path, 접기=기본(boot) 펼침.
  // sortedTrees를 넘겨 렌더와 동일 index로 path 생성(정합). 단방향(trees) 전용 — 양방향은 caller/callee 블록이라 별도.
  const toggleAllOpen = () => {
    const next = !allOpen;
    if (next) {
      const paths = _ctAllExpandedPaths(sortedTrees);
      // W1: 대형 트리(전체 트리 등)를 한 번에 펼치면 비메모 CallTreeNode 수천 개가 단일 렌더
      // 패스로 동시 마운트 → 브라우저 프리즈 위험. 임계 초과 시 확인 게이트로 사용자 동의 후 진행.
      if (paths.size > 2000 && typeof window !== 'undefined' && typeof window.confirm === 'function'
          && !window.confirm(`${paths.size.toLocaleString()}개 노드를 한 번에 펼칩니다. 트리가 크면 브라우저가 잠시 느려질 수 있습니다. 계속할까요?`)) {
        return;
      }
      setAllOpen(true);
      setExpanded(paths);
    } else {
      setAllOpen(false);
      setExpanded(_ctBootExpansion(trees, st.reverse));
    }
  };
  // 방향 토글을 바꾸고 재조회 전이면 표시 데이터(로드 시점 방향)와 컨트롤(direction)이 불일치 — 시각 단서.
  const loadedBidir = !!data?.bidir;
  const dirStale = !!data && (loadedBidir !== bidir || (!loadedBidir && (!!st.reverse !== reverse)));

  return (
    <div style={{ padding: '8px 0' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, marginBottom: 10,
        padding: 10, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 6 }}>
        <input list="calltree-seed-fns" value={entry} onChange={e => setEntry(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); load(); } }}
          placeholder="진입 함수명 (콤마 구분, 예: main, App_Init)"
          style={{ flex: '1 1 280px', minWidth: 200, padding: '6px 8px', fontSize: 12, fontFamily: 'monospace',
            border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--fg)' }} />
        <datalist id="calltree-seed-fns">
          {(seedFns || []).map(f => <option key={f} value={f} />)}
        </datalist>
        <label style={{ fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          깊이
          <input type="number" min={1} max={20} value={depth} onChange={e => setDepth(Number(e.target.value))}
            style={{ width: 56, padding: '5px 6px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--fg)' }} />
        </label>
        <label style={{ fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}
          title="표준 라이브러리를 제외한 외부(미정의) 함수 호출도 트리에 표시">
          <input type="checkbox" checked={includeExternal} onChange={e => setIncludeExternal(e.target.checked)} style={{ cursor: 'pointer' }} />
          외부 함수
        </label>
        <label style={{ fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4 }}
          title="방향 — 호출: 이 함수가 부르는 함수(callee, 하향) / 역호출: 이 함수를 부르는 함수(caller, 상향 — 영향분석) / 양방향: 한 함수 중심으로 위 caller·아래 callee 동시(진입 함수 필요)">
          방향
          <select value={direction} onChange={e => setDirection(e.target.value)}
            style={{ padding: '5px 6px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>
            <option value="callee">호출 → (callee)</option>
            <option value="caller">← 역호출 (caller)</option>
            <option value="both">↕ 양방향 (caller+callee)</option>
          </select>
        </label>
        <button type="button" onClick={() => load(false)} disabled={loading}
          style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, border: 'none', borderRadius: 4, cursor: loading ? 'default' : 'pointer',
            background: loading ? 'var(--border)' : 'var(--accent)', color: '#fff' }}>
          {loading ? '분석 중…' : (bidir ? '양방향 생성' : reverse ? '역콜트리 생성' : '콜트리 생성')}
        </button>
        {!bidir && (
          <button type="button" onClick={() => load(true)} disabled={loading}
            title="진입 함수 입력 없이, 아무 함수도 호출하지 않는 함수(루트: main·ISR·콜백·미사용)를 자동 탐지해 프로젝트 전체 호출 트리를 구성합니다."
            style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, borderRadius: 4, cursor: loading ? 'default' : 'pointer',
              background: 'var(--bg)', color: 'var(--accent)', border: '1px solid var(--accent)' }}>
            {reverse ? '전체 역트리' : '전체 트리'}
          </button>
        )}
        {trees.length > 0 && (
          <button type="button" onClick={toggleAllOpen}
            title={allOpen ? '모든 하위 노드 접기(기본 펼침으로 복귀)' : '로드된 모든 하위 노드를 한 번에 펼치기'}
            style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, borderRadius: 4, cursor: 'pointer',
              background: 'var(--bg)', color: 'var(--fg)', border: '1px solid var(--border)' }}>
            {allOpen ? '모두 접기 ⊟' : '모두 펼치기 ⊞'}
          </button>
        )}
        {data && !data.bidir && (
          <button type="button" onClick={toggleLabelMode} disabled={loading || switBusy}
            title="진입 함수(루트) 라벨을 함수명 ⇄ 참조 SwITS의 SwIT_SwUFn_ID로 전환합니다(화면 표시 전용). SwIT ID 매핑은 설정>입력자료의 SITS 경로 또는 기준 SCM에서 읽습니다."
            style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, borderRadius: 4, cursor: (loading || switBusy) ? 'default' : 'pointer',
              background: labelMode === 'swit' ? 'var(--accent)' : 'var(--bg)', color: labelMode === 'swit' ? '#fff' : 'var(--accent)', border: '1px solid var(--accent)' }}>
            {switBusy ? '매핑 로드…' : (labelMode === 'swit' ? '라벨: SwIT ID ⇄' : '라벨: 함수명 ⇄')}
          </button>
        )}
        {data && (
          <>
            <button type="button" onClick={() => exportXlsx(false)} disabled={loading || xlsxBusy}
              title="현재 호출 트리를 SwITS 통합전략(2.SW Integration Strategy) 형식 xlsx로 내보냅니다 — 진입 함수 블록을 함수명으로 표시. depth 컬럼·정의 파일·ASIL·마커 포함."
              style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, borderRadius: 4, cursor: (loading || xlsxBusy) ? 'default' : 'pointer',
                background: 'var(--bg)', color: 'var(--accent)', border: '1px solid var(--accent)' }}>
              {xlsxBusy ? '생성 중…' : 'Excel(함수명) ↓'}
            </button>
            <button type="button" onClick={() => exportXlsx(true)} disabled={loading || xlsxBusy}
              title="진입 함수 블록을 참조 SwITS의 SwIT_SwUFn_ID로 표시해 내보냅니다(설정>입력자료의 SITS 경로 필요). 매칭 안 되는 함수는 함수명 유지."
              style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, borderRadius: 4, cursor: (loading || xlsxBusy) ? 'default' : 'pointer',
                background: 'var(--bg)', color: '#fff', border: '1px solid var(--accent)',
                backgroundColor: 'var(--accent)' }}>
              {xlsxBusy ? '생성 중…' : 'Excel(SwIT ID) ↓'}
            </button>
          </>
        )}
      </div>

      {dirStale && (
        <div style={{ fontSize: 11, color: '#92400e', background: '#fffbeb', border: '1px solid #fde68a',
          borderRadius: 4, padding: '5px 8px', marginBottom: 8 }}>
          ⚠ 방향을 바꿨습니다 — 현재 표시된 것은 여전히 <strong>{loadedBidir ? '양방향' : st.reverse ? '역호출(caller)' : '호출(callee)'}</strong> 기준입니다.
          [{bidir ? '양방향 생성' : reverse ? '역콜트리 생성' : '콜트리 생성'}]을 다시 눌러 반영하세요.
        </div>
      )}

      {!data && !loading && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 4px' }}>
          진입 함수명을 입력하고 <strong>콜트리 생성</strong>을 누르면 tree-sitter로 분석한 함수 호출 트리를 보여줍니다.
          진입점을 모르면 <strong>전체 트리</strong>로 프로젝트의 모든 루트 함수(main·ISR·콜백·미사용)를 자동 탐지해 전체 호출 구조를 구성합니다.
          <strong>방향</strong>을 <em>역호출</em>로 바꾸면 “누가 이 함수를 호출하나(caller)”를 상향 추적하고, <em>양방향</em>은 한 함수를 중심에 두고 위 caller·아래 callee를 동시에 보여줍니다(영향분석).
          함수포인터 참조로 추론된 엣지는 <span style={{ color: '#7c3aed' }}>↪ 참조</span>, 대상을 못 잇는 간접호출(디스패치·콜백)은 <span style={{ color: '#ea580c' }}>⚡ 간접호출</span> 배지로 표시합니다.
          매트릭스가 로드돼 있으면 입력란에서 설계 함수명 자동완성을 제안합니다.
        </div>
      )}

      {data && data.bidir && (() => {
        // 양방향(피벗): 각 진입 함수를 중심으로 위=caller·아래=callee를 스택. 콤마로 여러 진입 함수를 주면
        // 함수마다 독립 피벗 블록으로 렌더(과거엔 trees[0]만 그려 나머지를 성공 토스트로 위장한 채 silent drop).
        // caller/callee 트리는 index가 아니라 함수명으로 짝지어 매칭(백엔드가 direction 무관 동일 known을
        // 순회하므로 정렬은 같으나, misalignment 방어). 경로 접두사 c{블록}_{i} / e{블록}_{i}로 충돌 방지.
        const calleeTrees = Array.isArray(data.callees?.trees) ? data.callees.trees : [];
        const callerTrees = Array.isArray(data.callers?.trees) ? data.callers.trees : [];
        const callerByName = new Map(callerTrees.map(t => [String(t?.name || ''), t]));
        const calleeByName = new Map(calleeTrees.map(t => [String(t?.name || ''), t]));
        // 중심 함수 목록(callee 트리 순서 우선, caller-only 보충) — 중복 제거.
        const names = [];
        const seenNames = new Set();
        [...calleeTrees, ...callerTrees].forEach(t => {
          const n = String(t?.name || '');
          if (n && !seenNames.has(n)) { seenNames.add(n); names.push(n); }
        });
        const bst = data.callees?.stats || {};
        const notFound = names.length === 0;
        return (
          <div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
              <span style={{ fontWeight: 700, color: '#0369a1' }}>↕ 양방향 (caller+callee)</span>
              <span>엔진 <strong style={{ color: bst.engine === 'tree-sitter' ? '#16a34a' : '#d97706' }}>{bst.engine || '?'}</strong></span>
              <span>함수 {bst.functions ?? 0}</span>
              {names.length > 1 && <span>중심 <strong>{names.length}</strong>개</span>}
            </div>
            {notFound ? (
              <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 12, textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 6 }}>
                입력한 함수를 빌드 소스에서 찾지 못했습니다 — 함수명/소스 캐시를 확인하세요.
              </div>
            ) : (
              names.map((nm, bi) => {
                const centerNode = calleeByName.get(nm) || callerByName.get(nm) || null;
                const cAsil = centerNode?.asil ? String(centerNode.asil).toUpperCase() : '';
                const callers = callerByName.get(nm)?.calls || [];
                const callees = calleeByName.get(nm)?.calls || [];
                const multi = names.length > 1;
                return (
                  <div key={`pivot-${bi}`}
                    style={multi ? { marginBottom: 14, paddingBottom: 10, borderBottom: '1px dashed var(--border)' } : undefined}>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#c026d3', marginBottom: 4 }}>⬆ 이 함수를 호출하는 함수 (caller)</div>
                    {callers.length ? (
                      <ul style={{ margin: '0 0 6px', padding: 0 }}>
                        {callers.map((n, i) => (
                          <CallTreeNode key={`c${bi}_${i}`} node={n} path={`c${bi}_${i}`} expanded={expanded} onToggle={toggle} depth={1} includeExternal={includeExternal} />
                        ))}
                      </ul>
                    ) : <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '2px 6px 6px' }}>호출하는 함수 없음 (진입점·미사용)</div>}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', margin: '4px 0',
                      background: 'var(--bg)', border: '2px solid var(--accent)', borderRadius: 6 }}>
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>◆ 중심</span>
                      <strong style={{ fontFamily: 'monospace', fontSize: 12 }}>{nm}</strong>
                      {cAsil && <span style={{ fontSize: 9, padding: '0 5px', borderRadius: 8, fontWeight: 700, color: '#fff', background: _ASIL_COLORS[cAsil] || '#6b7280' }}>ASIL {cAsil}</span>}
                      {Array.isArray(centerNode?.indirect) && centerNode.indirect.length > 0 && (
                        <span style={{ fontSize: 9, padding: '0 5px', borderRadius: 8, fontWeight: 700, color: '#fff', background: '#ea580c' }}
                          title={`미해결 간접호출:\n· ${centerNode.indirect.join('\n· ')}`}>⚡ 간접호출 {centerNode.indirect.length}</span>
                      )}
                    </div>
                    <div style={{ fontSize: 11, fontWeight: 600, color: '#0891b2', margin: '4px 0' }}>⬇ 이 함수가 호출하는 함수 (callee)</div>
                    {callees.length ? (
                      <ul style={{ margin: 0, padding: 0 }}>
                        {callees.map((n, i) => (
                          <CallTreeNode key={`e${bi}_${i}`} node={n} path={`e${bi}_${i}`} expanded={expanded} onToggle={toggle} depth={1} includeExternal={includeExternal} />
                        ))}
                      </ul>
                    ) : <div style={{ fontSize: 11, color: 'var(--text-muted)', padding: '2px 6px' }}>호출하는 하위 함수 없음 (leaf)</div>}
                  </div>
                );
              })
            )}
          </div>
        );
      })()}

      {activeData && !activeData.bidir && (
        <div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
            {st.reverse && <span style={{ fontWeight: 700, color: '#c026d3' }} title="역방향 — 자식은 이 함수를 호출하는 함수(caller)">← 역콜트리(누가 호출하나)</span>}
            <span>엔진 <strong style={{ color: st.engine === 'tree-sitter' ? '#16a34a' : '#d97706' }}>{st.engine || '?'}</strong></span>
            <span>스캔 파일 {st.files_scanned ?? 0}</span>
            <span>함수 {st.functions ?? 0}</span>
            <span>호출 엣지 {st.edges ?? 0}</span>
            {st.roots > 0 && <span>루트 <strong>{st.roots}</strong>{!st.reverse && <span style={{ opacity: 0.65 }}> · 진입점·ISR 우선</span>}</span>}
            {Array.isArray(activeData.missing) && activeData.missing.length > 0 && (
              <span style={{ color: '#d97706' }}>미발견 {activeData.missing.length}</span>
            )}
          </div>
          {trees.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 12, textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 6 }}>
              표시할 호출 트리가 없습니다.
              {Array.isArray(activeData.missing) && activeData.missing.length > 0 && (
                <> 입력한 함수({activeData.missing.join(', ')})를 빌드 소스에서 찾지 못했습니다 — 함수명/소스 캐시를 확인하세요.</>
              )}
            </div>
          ) : (
            <ul style={{ margin: 0, padding: 0 }}>
              {sortedTrees.map((t, i) => (
                <CallTreeNode key={i} node={t} path={`${i}`} expanded={expanded} onToggle={toggle} depth={0} includeExternal={includeExternal} switMap={labelMode === 'swit' ? switMap : null} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/* ── 인라인 콜트리 (표 행 펼침 내부 — 탭 전환 없이 UDS 함수의 호출 트리를 그 자리에서 표시) ──
 * CallTreeView(탭 전용)의 축약판: 진입 함수 1개 고정, 방향(호출/역호출) 토글, 깊이 조절(기본 8·최대 20)·모두 펼치기, 외부함수 제외.
 * 소스(job.url 또는 sourceRoot) 없으면 요청하지 않고 안내(로컬 파일모드의 doomed 404 방지).
 * CallTreeNode·_ctSortRoots·_ctBootExpansion(모듈 SSOT) 재사용 — 렌더/정렬 규칙이 탭과 동일.
 * loadSeq/mountedRef로 방향 연타·언마운트 시 stale setData 방지(CallTreeView와 동일 패턴).
 * job 객체 대신 jobUrl 문자열을 deps로 써서 부모 리렌더로 인한 무한 재조회를 차단. */
function InlineCallTree({ fn, job, cacheRoot, buildSelector, sourceRoot, onOpenFull, onClose }) {
  const bare = String(fn || '').split(/[\s(]/)[0].trim();
  const jobUrl = job?.url || '';
  const hasSource = !!(jobUrl || sourceRoot);
  const [direction, setDirection] = useState('callee');   // 'callee'(호출→) | 'caller'(←역호출)
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(() => new Set());
  const [depth, setDepth] = useState(8);                  // 확정 깊이(load 구동) — depthInput에서 디바운스 반영
  const [depthInput, setDepthInput] = useState(8);        // 입력창 값(즉시) — 타이핑 중 재조회 폭주(W1) 방지용 분리
  const [allOpen, setAllOpen] = useState(false);          // 모두 펼치기 상태(로드된 노드 전체 펼침/접기)
  const mountedRef = useRef(true);
  const loadSeq = useRef(0);
  useEffect(() => { mountedRef.current = true; return () => { mountedRef.current = false; }; }, []);

  const toggle = useCallback((id) => {
    setExpanded(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }, []);

  const load = useCallback(async (dir) => {
    if (!bare || !hasSource) return;
    const rev = dir === 'caller';
    setLoading(true); setError('');
    const myseq = ++loadSeq.current;
    try {
      const res = await post('/api/jenkins/call-tree', {
        job_url: jobUrl,
        cache_root: cacheRoot || '.devops_pro_cache',
        build_selector: buildSelector || 'lastSuccessfulBuild',
        source_root: sourceRoot || '',
        all_roots: false, reverse: rev, entry: bare,
        max_depth: Math.min(20, Math.max(1, depth || 1)), include_external: false, engine: 'precise',
      });
      if (!mountedRef.current || myseq !== loadSeq.current) return;   // 재진입/언마운트 stale 무시
      setData(res);
      setExpanded(_ctBootExpansion(res?.trees, res?.stats?.reverse));
      setAllOpen(false);   // 새 데이터 로드 시 펼침 상태 초기화(깊이/방향 변경 후 일관)
      const miss = Array.isArray(res?.missing) ? res.missing : [];
      if (miss.length) setError(`빌드 소스에서 '${bare}'를 찾지 못했습니다 — 함수명/소스 캐시를 확인하세요.`);
    } catch (e) {
      if (mountedRef.current && myseq === loadSeq.current) {
        setError(e?.status === 404
          ? '캐시된 빌드가 없습니다 — 먼저 Jenkins 빌드를 동기화하세요.'
          : `콜트리 실패: ${e.message}`);
      }
    } finally {
      if (mountedRef.current && myseq === loadSeq.current) setLoading(false);
    }
  }, [bare, hasSource, jobUrl, cacheRoot, buildSelector, sourceRoot, depth]);

  // 마운트 + 방향/깊이 변경 시 자동 로드 (load가 depth를 deps로 물어 깊이 변경 시 재조회)
  useEffect(() => { load(direction); }, [direction, load]);

  // depthInput → depth 디바운스(350ms) — number input 타이핑 중 키마다 재조회하던 낭비(W1) 차단.
  // 확정 depth만 load deps를 바꿔 재조회를 1회로 합침(loadSeq가 stale 응답은 폐기하나 파싱 낭비 방지).
  useEffect(() => {
    const t = setTimeout(() => setDepth(depthInput), 350);
    return () => clearTimeout(t);
  }, [depthInput]);

  const trees = Array.isArray(data?.trees) ? data.trees : [];
  const st = data?.stats || {};
  const reverse = direction === 'caller';
  const sortedTrees = useMemo(() => _ctSortRoots(trees, st.reverse), [trees, st.reverse]);

  // 모두 펼치기/접기 — 클라이언트 측(재조회 없음). 펼침=로드된 전 노드 path, 접기=기본(boot) 펼침.
  const toggleAllOpen = () => {
    const next = !allOpen;
    setAllOpen(next);
    setExpanded(next ? _ctAllExpandedPaths(sortedTrees) : _ctBootExpansion(trees, st.reverse));
  };

  return (
    <div style={{ marginTop: 12, border: '1px solid var(--accent)', borderRadius: 8, background: 'var(--panel)',
      overflow: 'hidden', boxShadow: '0 2px 10px rgba(0,0,0,0.07)' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, padding: '8px 12px',
        borderBottom: '1px solid var(--border)', background: 'var(--bg-elevated)' }}>
        <span style={{ fontSize: 13, fontWeight: 700 }}>콜트리</span>
        <code style={{ fontSize: 13, fontFamily: 'monospace', fontWeight: 700, color: _STAGE_COLORS.UDS,
          background: 'var(--bg)', padding: '2px 9px', borderRadius: 6, border: '1px solid var(--border)' }}>{bare}</code>
        <div style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          {[['callee', '호출 →'], ['caller', '← 역호출']].map(([v, label]) => (
            <button key={v} type="button" onClick={() => setDirection(v)}
              title={v === 'callee' ? '이 함수가 호출하는 하위 함수(callee, 하향)' : '이 함수를 호출하는 함수(caller, 상향 — 영향분석)'}
              style={{ fontSize: 11, padding: '4px 12px', border: 'none', cursor: 'pointer', fontWeight: direction === v ? 700 : 500,
                background: direction === v ? 'var(--accent)' : 'transparent', color: direction === v ? '#fff' : 'var(--fg)' }}>{label}</button>
          ))}
        </div>
        <label style={{ fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--text-muted)' }}
          title="호출 트리 최대 깊이 (1~20) — 높일수록 더 깊은 호출까지 표시. '… 깊이제한' 배지는 이 깊이에서 잘렸다는 표시입니다.">
          깊이
          <input type="number" min={1} max={20} value={depthInput}
            onChange={e => setDepthInput(Math.min(20, Math.max(1, Number(e.target.value) || 1)))}
            style={{ width: 46, padding: '3px 5px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--fg)' }} />
        </label>
        {trees.length > 0 && (
          <button type="button" onClick={toggleAllOpen}
            title={allOpen ? '모든 하위 노드 접기' : '로드된 모든 하위 노드를 한 번에 펼치기'}
            style={{ fontSize: 11, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>
            {allOpen ? '모두 접기' : '모두 펼치기'}
          </button>
        )}
        {loading && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>분석 중…</span>}
        {!loading && data && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            엔진 {st.engine || '?'} · 함수 {st.functions ?? 0} · 엣지 {st.edges ?? 0}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {onOpenFull && (
          <button type="button" onClick={onOpenFull} title="전체 콜트리 뷰(깊이 조절·전체 트리·양방향)로 열기"
            style={{ fontSize: 11, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--accent)', cursor: 'pointer', fontWeight: 600 }}>⤢ 전체 뷰</button>
        )}
        <button type="button" onClick={onClose} title="콜트리 닫기"
          style={{ fontSize: 14, lineHeight: 1, padding: '3px 9px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>✕</button>
      </div>
      <div style={{ padding: '10px 12px', maxHeight: 400, overflowY: 'auto', background: 'var(--bg)' }}>
        {!hasSource ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 2px', lineHeight: 1.5 }}>
            소스가 연결되지 않아(로컬 파일 모드) 콜트리를 만들 수 없습니다 — Jenkins 빌드가 있는 환경에서 시도하세요.
          </div>
        ) : error ? (
          <div style={{ fontSize: 12, color: '#b91c1c', padding: '8px 2px', lineHeight: 1.5 }}>{error}</div>
        ) : (loading && !data) ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 2px' }}>tree-sitter로 호출 트리 분석 중…</div>
        ) : trees.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 2px' }}>
            {reverse ? '이 함수를 호출하는 함수가 없습니다 (진입점·미사용).' : '이 함수가 호출하는 하위 함수가 없습니다 (leaf).'}
          </div>
        ) : (
          <ul style={{ margin: 0, padding: 0 }}>
            {sortedTrees.map((t, i) => (
              <CallTreeNode key={i} node={t} path={`${i}`} expanded={expanded} onToggle={toggle} depth={0} includeExternal={false} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ── 인라인 그래프 프레임 (함수그래프/추적그래프 공용 — 표 행 안에서 기존 그래프 컴포넌트를 감싸 표시) ──
 * 헤더(제목·badge·⤢전체뷰·✕) + maxHeight 스크롤 본문. 자식 그래프 컴포넌트는 seed가 바뀌면
 * 호출부에서 key로 remount하여 재시드한다(그래프 컴포넌트는 initial* 를 useState 1회 시드만 하므로). */
function InlineGraphFrame({ title, badge, onOpenFull, onClose, children }) {
  return (
    <div style={{ marginTop: 12, border: '1px solid var(--accent)', borderRadius: 8, background: 'var(--panel)',
      overflow: 'hidden', boxShadow: '0 2px 10px rgba(0,0,0,0.07)' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, padding: '8px 12px',
        borderBottom: '1px solid var(--border)', background: 'var(--bg-elevated)' }}>
        <span style={{ fontSize: 13, fontWeight: 700 }}>{title}</span>
        {badge && (
          <code style={{ fontSize: 13, fontFamily: 'monospace', fontWeight: 700, color: _STAGE_COLORS.UDS,
            background: 'var(--bg)', padding: '2px 9px', borderRadius: 6, border: '1px solid var(--border)',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 360 }}>{badge}</code>
        )}
        <span style={{ flex: 1 }} />
        {onOpenFull && (
          <button type="button" onClick={onOpenFull} title="전용 탭(더 큰 캔버스)에서 열기"
            style={{ fontSize: 11, padding: '4px 10px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--accent)', cursor: 'pointer', fontWeight: 600 }}>⤢ 전체 뷰</button>
        )}
        <button type="button" onClick={onClose} title="닫기"
          style={{ fontSize: 14, lineHeight: 1, padding: '3px 9px', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>✕</button>
      </div>
      <div style={{ padding: '10px 12px', maxHeight: 460, overflow: 'auto', background: 'var(--bg)' }}>
        {children}
      </div>
    </div>
  );
}

/* ── 요구사항 상하위 추적 그래프 (additive '그래프' 뷰) ──
   요구사항 1개를 선택하면 그 하위 추적(SW: SDS→UDS→STS/SUTS/SITS · 시스템: HSIS·SyTS·SyITS → VectorCAST)을 레벨별 SVG
   노드-엣지 그래프로 보여준다. hiMA UCOneIDTrace(요구사항 ID 의존성 그래프)의 child 방향에
   대응 — hiMA의 MSAGL Sugiyama 대신 레벨이 7컬럼으로 고정이라 컬럼 배치로 단순화(레이아웃 엔진 불필요).
   데이터는 matrix row만으로 완결(백엔드 무변경): _stageMembers(단계 멤버) + _unitTestMap(UDS함수↔
   SUTS단위시험 정확 매핑 엣지). 상위(부모 요구사항)는 row에 구조화 데이터가 없어(설계서 prose에 묻힘)
   이번 범위에서 제외 — 하위 추적에 집중. 모든 시각화는 SVG(innerHTML 없음 → XSS 무관). */
const _STAGE_COLORS = { SyRS: '#475569', SDS: '#0d9488', HSIS: '#0e7490', UDS: '#7c3aed', STS: '#2563eb', SUTS: '#0891b2', SITS: '#db2777', SyTS: '#9333ea', SyITS: '#c026d3', VectorCAST: '#ea580c' };
const _GRAPH = { COL_W: 172, NODE_W: 150, NODE_H: 30, GAP: 9, HEADER_H: 26, PAD: 14, MAX_PER_COL: 40 };

function _reqGraphId(r) {
  return String(r?.requirement_id ?? r?.req_id ?? r?.id ?? '').trim();
}

// 한 요구사항 row → 레벨별 노드 + 엣지(좌표 포함). 순수 함수(렌더 외부 계산).
// FAIL 우선 정렬 키 — 안전관련(FAIL) 시험이 MAX_PER_COL 캡에 silent하게 잘려나가지 않도록
// 캡 적용 전 FAIL을 앞으로 보낸다. 0=FAIL, 1=mapped/unknown, 2=PASS.
function _resultRank(result) {
  const v = (result || '').toLowerCase();
  if (/^(fail|failed|false|0)$/.test(v)) return 0;
  if (/^(pass|passed|true|1)$/.test(v)) return 2;
  return 1;
}

// focusSet(영향도 변경함수 정규화 집합)이 주어지면 UDS 함수/시험 유닛이 변경 영향인지 표시.
// visibleKeys(레벨 필터)가 주어지면 해당 단계만 컬럼으로 그린다(null/빈 배열=전체).
function _buildReqGraph(row, focusSet, visibleKeys, linkTable) {
  const G = _GRAPH;
  const reqId = _reqGraphId(row) || '(이름없음)';
  const reqName = String(row?.requirement_name ?? '').trim();
  // ASIL 추출 연산자는 매트릭스 뷰(CrossMatrixView)와 통일(`||`) — present-but-empty asil에서 분기 방지.
  const asil = String(row?.asil || row?.requirement_asil || row?.ASIL || '').trim().toUpperCase();
  const fset = focusSet instanceof Set && focusSet.size ? focusSet : null;
  const isSafety = asil === 'C' || asil === 'D'; // ISO 26262 최고 등급(시험 경로 강조용)
  // 안전 검증 공백 — 백엔드 _asil_missing_bands(report_gen/trace_link_table.py)와 동일 규칙.
  //   C/D = SUTS·SITS 둘 다 필수(하나라도 0이면 누락), A/B = 시험 밴드 중 1개 이상, QM/미상 = 기대 없음.
  //   레벨 필터와 무관하게 전체 row 기준으로 판정(필터로 시험 단계를 숨겨도 정확).
  // 안전 검증 공백 — 백엔드 link_table.asil_coverage.gaps를 SSOT로 직독(매트릭스 뷰 CrossMatrixView와
  // 동일 출처 → 같은 요구사항에 byte-identical 갭, drift 제거). 백엔드 link_table 부재(구버전/빌드 실패)
  // 시에만 _rowBands(백엔드 build_link_table과 byte-exact 추출) + _asil_missing_bands 규칙으로 폴백 재계산.
  let safetyMissing;
  const _backendGaps = linkTable?.asil_coverage?.gaps;
  if (Array.isArray(_backendGaps)) {
    const g = _backendGaps.find(x => String(x?.target_id ?? '') === reqId);
    safetyMissing = (g && Array.isArray(g.missing)) ? g.missing.slice() : [];
  } else {
    const _safetyBands = _rowBands(row);
    const _bandCount = (key) => (_safetyBands[key] || []).length;
    const _asilRank = { QM: 0, A: 1, B: 2, C: 3, D: 4 }[asil] ?? -1;
    safetyMissing = [];
    if (_asilRank >= 3) { // ASIL C/D — SUTS·SITS 둘 다 필수
      if (_bandCount('SUTS') === 0) safetyMissing.push('SUTS');
      if (_bandCount('SITS') === 0) safetyMissing.push('SITS');
    } else if (_asilRank >= 1) { // ASIL A/B — 시험 밴드 중 1개 이상
      if (!['STS', 'SUTS', 'SITS', 'SyTS', 'SyITS', 'VectorCAST'].some(b => _bandCount(b) > 0)) safetyMissing.push('ANY_TEST');
    }
  }
  const safetyGap = safetyMissing.length > 0;
  // 레벨 필터: visibleKeys에 든 단계만 컬럼화.
  const stages = (Array.isArray(visibleKeys) && visibleKeys.length)
    ? TREE_STAGES.filter(s => visibleKeys.includes(s.key)) : TREE_STAGES;

  // 단계별 멤버(캡 적용 — 시험 수십 개 컬럼이 무한정 길어지는 것 방지)
  const columns = stages.map((s, ci) => {
    const { type, items } = _stageMembers(row, s.key);
    let all = (Array.isArray(items) ? items : []).map((it, i) => {
      const label = type === 'tests' ? _testId(it) : String(it ?? '').trim();
      if (!label) return null;
      const unit = type === 'tests' ? String(it?.unit ?? '') : '';
      // 영향도 연동: UDS 함수명 또는 시험 유닛명이 변경함수 집합에 들면 강조
      const impacted = !!(fset && (
        (s.key === 'UDS' && fset.has(_normFn(label))) ||
        (type === 'tests' && unit && fset.has(_normFn(unit)))
      ));
      return {
        // id에 reqId prefix — 요구사항 간 위치기반 id 충돌(selNode 오매칭) 원천 차단
        id: `${reqId}::${s.key}:${i}`, label, stage: s.key, kind: s.kind, type,
        result: type === 'tests' ? String(it?.result ?? '') : '',
        unit, source: type === 'tests' ? String(it?.source ?? '') : '',
        confidence: type === 'tests' ? String(it?.confidence ?? '') : '',
        impacted,
      };
    }).filter(Boolean);
    // 시험 컬럼이 캡을 넘치면 FAIL 우선 정렬 후 자른다(안전 시험 우선 노출). 캡 이내면 원본 순서 유지.
    if (type === 'tests' && all.length > G.MAX_PER_COL) {
      all = all.map((m, idx) => ({ m, idx }))
        .sort((a, b) => (_resultRank(a.m.result) - _resultRank(b.m.result)) || (a.idx - b.idx))
        .map(o => o.m);
    }
    const shown = all.slice(0, G.MAX_PER_COL);
    const hiddenFail = all.slice(G.MAX_PER_COL).filter(m => _resultRank(m.result) === 0).length;
    return { stage: s.key, label: s.label, kind: s.kind, colIndex: ci + 1, members: shown, hidden: all.length - shown.length, hiddenFail };
  });

  // 좌표 계산
  const maxRows = Math.max(1, ...columns.map(c => c.members.length || 1));
  const bodyH = maxRows * (G.NODE_H + G.GAP);
  const height = G.HEADER_H + bodyH + G.PAD * 2;
  const width = (stages.length + 1) * G.COL_W;

  const nodeXY = {};
  const rootY = G.HEADER_H + G.PAD + Math.max(0, (bodyH - (G.NODE_H + G.GAP)) / 2);
  nodeXY['__root__'] = { x: G.PAD, y: rootY };
  for (const col of columns) {
    const x = col.colIndex * G.COL_W + G.PAD;
    col.members.forEach((m, mi) => {
      const y = G.HEADER_H + G.PAD + mi * (G.NODE_H + G.GAP);
      m.x = x; m.y = y;
      nodeXY[m.id] = { x, y };
    });
  }

  // 엣지: 요구사항(root) → 각 단계 멤버 (row 데이터는 모두 요구사항 기준이므로 SRS 직속).
  // root 출발점이 한 점에 완전 중첩돼 hairball이 되던 것을 fromFrac으로 root 노드 우변 높이에
  // 펼쳐(각 엣지 출발 y 분산) 초기 밀집을 완화한다.
  const edges = [];
  const reqEdges = [];
  for (const col of columns) {
    for (const m of col.members) {
      // 안전 체인: ASIL C/D 요구사항이 시험 단계로 추적되는 경로를 ASIL 색으로 강조(hiMA FS-FS Navy 대응).
      reqEdges.push({ from: '__root__', to: m.id, color: _STAGE_COLORS[col.stage] || '#9ca3af', kind: 'req', safety: isSafety && col.kind === 'test' });
    }
  }
  reqEdges.forEach((e, i) => { e.fromFrac = (i + 0.5) / reqEdges.length; });
  edges.push(...reqEdges);
  // UDS 함수 ↔ SUTS 단위시험 정확 매핑(row에서 추출 가능한 유일한 단계간 엣지)
  const udsCol = columns.find(c => c.stage === 'UDS');
  const sutsCol = columns.find(c => c.stage === 'SUTS');
  if (udsCol && sutsCol && sutsCol.members.length) {
    const utMap = _unitTestMap(row);
    for (const u of udsCol.members) {
      const key = _normFn(u.label);
      if (!key || !utMap.has(key)) continue;
      for (const s of sutsCol.members) {
        if (_normFn(s.unit) === key) edges.push({ from: u.id, to: s.id, color: '#2563eb', kind: 'unit' });
      }
    }
  }

  // 분리된 인터페이스 함수(추적 정화) — 그래프 노드로는 안 그려 정화를 유지하되, 데이터 존재는
  // 범례/패널로 정직하게 노출(함수가 UI에서 완전 소실되지 않도록).
  const sdsFunctions = (Array.isArray(row?.sds_functions) ? row.sds_functions : []).map(s => String(s).trim()).filter(Boolean);
  // SyRS 상위 추적(배지) — 그래프 좌표 무변경, root 위 배지로 노출(SR→SyRS→SwRS 체인). 풀 부모 컬럼은 후속.
  const syrsParents = (Array.isArray(row?.syrs_parents) ? row.syrs_parents : []).map(s => String(s).trim()).filter(Boolean);
  return { reqId, reqName, asil, isSafety, safetyGap, safetyMissing, sdsFunctions, syrsParents, columns, edges, width, height, nodeXY, rootY };
}

function _bez(x1, y1, x2, y2) {
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
}

// 단계 → 노드 모양(hiMA UCOneIDTrace getNodeShape 대응): SwDS=House, SwUDS=InvHouse,
// SwTS/TR=Ellipse, SwUTS/UTR=Diamond, SwITS/ITR=Octagon, 요구사항=Box. VectorCAST는 hiMA에
// 없으나 시험 실행결과라 Ellipse로 둔다(SUTS Diamond와 구분).
const _NODE_SHAPE = { SDS: 'house', HSIS: 'house', UDS: 'invhouse', STS: 'ellipse', SUTS: 'diamond', SITS: 'octagon', SyTS: 'ellipse', SyITS: 'octagon', VectorCAST: 'ellipse' };

function _shapePath(shape, W, H) {
  if (shape === 'house') return `M0,9 L${W / 2},0 L${W},9 L${W},${H} L0,${H} Z`;        // 집(△지붕)
  if (shape === 'invhouse') return `M0,0 L${W},0 L${W},${H - 9} L${W / 2},${H} L0,${H - 9} Z`; // 역집
  if (shape === 'diamond') return `M12,0 L${W - 12},0 L${W},${H / 2} L${W - 12},${H} L12,${H} L0,${H / 2} Z`; // 늘인 ◇
  if (shape === 'octagon') return `M9,0 L${W - 9},0 L${W},9 L${W},${H - 9} L${W - 9},${H} L9,${H} L0,${H - 9} L0,9 Z`; // 8각
  return `M0,0 L${W},0 L${W},${H} L0,${H} Z`; // box fallback
}

// 내보내기용 SVG 직렬화 — CSS 변수 fill을 현재 테마 computed 값으로 인라인(다운로드 SVG/PNG는
// CSS 컨텍스트 밖이라 var() 미해석). 우리 SVG의 var fill 3종만 치환.
function _graphSvgString(svgEl) {
  const clone = svgEl.cloneNode(true);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  const cs = getComputedStyle(svgEl);
  const fg = (cs.getPropertyValue('--fg') || '#111827').trim() || '#111827';
  const bgEl = (cs.getPropertyValue('--bg-elevated') || '#ffffff').trim() || '#ffffff';
  const muted = (cs.getPropertyValue('--text-muted') || '#6b7280').trim() || '#6b7280';
  const bg = (cs.getPropertyValue('--bg') || '#ffffff').trim() || '#ffffff';
  // 노드 강조 dim(노드/placeholder <g>의 opacity)이 다운로드본에 박히지 않게 복원 — 선택 상태에서
  // 내보내도 워시아웃 없이 전체가 또렷. 엣지는 <path opacity>라 g[opacity] 선택에서 제외(시각계층 보존).
  clone.querySelectorAll('g[opacity]').forEach(g => g.setAttribute('opacity', '1'));
  // 다운로드 SVG는 컨테이너 var(--bg) 밖이라 투명 → 다크테마 헤더/placeholder가 뷰어 흰배경에 묻힘.
  // PNG(canvas fillRect)와 정합하도록 불투명 배경 rect를 최하단에 삽입.
  const bgRect = clone.ownerDocument.createElementNS('http://www.w3.org/2000/svg', 'rect');
  bgRect.setAttribute('width', '100%');
  bgRect.setAttribute('height', '100%');
  bgRect.setAttribute('fill', bg);
  clone.insertBefore(bgRect, clone.firstChild);
  let s = new XMLSerializer().serializeToString(clone);
  s = s.split('var(--bg-elevated, #ffffff)').join(bgEl)
    .split('var(--fg)').join(fg)
    .split('var(--text-muted)').join(muted);
  return s;
}

function _downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

// 그래프 노드 1개 (root/단계 공용). label은 truncate, 전체는 <title> 툴팁.
// active=hover/선택 강조(dim), kbFocused=키보드 포커스 링(dim과 분리), node.impacted=영향도 변경함수.
function ReqGraphNode({ node, color, active, kbFocused, onClick, onHover, onFocus, onBlur }) {
  const G = _GRAPH;
  const W = G.NODE_W, H = G.NODE_H;
  const label = String(node.label || '');
  const shown = label.length > 20 ? label.slice(0, 19) + '…' : label;
  const impacted = !!node.impacted;
  // 단계별 모양(hiMA 대응). root/요구사항은 box.
  const shape = node.isRoot ? 'box' : (_NODE_SHAPE[node.stage] || 'box');
  const stroke = impacted ? '#b45309' : color;
  const sw = impacted ? 3 : (node.isRoot ? 2.5 : 1.5);
  const fillStyle = { fill: 'var(--bg-elevated, #ffffff)' };
  // 텍스트 y — house는 지붕만큼 아래, invhouse는 위쪽 본체에.
  const textY = shape === 'house' ? H / 2 + 8 : shape === 'invhouse' ? H / 2 - 1 : H / 2 + 4;
  const body = shape === 'box'
    ? <rect width={W} height={H} rx={6} style={fillStyle} stroke={stroke} strokeWidth={sw} />
    : shape === 'ellipse'
      ? <rect width={W} height={H} rx={H / 2} style={fillStyle} stroke={stroke} strokeWidth={sw} />
      : <path d={_shapePath(shape, W, H)} style={fillStyle} stroke={stroke} strokeWidth={sw} strokeLinejoin="round" />;
  return (
    <g transform={`translate(${node.x},${node.y})`} style={{ cursor: 'pointer' }} opacity={active ? 1 : 0.28}
      role="button" tabIndex={0} aria-label={impacted ? `${label} (변경 영향 함수)` : label}
      onClick={onClick}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick?.(); } }}
      onMouseEnter={() => onHover?.(node.id)} onMouseLeave={() => onHover?.(null)}
      onFocus={() => onFocus?.(node.id)} onBlur={() => onBlur?.()}>
      <title>{impacted ? `${label} — 변경 영향 함수(영향도 연동)` : label}</title>
      {kbFocused && <rect x={-3} y={-3} width={W + 6} height={H + 6} rx={8} fill="none" stroke="#2563eb" strokeWidth={2} strokeDasharray="3 2" />}
      {body}
      {impacted && <circle cx={W - 9} cy={9} r={4} fill="#b45309" />}
      <text x={12} y={textY} fontSize={11} fontWeight={node.isRoot || impacted ? 700 : 500} clipPath="url(#rg-node-clip)" style={{ fill: 'var(--fg)' }}>{shown}</text>
    </g>
  );
}

function TraceReqGraphView({ rows, focusFunctions = null, linkTable = null, initialReqId = '', embedded = false }) {
  const list = useMemo(() => (Array.isArray(rows) ? rows.filter(r => _reqGraphId(r)) : []), [rows]);
  // 표 행에서 진입 시 그 요구사항으로 시작(인라인은 key로 remount되므로 초기값 시드로 충분). 검색창으로 변경 가능.
  const [selId, setSelId] = useState(initialReqId || '');
  const [selNode, setSelNode] = useState(null);
  const [hoverId, setHoverId] = useState(null);
  const [focusId, setFocusId] = useState(null); // 키보드 포커스(강조 dim과 분리)
  const [levelFilter, setLevelFilter] = useState('all'); // 'all' | 'design' | 'test' (hiMA DisplayLevel 대응)
  const svgRef = useRef(null); // 내보내기(SVG/PNG)용 SVG 참조
  const [showSdsFns, setShowSdsFns] = useState(false); // SDS 인터페이스 함수 펼침(추적 정화 분리분)

  const visibleKeys = useMemo(() => {
    if (levelFilter === 'design') return ['SDS', 'HSIS', 'UDS'];
    if (levelFilter === 'test') return ['STS', 'SUTS', 'SITS', 'SyTS', 'SyITS', 'VectorCAST'];
    return null; // 전체
  }, [levelFilter]);

  // 영향도 연동 변경함수 집합(정규화) — 그래프 안에서 변경 영향 UDS/시험 노드를 강조.
  const focusSet = useMemo(() => {
    const arr = Array.isArray(focusFunctions) ? focusFunctions : [];
    return new Set(arr.map(f => _normFn(f)).filter(Boolean));
  }, [focusFunctions]);

  // 선택 row (입력 없으면 첫 항목 자동)
  const selectedRow = useMemo(() => {
    if (!list.length) return null;
    if (!selId) return list[0];
    return list.find(r => _reqGraphId(r) === selId) || null;
  }, [list, selId]);

  const graph = useMemo(() => (selectedRow ? _buildReqGraph(selectedRow, focusSet, visibleKeys, linkTable) : null), [selectedRow, focusSet, visibleKeys, linkTable]);

  // 표시 그래프 교체 시: 선택 노드가 새 graph에 여전히 존재하면 유지(레벨필터 좁히기에도 상세 보존),
  // 없으면 리셋(selId 변경·필터로 단계 제거 시 stale selNode/유령 dimming 차단). hover/focus는 transient라 항상 리셋.
  useEffect(() => {
    // 노드 생존 시 보존하되, root('__root__')는 nodeXY에 항상 있으므로 요구사항 동일(label===reqId)일 때만
    // 보존 — 안 그러면 요구사항 전환 후에도 root 상세패널이 옛 reqId를 영구 표시(stale).
    setSelNode(prev => (prev && graph && graph.nodeXY[prev.id] && (!prev.isRoot || prev.label === graph.reqId)) ? prev : null);
    setHoverId(null); setFocusId(null);
  }, [graph]);

  // hover/선택 강조는 키보드 focus와 분리(focusId는 dim 트리거 안 함 — Tab 순회 깜빡임 방지).
  // selValid: graph 교체 직후 useEffect 리셋 전 1프레임에 selNode가 stale일 수 있어, 렌더 중 즉시
  // '현재 graph에 그 노드가 있을 때만' 강조를 채택 → 전환 프레임 전체-dim 깜빡임 방지(derive-during-render).
  const selValid = selNode && graph && graph.nodeXY[selNode.id];
  const activeNodeId = hoverId || (selValid ? selNode.id : null);
  // 활성 노드와 엣지로 직접 연결된 이웃 노드 집합 — UDS↔SUTS 매핑 등 인접 노드도 함께 강조.
  const neighborSet = useMemo(() => {
    const s = new Set();
    if (activeNodeId && graph) {
      for (const e of graph.edges) {
        if (e.from === activeNodeId) s.add(e.to);
        else if (e.to === activeNodeId) s.add(e.from);
      }
    }
    return s;
  }, [graph, activeNodeId]);

  if (!list.length) {
    return <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 12 }}>표시할 요구사항이 없습니다.</div>;
  }

  const G = _GRAPH;
  // graph는 selId 비매칭 시 null일 수 있다(아래 JSX는 {graph && …}로 가드) — 파생 const도 null-safe.
  const headerLabels = ['요구사항', ...(graph ? graph.columns.map(c => c.label) : [])];
  const isNodeActive = (id) => !activeNodeId || id === activeNodeId || neighborSet.has(id);
  const isEdgeActive = (e) => !activeNodeId || e.from === activeNodeId || e.to === activeNodeId;
  const totalHiddenFail = graph ? graph.columns.reduce((n, c) => n + (c.hiddenFail || 0), 0) : 0;
  const impactedCount = graph ? graph.columns.reduce((n, c) => n + c.members.filter(m => m.impacted).length, 0) : 0;

  // 내보내기(hiMA SaveInVectorFormat/SaveAsImage 대응) — 클라이언트에서 SVG 직렬화/PNG 래스터화.
  const exportSvg = () => {
    if (!svgRef.current || !graph) return;
    const s = _graphSvgString(svgRef.current);
    _downloadBlob(new Blob([s], { type: 'image/svg+xml;charset=utf-8' }), `${graph.reqId}_trace_graph.svg`);
  };
  const exportPng = () => {
    if (!svgRef.current || !graph) return;
    const s = _graphSvgString(svgRef.current);
    const bg = (getComputedStyle(svgRef.current).getPropertyValue('--bg') || '#ffffff').trim() || '#ffffff';
    const w = graph.width, h = graph.height, scale = 2;
    const img = new Image();
    const url = URL.createObjectURL(new Blob([s], { type: 'image/svg+xml;charset=utf-8' }));
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = w * scale; canvas.height = h * scale;
      const ctx = canvas.getContext('2d');
      ctx.scale(scale, scale);
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob(b => { if (b) _downloadBlob(b, `${graph.reqId}_trace_graph.png`); }, 'image/png');
    };
    img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
  };

  return (
    <div>
      {/* 요구사항 선택 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        {/* 인라인(embedded)에선 행 버튼이 선택자이므로 내부 요구사항 선택창 숨김 — 하이라이트 어긋남·DOM id 중복 제거 */}
        {!embedded && (<>
          <label htmlFor="req-graph-input" style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg)' }}>요구사항</label>
          <input id="req-graph-input" list="req-graph-ids" value={selId} onChange={e => setSelId(e.target.value)}
            placeholder={`요구사항 ID 선택/검색 (${list.length}건, 미입력 시 첫 항목)`}
            style={{ flex: '1 1 280px', maxWidth: 440, padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }} />
          <datalist id="req-graph-ids">
            {list.slice(0, 1000).map((r, i) => {
              const id = _reqGraphId(r);
              return <option key={i} value={id}>{r.requirement_name ? `${id} — ${r.requirement_name}` : id}</option>;
            })}
          </datalist>
          {selId && !selectedRow && <span style={{ fontSize: 11, color: '#d97706' }}>일치하는 요구사항 없음</span>}
        </>)}
        <div role="group" aria-label="단계 필터" style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', marginLeft: 'auto' }}>
          {[['all', '전체'], ['design', '설계'], ['test', '시험']].map(([k, lbl], i) => (
            <button key={k} type="button" onClick={() => setLevelFilter(k)} aria-pressed={levelFilter === k}
              title={k === 'design' ? 'SDS·HSIS·UDS만' : k === 'test' ? 'STS·SUTS·SITS·SyTS·SyITS·VectorCAST만' : '전체 단계'}
              style={{ padding: '5px 10px', fontSize: 11, border: 'none', borderLeft: i ? '1px solid var(--border)' : 'none', cursor: 'pointer',
                background: levelFilter === k ? 'var(--accent)' : 'var(--bg)', color: levelFilter === k ? '#fff' : 'var(--fg)', fontWeight: levelFilter === k ? 700 : 400 }}>
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {graph && (
        <>
          {/* 요약 + 범례 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, alignItems: 'center' }}>
            <span><strong style={{ color: 'var(--fg)' }}>{graph.reqId}</strong>{graph.reqName ? ` — ${graph.reqName}` : ''}</span>
            {graph.asil && <span style={{ padding: '1px 7px', borderRadius: 10, background: (_ASIL_COLORS[graph.asil] || '#6b7280'), color: '#fff', fontWeight: 700 }}>ASIL {graph.asil}</span>}
            {graph.syrsParents && graph.syrsParents.length > 0 && (
              <span title={`상위 시스템 요구(SyRS) — SR→SyRS→SwRS 체인: ${graph.syrsParents.join(', ')}`}
                style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 12, border: `1px solid ${_STAGE_COLORS.UDS}`, color: _STAGE_COLORS.UDS, fontWeight: 600 }}>
                ↑ 상위요구 {graph.syrsParents.length}: {graph.syrsParents.slice(0, 4).join(', ')}{graph.syrsParents.length > 4 ? '…' : ''}
              </span>
            )}
            {graph.columns.map(c => (
              <span key={c.stage} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 9, height: 9, borderRadius: 2, background: _STAGE_COLORS[c.stage], display: 'inline-block' }} />
                {c.label} {c.members.length}{c.hidden > 0 ? `(+${c.hidden})` : ''}
              </span>
            ))}
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 14, height: 0, borderTop: '2px dashed #2563eb', display: 'inline-block' }} />UDS↔SUTS 단위시험 매핑
            </span>
            <span style={{ opacity: 0.65 }} title="그래프/트리는 VectorCAST 컬럼에 미분류 소스 시험도 포함하나, 매트릭스 뷰는 엄격히 source='VectorCAST'만 셉니다(백엔드 link_table과 동일).">
              ⓘ VectorCAST=실행시험+미분류 소스
            </span>
            {impactedCount > 0 && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#b45309', fontWeight: 600 }}
                title="영향도 분석에서 변경된 함수에 해당하는 UDS/시험 노드 (주황 테두리·● 표시)">
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#b45309', display: 'inline-block' }} />변경 영향 {impactedCount}
              </span>
            )}
            {totalHiddenFail > 0 && (
              <span style={{ color: '#dc2626', fontWeight: 700 }}
                title={`시험 컬럼 캡(${G.MAX_PER_COL})을 초과해 표시되지 않은 FAIL 시험이 있습니다. FAIL 우선 정렬로 대부분 노출되나, FAIL이 캡보다 많은 예외입니다.`}>
                ⚠ 미표시 FAIL {totalHiddenFail}
              </span>
            )}
            {graph.isSafety && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                title="ASIL C/D 요구사항이 시험 단계로 추적되는 경로(안전 검증 체인)를 ASIL 색·굵게로 강조합니다.">
                <span style={{ width: 14, height: 0, borderTop: `2px solid ${_ASIL_COLORS[graph.asil] || '#dc2626'}`, display: 'inline-block' }} />안전 검증 경로
              </span>
            )}
            {graph.safetyGap && (
              <span style={{ color: '#dc2626', fontWeight: 700 }}
                title={`ISO 26262: ASIL ${graph.asil} 요구사항의 기대 시험이 누락됐습니다(백엔드 asil_coverage와 동일 규칙 — C/D=SUTS·SITS 필수, A/B=시험 1개 이상).`}>
                ⚠ 안전 검증 공백: {graph.safetyMissing.includes('ANY_TEST') ? '시험 없음' : `${graph.safetyMissing.join('·')} 누락`}
              </span>
            )}
            <span style={{ opacity: 0.6 }} title="hiMA UCOneIDTrace 표기 대응 — 설계=집(△지붕)/단위설계=역집/시험스펙=타원/단위시험=◇/통합시험=8각/요구사항=□">
              모양: 설계▭집·단위설계▽·시험◯◇⯃
            </span>
            {graph.sdsFunctions.length > 0 && (
              <button type="button" onClick={() => setShowSdsFns(v => !v)} aria-expanded={showSdsFns}
                title="SDS 인터페이스 함수 — 추적 정화로 설계 컴포넌트와 분리(SDS 밴드 집계 제외). 단위시험(SUTS)·VectorCAST 추적의 근거. 클릭해 목록 보기."
                style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 12,
                  background: showSdsFns ? 'var(--accent)' : 'var(--bg)', color: showSdsFns ? '#fff' : 'var(--fg)', cursor: 'pointer' }}>
                함수 {graph.sdsFunctions.length} {showSdsFns ? '▲' : '▼'}
              </button>
            )}
            <div style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
              <button type="button" onClick={exportSvg} title="그래프를 SVG(벡터)로 내보내기 (hiMA SaveInVectorFormat 대응)"
                style={{ padding: '4px 9px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 5, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>SVG ↓</button>
              <button type="button" onClick={exportPng} title="그래프를 PNG(이미지)로 내보내기 (hiMA SaveAsImage 대응)"
                style={{ padding: '4px 9px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 5, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>PNG ↓</button>
            </div>
          </div>

          {/* SDS 인터페이스 함수 펼침 패널(추적 정화로 분리된 함수 — 기본 접힘, 그래프 노드 재팽창 방지) */}
          {showSdsFns && graph.sdsFunctions.length > 0 && (
            <div style={{ marginBottom: 8, padding: 10, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--panel, #f9fafb)', maxHeight: 170, overflow: 'auto' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
                SDS 인터페이스 함수 {graph.sdsFunctions.length}개 — 설계 컴포넌트의 멤버 함수(SDS 밴드 집계엔 미포함, SUTS/VectorCAST 단위시험 추적 근거)
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {graph.sdsFunctions.slice(0, 500).map((fn, i) => (
                  <span key={i} style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--fg)' }}>{fn}</span>
                ))}
                {graph.sdsFunctions.length > 500 && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>… +{graph.sdsFunctions.length - 500}</span>}
              </div>
            </div>
          )}

          {/* SVG 그래프 */}
          <div style={{ overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg)', maxHeight: 580 }}>
            <svg ref={svgRef} width={graph.width} height={graph.height} style={{ display: 'block', minWidth: '100%' }} role="group" aria-label={`${graph.reqId} 하위 추적 그래프`}>
              <defs>
                {/* 엣지 방향 화살표(타겟 노드 끝). userSpaceOnUse로 strokeWidth와 무관하게 일정 크기. */}
                <marker id="rg-arrow" markerWidth={7} markerHeight={7} refX={6} refY={2.5} orient="auto" markerUnits="userSpaceOnUse">
                  <path d="M0,0 L6,2.5 L0,5 Z" fill="#94a3b8" />
                </marker>
                {/* 노드 라벨 클립 — 문자수 truncate가 CJK(한글 컴포넌트명 등)에서 박스를 넘어
                    이웃 컬럼을 침범하던 것을 박스 내로 가둠. userSpaceOnUse라 g translate 로컬 좌표로 재사용. */}
                <clipPath id="rg-node-clip">
                  <rect x={0} y={0} width={G.NODE_W} height={G.NODE_H} rx={6} />
                </clipPath>
              </defs>
              {/* 컬럼 헤더 */}
              {headerLabels.map((h, ci) => (
                <text key={ci} x={ci * G.COL_W + G.PAD} y={16} fontSize={11} fontWeight={700} style={{ fill: 'var(--text-muted)' }}>{h}</text>
              ))}
              {/* 엣지 (노드보다 먼저 그려 뒤에 깔림) */}
              {graph.edges.map((e, i) => {
                const a = graph.nodeXY[e.from], b = graph.nodeXY[e.to];
                if (!a || !b) return null;
                const x1 = a.x + G.NODE_W;
                const y1 = a.y + (e.fromFrac != null ? e.fromFrac * G.NODE_H : G.NODE_H / 2);
                const x2 = b.x, y2 = b.y + G.NODE_H / 2;
                const active = isEdgeActive(e);
                // 안전 체인(ASIL C/D 요구사항→시험 단계)은 ASIL 색·굵게로 부각(hiMA FS-FS Navy 대응).
                const stroke = e.kind === 'unit' ? '#2563eb' : (e.safety ? (_ASIL_COLORS[graph.asil] || e.color) : e.color);
                const sw = e.kind === 'unit' ? 2 : (e.safety ? 2 : 1.2);
                // 초기(미선택) 상태에선 req 엣지를 옅게 깔아 hairball 밀도를 낮추되, 안전/unit 엣지는 진하게.
                const idleOp = e.kind === 'unit' ? 0.5 : (e.safety ? 0.45 : 0.16);
                const op = active
                  ? (e.kind === 'unit' ? 0.9 : (e.safety ? 0.85 : 0.55))
                  : (activeNodeId ? 0.06 : idleOp);
                return <path key={i} d={_bez(x1, y1, x2, y2)} fill="none"
                  stroke={stroke} strokeWidth={sw}
                  strokeDasharray={e.kind === 'unit' ? '4 2' : undefined}
                  markerEnd="url(#rg-arrow)" opacity={op} />;
              })}
              {/* root(요구사항) 노드 */}
              <ReqGraphNode node={{ id: '__root__', label: graph.reqId, x: G.PAD, y: graph.rootY, isRoot: true }}
                color={_ASIL_COLORS[graph.asil] || '#374151'}
                active={isNodeActive('__root__')} kbFocused={focusId === '__root__'}
                onClick={() => setSelNode({ id: '__root__', label: graph.reqId, stage: '요구사항', asil: graph.asil, isRoot: true })}
                onHover={setHoverId} onFocus={setFocusId} onBlur={() => setFocusId(null)} />
              {/* 단계 노드 */}
              {graph.columns.map(col => col.members.map(m => (
                <ReqGraphNode key={m.id} node={m} color={_STAGE_COLORS[m.stage] || '#9ca3af'}
                  active={isNodeActive(m.id)} kbFocused={focusId === m.id}
                  onClick={() => setSelNode(m)} onHover={setHoverId} onFocus={setFocusId} onBlur={() => setFocusId(null)} />
              )))}
              {/* 끊긴 단계 placeholder('없음') */}
              {graph.columns.filter(c => c.members.length === 0).map(c => (
                <g key={`empty-${c.stage}`} opacity={activeNodeId ? 0.28 : 1} transform={`translate(${c.colIndex * G.COL_W + G.PAD},${G.HEADER_H + G.PAD})`}>
                  <rect width={G.NODE_W} height={G.NODE_H} rx={5} fill="none" stroke="#d1d5db" strokeDasharray="4 3" />
                  <text x={G.NODE_W / 2} y={G.NODE_H / 2 + 4} fontSize={10} textAnchor="middle" style={{ fill: '#9ca3af' }}>없음</text>
                </g>
              ))}
            </svg>
          </div>

          {/* 노드 상세 */}
          {selNode && (
            <div style={{ marginTop: 10, padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--panel, #f9fafb)', fontSize: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <strong style={{ color: 'var(--fg)', wordBreak: 'break-all' }}>{selNode.label}</strong>
                <button type="button" onClick={() => setSelNode(null)} style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 16, lineHeight: 1 }} aria-label="닫기">×</button>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, color: 'var(--text-muted)' }}>
                <span>단계 <strong style={{ color: selNode.isRoot ? 'var(--fg)' : (_STAGE_COLORS[selNode.stage] || 'var(--fg)') }}>{selNode.isRoot ? '요구사항' : selNode.stage}</strong></span>
                {selNode.isRoot && selNode.asil && <span>ASIL <strong>{selNode.asil}</strong></span>}
                {selNode.source && <span>소스 <strong>{selNode.source}</strong></span>}
                {selNode.unit && <span>유닛 <strong>{selNode.unit}</strong></span>}
                {selNode.result && <span>결과 <strong style={{ color: _testResultColor(selNode.result) }}>{selNode.result}</strong></span>}
                {selNode.confidence && <span>신뢰 <strong>{CONFIDENCE_LABELS[selNode.confidence] || selNode.confidence}</strong></span>}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* ── 함수중심 V-model 트레이스 그래프 (viewMode='funcgraph') ──────────────────────
   요구사항 그래프(TraceReqGraphView)의 역(逆). root=함수(UDS). 그 함수가 source_ids로
   구현한 요구사항/설계(SDS, 요구사항 경유)와, 그 함수 직접 단위시험(SUTS unit==함수)·
   VectorCAST 실행결과(subprogram==함수, PASS/FAIL)를 방사형으로. hiMA UCOneIDTrace의
   '함수 ID' 추적에 대응하나, 우리만의 단위시험 코드연결·VectorCAST PASS/FAIL을 노드로 노출.
   ── function-specific(SUTS·VectorCAST: 이 함수 직접) vs requirement-level(요구·설계·STS·SITS:
   함수가 구현한 요구사항 경유)을 색·범례로 구분. MC/DC 등 커버리지%는 클라 데이터에 없어 표기 안 함. */
const _FUNC_STAGES = [
  { key: 'REQ',  label: '요구사항',        kind: 'req' },
  { key: 'SDS',  label: '설계(SDS)',       kind: 'design' },
  { key: 'STS',  label: 'STS',            kind: 'test' },
  { key: 'SUTS', label: '단위시험(SUTS)',  kind: 'test' },
  { key: 'SITS', label: 'SITS',           kind: 'test' },
  // 시스템 레벨 시험(SW V-model 상단) — SITS와 동일 성격(요구사항 경유), 색만 시스템 보라/마젠타로 구분.
  { key: 'SyTS', label: 'SyTS',           kind: 'test' },
  { key: 'SyITS', label: 'SyITS',          kind: 'test' },
  { key: 'VectorCAST', label: 'VectorCAST', kind: 'test' },
];
// REQ 컬럼 색(요구사항=중립 슬레이트). 나머지 단계는 _STAGE_COLORS 재사용.
const _FUNC_STAGE_COLORS = { REQ: '#475569', SDS: _STAGE_COLORS.SDS, STS: _STAGE_COLORS.STS, SUTS: _STAGE_COLORS.SUTS, SITS: _STAGE_COLORS.SITS, SyTS: _STAGE_COLORS.SyTS, SyITS: _STAGE_COLORS.SyITS, VectorCAST: _STAGE_COLORS.VectorCAST };
const _FN_ASIL_RANK = { QM: 0, A: 1, B: 2, C: 3, D: 4 };
// 선행 언더스코어 bridge — '_entrypoint'(UDS) vs 'entrypoint'(SUTS unit) 거짓 공백 방지(백엔드 _sds_comp_key 대응).
function _looseFn(x) { return _normFn(x).replace(/^_+/, ''); }
// ASIL 결합 토큰('A, B' · 'C/D')에서 최고 등급(백엔드 _asil_max_of 대칭). 단일 토큰만 키였던 과소평가 방어.
function _asilMaxRank(raw) {
  let rank = -1, asil = '';
  for (const t of String(raw || '').toUpperCase().split(/[,/\s]+/).filter(Boolean)) {
    const rk = _FN_ASIL_RANK[t];
    if (rk != null && rk > rank) { rank = rk; asil = t; }
  }
  return { rank, asil };
}

// 전체 행의 UDS 함수 인벤토리(고유) — 피커용. {norm, display}.
function _funcInventory(rows) {
  const seen = new Map();
  for (const r of (Array.isArray(rows) ? rows : [])) {
    for (const s of (Array.isArray(r?.source_ids) ? r.source_ids : [])) {
      const disp = String(s ?? '').trim();
      const norm = _normFn(disp);
      if (!norm || seen.has(norm)) continue;
      seen.set(norm, disp);
    }
  }
  return [...seen.entries()].map(([norm, display]) => ({ norm, display })).sort((a, b) => a.display.localeCompare(b.display));
}

function _buildFuncGraph(funcDisplay, rows, focusSet, visibleKeys) {
  const G = _GRAPH;
  const nf = _normFn(funcDisplay);      // 노드 id prefix·자기강조용(엄격)
  const lf = _looseFn(funcDisplay);     // 크로스밴드 매칭용(선행 _ bridge)
  const fset = focusSet instanceof Set && focusSet.size ? focusSet : null;
  const impactedSelf = !!(fset && (fset.has(nf) || [...fset].some(f => _looseFn(f) === lf)));
  // 이 함수를 source_ids(UDS)에 가진 요구사항 = 함수가 구현한 요구사항.
  const implRows = (Array.isArray(rows) ? rows : []).filter(r =>
    (Array.isArray(r?.source_ids) ? r.source_ids : []).some(s => _looseFn(s) === lf));
  // 함수 ASIL = 구현 요구사항들의 최고 등급(결합 토큰 'A, B'도 split-max).
  let asilRank = -1, asil = '';
  for (const r of implRows) {
    const { rank, asil: a } = _asilMaxRank(r?.asil || r?.requirement_asil || r?.ASIL);
    if (rank > asilRank) { asilRank = rank; asil = a; }
  }
  const isSafety = asilRank >= 3; // ASIL C/D

  // SwUFn-키 프로젝트 bridge: VectorCAST subprogram이 함수명이 아니라 SwUFn ID인 산출물(KJPDS02 등)에서
  // 함수↔VectorCAST를 잇기 위해, 이 함수의 SUTS 시험케이스(SwUTC_SwUFn_####)에서 SwUFn ID를 유도한다.
  const swufnSet = new Set();
  const SWUFN_RE = /sw_?[ui]_?fn_?\d+/ig; // 백엔드 _SWUFN_RE(Sw[UI]Fn) 대칭 — 단위(U)·통합(I) 모두
  for (const r of implRows) {
    for (const t of _stageMembers(r, 'SUTS').items) {
      if (_looseFn(t?.unit) !== lf && _looseFn(t?.subprogram) !== lf) continue;
      const mm = String(t?.testcase ?? t?.id ?? '').match(SWUFN_RE);
      if (mm) mm.forEach(x => swufnSet.add(_normFn(x)));
    }
  }
  // 함수 직접 시험 매칭: 함수명(loose) 일치 OR SwUFn ID bridge 일치(SwUFn-키 vcast).
  const matchesFn = (t) => {
    if (_looseFn(t?.subprogram) === lf || _looseFn(t?.unit) === lf) return true;
    if (swufnSet.size) {
      const cand = _normFn(t?.subprogram) || _normFn(t?.testcase);
      if (cand && swufnSet.has(cand)) return true;
    }
    return false;
  };

  // 요구사항·설계 멤버(고유) — REQ는 개별 ASIL/명 보유(mixed-criticality 추적 손실 방지).
  const reqMembers = [];
  const seenReq = new Set();
  for (const r of implRows) {
    const rid = _reqGraphId(r);
    if (!rid || seenReq.has(rid)) continue;
    seenReq.add(rid);
    reqMembers.push({ label: rid, stage: 'REQ', kind: 'req', type: 'ids',
      name: String(r?.requirement_name ?? '').trim(),
      asil: _asilMaxRank(r?.asil || r?.requirement_asil || r?.ASIL).asil });
  }
  const sdsMembers = [];
  const seenSds = new Set();
  for (const r of implRows) {
    for (const c of (Array.isArray(r?.sds_components) ? r.sds_components : [])) {
      const lab = String(c ?? '').trim();
      if (!lab || seenSds.has(lab)) continue;
      seenSds.add(lab);
      sdsMembers.push({ label: lab, stage: 'SDS', kind: 'design', type: 'ids' });
    }
  }
  // 시험 멤버 — dedup(단계+라벨+유닛). fnSpecific=이 함수 직접(SUTS·VectorCAST, 함수명/SwUFn 매칭).
  const collectTests = (stageKey, fnSpecific) => {
    const out = [];
    const seen = new Set();
    for (const r of implRows) {
      for (const t of _stageMembers(r, stageKey).items) {
        if (fnSpecific && !matchesFn(t)) continue;
        const lab = _testId(t);
        if (!lab) continue;
        const key = `${stageKey}|${lab}|${_normFn(t?.unit)}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ label: lab, stage: stageKey, kind: 'test', type: 'tests',
          result: String(t?.result ?? ''), unit: String(t?.unit ?? ''),
          source: String(t?.source ?? ''), confidence: String(t?.confidence ?? '') });
      }
    }
    return out;
  };
  const membersByStage = {
    REQ: reqMembers,
    SDS: sdsMembers,
    STS: collectTests('STS', false),
    SUTS: collectTests('SUTS', true),
    SITS: collectTests('SITS', false),
    // 시스템 시험은 요구사항 경유(함수 직접 매칭 아님) → fnSpecific=false (SITS와 동일).
    SyTS: collectTests('SyTS', false),
    SyITS: collectTests('SyITS', false),
    VectorCAST: collectTests('VectorCAST', true),
  };

  // 안전 검증 공백 — ASIL C/D 함수인데 단위시험·VectorCAST 실행이 없거나 FAIL이면 공백.
  const safetyMissing = [];
  if (asilRank >= 3) {
    if (membersByStage.SUTS.length === 0) safetyMissing.push('단위시험');
    if (membersByStage.VectorCAST.length === 0) safetyMissing.push('VectorCAST');
    // FAIL은 ASIL 무관 결함이나 '안전 검증 공백' 배너는 C/D 한정(요구사항 그래프 규칙과 통일).
    // 모든 ASIL의 FAIL은 노드 결과 색(빨강)으로 이미 노출됨.
    if (membersByStage.VectorCAST.some(m => _resultRank(m.result) === 0)) safetyMissing.push('VectorCAST FAIL');
  }
  const safetyGap = safetyMissing.length > 0;

  const stages = (Array.isArray(visibleKeys) && visibleKeys.length)
    ? _FUNC_STAGES.filter(s => visibleKeys.includes(s.key)) : _FUNC_STAGES;

  const columns = stages.map((s, ci) => {
    // 멤버 노드엔 impacted 부여 안 함 — 변경 영향은 root(함수) impactedSelf로만 표시. 시험/요구 노드에
    // impacted를 달면 ReqGraphNode가 '변경 영향 함수'로 오표기(시험 TC는 변경함수가 아님).
    let all = membersByStage[s.key].map((m, i) => ({ ...m, id: `${nf}::${s.key}:${i}` }));
    if (s.kind === 'test' && all.length > G.MAX_PER_COL) {
      all = all.map((m, idx) => ({ m, idx }))
        .sort((a, b) => (_resultRank(a.m.result) - _resultRank(b.m.result)) || (a.idx - b.idx))
        .map(o => o.m);
    }
    const shown = all.slice(0, G.MAX_PER_COL);
    const hiddenFail = all.slice(G.MAX_PER_COL).filter(m => _resultRank(m.result) === 0).length;
    return { stage: s.key, label: s.label, kind: s.kind, colIndex: ci + 1, members: shown, hidden: all.length - shown.length, hiddenFail };
  });

  // 좌표
  const maxRows = Math.max(1, ...columns.map(c => c.members.length || 1));
  const bodyH = maxRows * (G.NODE_H + G.GAP);
  const height = G.HEADER_H + bodyH + G.PAD * 2;
  const width = (stages.length + 1) * G.COL_W;
  const nodeXY = {};
  const rootY = G.HEADER_H + G.PAD + Math.max(0, (bodyH - (G.NODE_H + G.GAP)) / 2);
  nodeXY['__root__'] = { x: G.PAD, y: rootY };
  for (const col of columns) {
    const x = col.colIndex * G.COL_W + G.PAD;
    col.members.forEach((m, mi) => {
      const y = G.HEADER_H + G.PAD + mi * (G.NODE_H + G.GAP);
      m.x = x; m.y = y; nodeXY[m.id] = { x, y };
    });
  }
  // 엣지: 함수(root) → 각 멤버. 안전 체인(C/D 함수→시험)은 ASIL 색 강조.
  const edges = [];
  for (const col of columns) {
    // STS/SITS·SyTS/SyITS는 함수가 구현한 '요구사항'의 시험(함수 직접 대응 아님) → 점선으로 구분(범례 일치).
    // SyTS/SyITS도 collectTests fnSpecific=false(요구사항 경유)라 SITS와 동일하게 점선 처리.
    const viaReq = col.stage === 'STS' || col.stage === 'SITS' || col.stage === 'SyTS' || col.stage === 'SyITS';
    for (const m of col.members) {
      edges.push({ from: '__root__', to: m.id, color: _FUNC_STAGE_COLORS[col.stage] || '#9ca3af', kind: 'req', viaReq, safety: isSafety && col.kind === 'test' });
    }
  }
  edges.forEach((e, i) => { e.fromFrac = (i + 0.5) / Math.max(1, edges.length); });

  return { funcId: funcDisplay, asil, asilRank, isSafety, safetyGap, safetyMissing, impactedSelf, reqCount: reqMembers.length, columns, edges, width, height, nodeXY, rootY };
}

function TraceFuncGraphView({ rows, focusFunctions = null, initialFn = '', embedded = false }) {
  const inventory = useMemo(() => _funcInventory(rows), [rows]);
  // 표에서 함수 클릭 진입 시 그 함수로 시작(뷰 전환마다 새로 마운트되므로 초기값으로 시드). 검색창으로 변경 가능.
  const [selFn, setSelFn] = useState(initialFn || '');
  const [selNode, setSelNode] = useState(null);
  const [hoverId, setHoverId] = useState(null);
  const [focusId, setFocusId] = useState(null);
  const [levelFilter, setLevelFilter] = useState('all'); // 'all' | 'design' | 'test'
  const svgRef = useRef(null);

  const visibleKeys = useMemo(() => {
    if (levelFilter === 'design') return ['REQ', 'SDS'];
    if (levelFilter === 'test') return ['STS', 'SUTS', 'SITS', 'SyTS', 'SyITS', 'VectorCAST'];
    return null;
  }, [levelFilter]);

  const focusSet = useMemo(() => {
    const arr = Array.isArray(focusFunctions) ? focusFunctions : [];
    return new Set(arr.map(f => _normFn(f)).filter(Boolean));
  }, [focusFunctions]);

  const selectedFn = useMemo(() => {
    if (!inventory.length) return null;
    if (!selFn) return inventory[0].display;
    const nf = _normFn(selFn);
    const hit = inventory.find(f => f.norm === nf);
    return hit ? hit.display : null;
  }, [inventory, selFn]);

  const graph = useMemo(() => (selectedFn ? _buildFuncGraph(selectedFn, rows, focusSet, visibleKeys) : null), [selectedFn, rows, focusSet, visibleKeys]);

  useEffect(() => {
    setSelNode(prev => (prev && graph && graph.nodeXY[prev.id] && (!prev.isRoot || prev.label === graph.funcId)) ? prev : null);
    setHoverId(null); setFocusId(null);
  }, [graph]);

  const selValid = selNode && graph && graph.nodeXY[selNode.id];
  const activeNodeId = hoverId || (selValid ? selNode.id : null);
  const neighborSet = useMemo(() => {
    const s = new Set();
    if (activeNodeId && graph) {
      for (const e of graph.edges) {
        if (e.from === activeNodeId) s.add(e.to);
        else if (e.to === activeNodeId) s.add(e.from);
      }
    }
    return s;
  }, [graph, activeNodeId]);

  if (!inventory.length) {
    return <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 12 }}>표시할 UDS 함수가 없습니다(추적성 매트릭스에 source_ids 미존재 — UDS 추출/매핑을 먼저 실행하세요).</div>;
  }

  const G = _GRAPH;
  const headerLabels = ['함수', ...(graph ? graph.columns.map(c => c.label) : [])];
  const isNodeActive = (id) => !activeNodeId || id === activeNodeId || neighborSet.has(id);
  const isEdgeActive = (e) => !activeNodeId || e.from === activeNodeId || e.to === activeNodeId;
  const totalHiddenFail = graph ? graph.columns.reduce((n, c) => n + (c.hiddenFail || 0), 0) : 0;

  const exportSvg = () => {
    if (!svgRef.current || !graph) return;
    _downloadBlob(new Blob([_graphSvgString(svgRef.current)], { type: 'image/svg+xml;charset=utf-8' }), `${graph.funcId}_func_trace.svg`);
  };
  const exportPng = () => {
    if (!svgRef.current || !graph) return;
    const s = _graphSvgString(svgRef.current);
    const bg = (getComputedStyle(svgRef.current).getPropertyValue('--bg') || '#ffffff').trim() || '#ffffff';
    const w = graph.width, h = graph.height, scale = 2;
    const img = new Image();
    const url = URL.createObjectURL(new Blob([s], { type: 'image/svg+xml;charset=utf-8' }));
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width = w * scale; canvas.height = h * scale;
      const ctx = canvas.getContext('2d');
      ctx.scale(scale, scale);
      ctx.fillStyle = bg; ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0);
      URL.revokeObjectURL(url);
      canvas.toBlob(b => { if (b) _downloadBlob(b, `${graph.funcId}_func_trace.png`); }, 'image/png');
    };
    img.onerror = () => URL.revokeObjectURL(url);
    img.src = url;
  };

  return (
    <div>
      {/* 함수 선택 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
        {/* 인라인(embedded)에선 행의 함수명 버튼이 선택자이므로 내부 함수 선택창 숨김 — 하이라이트 어긋남·DOM id 중복 제거 */}
        {!embedded && (<>
          <label htmlFor="func-graph-input" style={{ fontSize: 12, fontWeight: 600, color: 'var(--fg)' }}>함수</label>
          <input id="func-graph-input" list="func-graph-ids" value={selFn} onChange={e => setSelFn(e.target.value)}
            placeholder={`UDS 함수 선택/검색 (${inventory.length}개, 미입력 시 첫 항목)`}
            style={{ flex: '1 1 280px', maxWidth: 440, padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }} />
          <datalist id="func-graph-ids">
            {inventory.slice(0, 2000).map((f, i) => <option key={i} value={f.display} />)}
          </datalist>
          {selFn && !selectedFn && <span style={{ fontSize: 11, color: '#d97706' }}>일치하는 함수 없음</span>}
        </>)}
        <div role="group" aria-label="단계 필터" style={{ display: 'inline-flex', border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden', marginLeft: 'auto' }}>
          {[['all', '전체'], ['design', '설계'], ['test', '시험']].map(([k, lbl], i) => (
            <button key={k} type="button" onClick={() => setLevelFilter(k)} aria-pressed={levelFilter === k}
              title={k === 'design' ? '요구사항·SDS만' : k === 'test' ? 'STS·SUTS·SITS·SyTS·SyITS·VectorCAST만' : '전체 단계'}
              style={{ padding: '5px 10px', fontSize: 11, border: 'none', borderLeft: i ? '1px solid var(--border)' : 'none', cursor: 'pointer',
                background: levelFilter === k ? 'var(--accent)' : 'var(--bg)', color: levelFilter === k ? '#fff' : 'var(--fg)', fontWeight: levelFilter === k ? 700 : 400 }}>
              {lbl}
            </button>
          ))}
        </div>
      </div>

      {graph && (
        <>
          {/* 요약 + 범례 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, alignItems: 'center' }}>
            <span><strong style={{ color: 'var(--fg)', wordBreak: 'break-all' }}>{graph.funcId}</strong></span>
            {graph.asil && <span style={{ padding: '1px 7px', borderRadius: 10, background: (_ASIL_COLORS[graph.asil] || '#6b7280'), color: '#fff', fontWeight: 700 }}>ASIL {graph.asil}</span>}
            {graph.reqCount > 0 && <span title="이 함수가 구현(source_ids 포함)하는 요구사항 수">구현 요구사항 <strong style={{ color: 'var(--fg)' }}>{graph.reqCount}</strong></span>}
            {graph.columns.map(c => (
              <span key={c.stage} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <span style={{ width: 9, height: 9, borderRadius: 2, background: _FUNC_STAGE_COLORS[c.stage], display: 'inline-block' }} />
                {c.label} {c.members.length}{c.hidden > 0 ? `(+${c.hidden})` : ''}
              </span>
            ))}
            <span style={{ opacity: 0.7 }} title="단위시험(SUTS)·VectorCAST는 이 함수에 직접 연결(unit/subprogram==함수). 요구사항·설계·STS·SITS는 이 함수가 구현한 요구사항을 경유한 연결입니다.">
              ⓘ SUTS·VectorCAST=함수 직접 / 나머지=요구사항 경유
            </span>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }} title="STS·SITS는 함수가 구현한 요구사항의 시험(함수 직접 대응 아님)이라 점선으로 구분합니다.">
              <span style={{ width: 14, height: 0, borderTop: '2px dashed #94a3b8', display: 'inline-block' }} />요구사항 경유 시험(STS·SITS)
            </span>
            {totalHiddenFail > 0 && (
              <span style={{ color: '#dc2626', fontWeight: 700 }}
                title={`시험 컬럼 캡(${G.MAX_PER_COL})을 초과해 표시되지 않은 FAIL 시험이 있습니다(FAIL 우선 정렬).`}>
                ⚠ 미표시 FAIL {totalHiddenFail}
              </span>
            )}
            {graph.isSafety && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                title="ASIL C/D 함수가 단위시험·VectorCAST로 검증되는 경로를 ASIL 색·굵게로 강조합니다.">
                <span style={{ width: 14, height: 0, borderTop: `2px solid ${_ASIL_COLORS[graph.asil] || '#dc2626'}`, display: 'inline-block' }} />안전 검증 경로
              </span>
            )}
            {graph.safetyGap && (
              <span style={{ color: '#dc2626', fontWeight: 700 }}
                title={`ISO 26262: ASIL ${graph.asil} 함수의 시험 검증이 부족합니다(C/D=단위시험·VectorCAST 기대, FAIL 시 결함).`}>
                ⚠ 검증 공백: {graph.safetyMissing.join('·')}
              </span>
            )}
            {graph.impactedSelf && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#b45309', fontWeight: 600 }}
                title="영향도 분석에서 변경된 함수입니다.">
                <span style={{ width: 9, height: 9, borderRadius: '50%', background: '#b45309', display: 'inline-block' }} />변경 영향 함수
              </span>
            )}
            <span style={{ opacity: 0.6 }} title="hiMA UCOneIDTrace 표기 대응 — 요구사항=□·설계=집(△지붕)·시험스펙=타원·단위시험=◇·통합시험=8각">
              모양: 요구□·설계집·시험◯◇⯃
            </span>
            <div style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
              <button type="button" onClick={exportSvg} title="그래프를 SVG(벡터)로 내보내기"
                style={{ padding: '4px 9px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 5, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>SVG ↓</button>
              <button type="button" onClick={exportPng} title="그래프를 PNG(이미지)로 내보내기"
                style={{ padding: '4px 9px', fontSize: 11, border: '1px solid var(--border)', borderRadius: 5, background: 'var(--bg)', color: 'var(--fg)', cursor: 'pointer' }}>PNG ↓</button>
            </div>
          </div>

          {/* SVG 그래프 */}
          <div style={{ overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg)', maxHeight: 580 }}>
            <svg ref={svgRef} width={graph.width} height={graph.height} style={{ display: 'block', minWidth: '100%' }} role="group" aria-label={`${graph.funcId} 함수중심 추적 그래프`}>
              <defs>
                <marker id="rg-arrow" markerWidth={7} markerHeight={7} refX={6} refY={2.5} orient="auto" markerUnits="userSpaceOnUse">
                  <path d="M0,0 L6,2.5 L0,5 Z" fill="#94a3b8" />
                </marker>
                <clipPath id="rg-node-clip">
                  <rect x={0} y={0} width={G.NODE_W} height={G.NODE_H} rx={6} />
                </clipPath>
              </defs>
              {headerLabels.map((h, ci) => (
                <text key={ci} x={ci * G.COL_W + G.PAD} y={16} fontSize={11} fontWeight={700} style={{ fill: 'var(--text-muted)' }}>{h}</text>
              ))}
              {graph.edges.map((e, i) => {
                const a = graph.nodeXY[e.from], b = graph.nodeXY[e.to];
                if (!a || !b) return null;
                const x1 = a.x + G.NODE_W;
                const y1 = a.y + (e.fromFrac != null ? e.fromFrac * G.NODE_H : G.NODE_H / 2);
                const x2 = b.x, y2 = b.y + G.NODE_H / 2;
                const active = isEdgeActive(e);
                const stroke = e.safety ? (_ASIL_COLORS[graph.asil] || e.color) : e.color;
                const sw = e.safety ? 2 : 1.2;
                const idleOp = e.safety ? 0.45 : 0.16;
                const op = active ? (e.safety ? 0.85 : 0.55) : (activeNodeId ? 0.06 : idleOp);
                return <path key={i} d={_bez(x1, y1, x2, y2)} fill="none" stroke={stroke} strokeWidth={sw} strokeDasharray={e.viaReq ? '4 2' : undefined} markerEnd="url(#rg-arrow)" opacity={op} />;
              })}
              {/* root(함수) 노드 */}
              <ReqGraphNode node={{ id: '__root__', label: graph.funcId, x: G.PAD, y: graph.rootY, isRoot: true, impacted: graph.impactedSelf }}
                color={_STAGE_COLORS.UDS}
                active={isNodeActive('__root__')} kbFocused={focusId === '__root__'}
                onClick={() => setSelNode({ id: '__root__', label: graph.funcId, stage: '함수', asil: graph.asil, isRoot: true })}
                onHover={setHoverId} onFocus={setFocusId} onBlur={() => setFocusId(null)} />
              {/* 단계 노드 */}
              {graph.columns.map(col => col.members.map(m => (
                <ReqGraphNode key={m.id} node={m} color={_FUNC_STAGE_COLORS[m.stage] || '#9ca3af'}
                  active={isNodeActive(m.id)} kbFocused={focusId === m.id}
                  onClick={() => setSelNode(m)} onHover={setHoverId} onFocus={setFocusId} onBlur={() => setFocusId(null)} />
              )))}
              {/* 끊긴 단계 placeholder */}
              {graph.columns.filter(c => c.members.length === 0).map(c => (
                <g key={`empty-${c.stage}`} opacity={activeNodeId ? 0.28 : 1} transform={`translate(${c.colIndex * G.COL_W + G.PAD},${G.HEADER_H + G.PAD})`}>
                  <rect width={G.NODE_W} height={G.NODE_H} rx={5} fill="none" stroke="#d1d5db" strokeDasharray="4 3" />
                  <text x={G.NODE_W / 2} y={G.NODE_H / 2 + 4} fontSize={10} textAnchor="middle" style={{ fill: '#9ca3af' }}>없음</text>
                </g>
              ))}
            </svg>
          </div>

          {/* 노드 상세 */}
          {selNode && (
            <div style={{ marginTop: 10, padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--panel, #f9fafb)', fontSize: 12 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <strong style={{ color: 'var(--fg)', wordBreak: 'break-all' }}>{selNode.label}</strong>
                <button type="button" onClick={() => setSelNode(null)} style={{ border: 'none', background: 'none', cursor: 'pointer', color: 'var(--text-muted)', fontSize: 16, lineHeight: 1 }} aria-label="닫기">×</button>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 14, color: 'var(--text-muted)' }}>
                <span>단계 <strong style={{ color: selNode.isRoot ? 'var(--fg)' : (_FUNC_STAGE_COLORS[selNode.stage] || 'var(--fg)') }}>{selNode.isRoot ? '함수(UDS)' : (_FUNC_STAGES.find(s => s.key === selNode.stage)?.label || selNode.stage)}</strong></span>
                {selNode.isRoot && selNode.asil && <span>ASIL <strong>{selNode.asil}</strong></span>}
                {!selNode.isRoot && selNode.stage === 'REQ' && selNode.asil && <span>ASIL <strong style={{ color: _ASIL_COLORS[selNode.asil] || 'var(--fg)' }}>{selNode.asil}</strong></span>}
                {!selNode.isRoot && selNode.name && <span style={{ flexBasis: '100%' }}>요구사항명 <strong style={{ color: 'var(--fg)' }}>{selNode.name}</strong></span>}
                {selNode.source && <span>소스 <strong>{selNode.source}</strong></span>}
                {selNode.unit && <span>유닛 <strong>{selNode.unit}</strong></span>}
                {selNode.result && <span>결과 <strong style={{ color: _testResultColor(selNode.result) }}>{selNode.result}</strong></span>}
                {selNode.confidence && <span>신뢰 <strong>{CONFIDENCE_LABELS[selNode.confidence] || selNode.confidence}</strong></span>}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
