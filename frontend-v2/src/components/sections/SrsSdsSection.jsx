import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { api, post, getUsername } from '../../api.js';
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
    // analysisResult.matchedScm.linked_docs는 분석 실행 시점의 스냅샷이라, 이후 Settings에서
    // 등록한 vectorcast(복수 경로)가 누락되거나 빈 배열([])로 굳어 있을 수 있다(vectorcast
    // 필드 추가 직후~경로 입력 전 시점에 캡처된 경우). core 문서가 있고 vectorcast가
    // '비어있지 않을' 때만 스냅샷을 그대로 쓰고, 그 외엔 레지스트리(단일 진실원) 최신본을
    // 가져온다 — 안 그러면 VectorCAST/P&F가 끝까지 비어 나온다.
    if (scmLinkedDocs && (scmLinkedDocs.sts || scmLinkedDocs.suts || scmLinkedDocs.sits)
        && Array.isArray(scmLinkedDocs.vectorcast) && scmLinkedDocs.vectorcast.length > 0) {
      setLinkedDocs(scmLinkedDocs);
      return;
    }
    api('/api/scm/list').then(d => {
      const items = d?.items || (Array.isArray(d) ? d : []);
      // Match the SAME registry entry the Dashboard selected for this job.
      // Falling back to items[0] would silently pull another project's docs
      // in multi-SCM environments.
      const matched = scmId ? items.find(it => it.id === scmId) : items[0];
      if (matched?.linked_docs) setLinkedDocs(matched.linked_docs);
      else if (scmLinkedDocs) setLinkedDocs(scmLinkedDocs);
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
    const cacheKey = JSON.stringify({ srs: docPaths.srs, sds: docPaths.sds, jobUrl: job?.url, sts: activeDocs.sts, suts: activeDocs.suts, sits: activeDocs.sits, vcast: (Array.isArray(activeDocs?.vectorcast) ? activeDocs.vectorcast : []).filter(Boolean).join(',') });
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
            dataSources.push(`SITS: ${sitsData.vcast_rows.length}건`);
          } else if (Array.isArray(sitsData?.available_sheets)) {
            stepWarnings.push(`SITS: ${sitsData.warning || sitsData.error || '시트 미인식'}. 사용 가능한 시트: ${sitsData.available_sheets.join(', ')}`);
          }
        } catch (e) {
          stepWarnings.push(`SITS 추출 실패: ${e.message}`);
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
        stepWarnings.push('설계/테스트 매핑 데이터가 없습니다. SDS/UDS/STS/SUTS/SITS/VectorCAST 연결을 확인하세요.');
      }

      // Step 4: Generate full traceability matrix (V-model 6-level)
      setLoadProgress(`매트릭스 생성 중 (${reqItems.length}개 요구사항)...`);
      const data = await post('/api/jenkins/uds/traceability-matrix', {
        requirement_items: reqItems,
        mapping_pairs: mappingPairs,
        uds_function_ids: udsFunctionIds,
        vcast_rows: vcastRows,
        sds_pairs: sdsPairs,
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
          {[
            { label: 'SRS', path: docPaths.srs, fromScm: !localDocPaths.srs && !!scmLinked.srs },
            { label: 'SDS', path: docPaths.sds, fromScm: !localDocPaths.sds && !!scmLinked.sds },
            { label: 'HSIS', path: docPaths.hsis, fromScm: !localDocPaths.hsis && !!scmLinked.hsis },
            { label: 'STP', path: docPaths.stp, fromScm: !localDocPaths.stp && !!scmLinked.stp },
          ].map(({ label, path, fromScm }) => (
            <div key={label} className="artifact-item" style={{ background: 'var(--bg)', overflow: 'hidden' }}>
              <span className="pill pill-purple" style={{ minWidth: 40, textAlign: 'center', flexShrink: 0 }}>{label}</span>
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
                  <span className="text-muted text-sm">설정 탭 또는 SCM에서 경로를 등록하세요</span>
                  <StatusBadge tone="neutral">미등록</StatusBadge>
                </>
              )}
            </div>
          ))}
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

// Field lists aligned with backend _cache_trace_summary (jenkins.py L2385~2400).
// Any divergence here will cause the Dashboard trace summary card to disagree
// with the Matrix / UncoveredTopList counts — keep the two in lockstep.
const DESIGN_FIELDS = [
  'source_ids', 'sds_components', 'functions', 'mapping', 'sds', 'source_mapping',
];
const TEST_FIELDS = [
  'tests', 'sts_tests', 'suts_tests', 'sits_tests', 'vcast_tests', 'test_ids',
];

function hasDesignData(r) {
  return DESIGN_FIELDS.some(f => _hasData(r[f]));
}

function hasTestData(r) {
  return TEST_FIELDS.some(f => _hasData(r[f]));
}

// Derive coverage status from row data (pure function, shared across useMemo/filters)
export function deriveStatus(r) {
  const hasDesign = hasDesignData(r);
  const hasTest = hasTestData(r);
  // Full: design (any of 6 field kinds) + test (any of 6 field kinds)
  if (hasDesign && hasTest) return 'covered';
  // Partial: any one layer present
  if (hasDesign || hasTest) return 'partial';
  if (r.status && r.status !== 'uncovered') return r.status;
  return 'uncovered';
}

const PAGE_SIZES = [30, 50, 100];
const SOURCE_ICONS = { STS: 'S', SUTS: 'U', SITS: 'I', VectorCAST: 'V' };
const SOURCE_COLORS = { STS: '#2563eb', SUTS: '#7c3aed', SITS: '#0891b2', VectorCAST: '#ea580c' };
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

// ── hiMA식 교차 추적성 매트릭스 (additive '매트릭스' 뷰) ──
// 행=요구사항(target), 열=SDS 컴포넌트(related), 셀=O/공백. 추적 0건 행은 핑크 강조
// (hiMA 0카운트 밴드 대응). 데이터는 filtered rows에서 클라이언트 파생(필터 반영),
// '링크 테이블 ↓'는 서버 파생 link_table(감사 baseline)을 그대로 내보낸다.
const _TRACE_BANDS = ['SDS', 'UDS', 'STS', 'SUTS', 'SITS', 'VectorCAST'];

function _testId(t) {
  if (!t || typeof t !== 'object') return '';
  return String(t.testcase || t.subprogram || t.unit || t.id || '').trim();
}
// 백엔드 build_link_table 의 밴드 추출과 동일 규칙 — 화면/내보내기 일관성.
function _rowBands(row) {
  const tids = (arr) => (Array.isArray(arr) ? arr : []).map(_testId).filter(Boolean);
  return {
    SDS: (Array.isArray(row.sds_components) ? row.sds_components : []).map(String).filter(Boolean),
    UDS: (Array.isArray(row.source_ids) ? row.source_ids : []).map(String).filter(Boolean),
    STS: tids(row.sts_tests),
    SUTS: tids(row.suts_tests),
    SITS: tids(row.sits_tests),
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
      const total = _TRACE_BANDS.reduce((n, bd) => n + bands[bd].length, 0);
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
      const res = await fetch('/api/jenkins/uds/traceability-matrix/export-xlsx', {
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
              {cols.map(c => (
                <th key={c} title={c}
                  style={{ writingMode: 'vertical-rl', transform: 'rotate(180deg)', whiteSpace: 'nowrap', maxHeight: 140 }}>{c}</th>
              ))}
              <th title="SDS→UDS 단위함수 수">UDS</th>
              <th title="SW 시험">STS</th><th title="단위 시험">SUTS</th><th title="통합 시험">SITS</th>
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
                  {cols.map(c => <Cell key={c} on={sdsSet.has(c)} />)}
                  <td style={{ textAlign: 'center' }}>{r.bands.UDS.length || ''}</td>
                  <Cell on={r.bands.STS.length > 0} />
                  <Cell on={r.bands.SUTS.length > 0} />
                  <Cell on={r.bands.SITS.length > 0} />
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

  // Reset page when rows change (e.g., new matrix data)
  useEffect(() => { setCurrentPage(0); setExpandedReqId(null); setExpandedTreeNodes(new Set()); }, [rows]);

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
    return [...srcs].sort();
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

  // V-Model 단계별 추적성 공백 — 정방향(설계 단절)·역방향(미추적 시험)을 viewMode와
  // 무관하게 항상 노출(deep-analyze WARNING: 공백이 covered 녹색/토글 뒤에 묻힘).
  //  - sdsNoUds: SRS→SDS는 됐으나 SDS→UDS 끊김(설계 단절)
  //  - udsUntestedFns: UDS 함수 중 SUTS 단위시험 미연결(정방향 검증 공백)
  //  - orphanSuts: 어느 UDS 함수에도 안 붙는 SUTS(역방향: 시험有 설계無)
  //  - unmappedTotal/Suts: VectorCAST 미추적(역방향) — 백엔드 summary 우선
  const gapStats = useMemo(() => {
    let sdsNoUds = 0, udsUntestedFns = 0, udsFnTotal = 0, orphanSuts = 0;
    for (const r of rows) {
      const sds = Array.isArray(r.sds_components) ? r.sds_components : [];
      const uds = Array.isArray(r.source_ids) ? r.source_ids : [];
      if (sds.length > 0 && uds.length === 0) sdsNoUds++;
      const m = _unitTestMap(r);
      udsFnTotal += uds.length;
      for (const fn of uds) if (!((m.get(_normFn(fn)) || []).length)) udsUntestedFns++;
      const udsSet = new Set(uds.map(_normFn));
      for (const t of _stageMembers(r, 'SUTS').items) {
        const u = _normFn(t && t.unit);
        if (u && !udsSet.has(u)) orphanSuts++;
      }
    }
    const unmappedTotal = summary?.unmapped_vcast_count ?? unmappedVcast.length;
    const unmappedSuts = summary?.unmapped_suts_tested ?? unmappedVcast.filter(u => u && u.category === 'suts_tested').length;
    const hasAny = sdsNoUds || udsUntestedFns || orphanSuts || unmappedTotal;
    return { sdsNoUds, udsUntestedFns, udsFnTotal, orphanSuts, unmappedTotal, unmappedSuts, hasAny };
  }, [rows, summary, unmappedVcast]);

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
              <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }} title="P/F는 VectorCAST 실행 결과만. STS/SUTS/SITS는 '매핑 존재'(중립)이며 시험 통과 아님 — 매핑 엔트리는 Total에 포함되나 P/F 대상이 아님.">
                실행검증(VectorCAST) {summary.total_pass ?? 0}P / {summary.total_fail ?? 0}F · 매핑 {summary.total_tests}건(STS/SUTS/SITS=매핑·통과 아님)
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
                  Covered (설계+시험 <em>매핑</em> 존재)
                </td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.covered.fg }}>{coverage.covered}</td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.covered.fg }}>{coverage.pct}%</td>
                <td style={{ padding: '6px 12px', fontSize: 11 }}>UDS 소스 매핑 + STS/SUTS/SITS/VectorCAST 시험 <strong>매핑</strong> 존재 — 매핑일 뿐 시험 통과 아님(P/F는 VectorCAST만)</td>
              </tr>
              {coverage.partial > 0 && (
                <tr style={{ background: COVERAGE_COLORS.partial.bg }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600, color: COVERAGE_COLORS.partial.fg }}>
                    Partial (테스트만 존재)
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.partial.fg }}>{coverage.partial}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.partial.fg }}>{coverage.total > 0 ? Math.round(coverage.partial / coverage.total * 100) : 0}%</td>
                  <td style={{ padding: '6px 12px', fontSize: 11 }}>STS 테스트 매핑 있으나 UDS 소스 매핑 없음 (비기능/HW/시스템 레벨 요구사항)</td>
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
                  설계(SDS/UDS) 매핑이 존재하는 요구사항 중 검증 완료 비율
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
                  STS/SUTS/SITS/VectorCAST 테스트 매핑 기준
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* 추적성 공백 (양방향) — viewMode 무관 상시 노출. 정방향 설계 단절 + 역방향 미명세 시험.
          deep-analyze: 공백이 covered 녹색·토글 뒤에 묻혀 감사에서 누락되는 문제 해소. */}
      {gapStats.hasAny ? (
        <div style={{ marginBottom: 12, border: `1px solid ${COVERAGE_COLORS.partial.border}`, borderLeft: `4px solid ${COVERAGE_COLORS.partial.border}`, borderRadius: 8, padding: '10px 14px', background: COVERAGE_COLORS.partial.bg + '40' }}>
          <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6, color: COVERAGE_COLORS.partial.fg }}>
            ⚠ 추적성 공백 (양방향 — 매핑 존재만으로 가려지지 않게 상시 표시)
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 12 }}>
            <GapBadge label="SDS有·UDS無 (설계 단절)" value={gapStats.sdsNoUds} tone={gapStats.sdsNoUds ? 'warn' : 'ok'}
              title="SRS→SDS는 추적됐으나 SDS→UDS(단위설계)가 끊긴 행" />
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
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
            정방향(요구사항→설계→시험)·역방향(시험→요구사항) 공백. ISO 26262 양방향 추적성 신호 — 0이 아니면 보강 검토. 역방향 상세는 트리 뷰 'SRS 미추적 시험'.
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
              { label: '\uC804\uCCB4 \uAC80\uC99D', type: '\uD1B5\uD569', count: summary.mapped_test_count ?? (coverage.covered + coverage.partial), desc: 'STS+SUTS+SITS+VectorCAST' },
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
          <button type="button" onClick={() => setViewMode('calltree')} aria-pressed={viewMode === 'calltree'} title="함수 호출 트리 (tree-sitter 정밀 분석 · ASIL 강조)"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'calltree' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'calltree' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'calltree' ? 700 : 400 }}>
            콜트리
          </button>
          <button type="button" onClick={() => setViewMode('graph')} aria-pressed={viewMode === 'graph'} title="요구사항 1개의 하위 추적 그래프 (SDS→UDS→STS/SUTS/SITS→VectorCAST · ASIL 강조 · UDS↔SUTS 매핑)"
            style={{ padding: '6px 10px', fontSize: 11, border: 'none', borderLeft: '1px solid var(--border)', cursor: 'pointer',
              background: viewMode === 'graph' ? 'var(--accent)' : 'var(--bg)',
              color: viewMode === 'graph' ? '#fff' : 'var(--fg)', fontWeight: viewMode === 'graph' ? 700 : 400 }}>
            그래프
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
            <th colSpan={2} style={{ textAlign: 'center', background: '#eff6ff', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => toggleSort('func_count')}>
              설계 (T1,T2){sortIcon('func_count')}
            </th>
            <th colSpan={4} style={{ textAlign: 'center', background: '#f0fdf4', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => toggleSort('test_count')}>
              검증 (T3,T4,T5){sortIcon('test_count')}
            </th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 50, textAlign: 'center' }}>P/F</th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 55, textAlign: 'center' }}>신뢰도</th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 75, cursor: 'pointer' }} onClick={() => toggleSort('status')}>
              상태{sortIcon('status')}
            </th>
          </tr>
          <tr>
            <th style={{ fontSize: 10, background: '#eff6ff' }} title="T1: SRS→SDS">SDS 컴포넌트</th>
            <th style={{ fontSize: 10, background: '#eff6ff' }} title="T2: SDS→UDS">UDS 함수</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T3: SRS→STS">STS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T4: UDS→SUTS">SUTS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T5: SDS→SITS">SITS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }}>VectorCAST</th>
          </tr>
        </thead>
        <tbody>
          {displayedRows.map((r, idx) => {
            const reqId = _rowReqId(r) || `row-${idx}`;
            const status = deriveStatus(r);
            const colors = COVERAGE_COLORS[status] || {};
            const sdsComps = r.sds_components ?? [];
            const srcFuncs = r.source_ids ?? [];
            const rawTests = Array.isArray(r.tests) ? r.tests : [];
            // ISO 26262 추적 관계별 분리: T3(STS), T4(SUTS), T5(SITS)
            const stsOnlyTests = Array.isArray(r.sts_tests) ? r.sts_tests : rawTests.filter(t => t.source === 'STS');
            const sutsOnlyTests = Array.isArray(r.suts_tests) ? r.suts_tests : rawTests.filter(t => t.source === 'SUTS');
            const sitsTests = Array.isArray(r.sits_tests) ? r.sits_tests : rawTests.filter(t => t.source === 'SITS');
            const vcastTests = rawTests.filter(t => t.source === 'VectorCAST');
            const otherTests = rawTests.filter(t => !['STS','SUTS','SITS','VectorCAST'].includes(t.source));
            const stsCount = stsOnlyTests.length;
            const sutsCount = sutsOnlyTests.length;
            const sitsCount = sitsTests.length;
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
                    <td colSpan={10} style={{ padding: '10px 16px' }}>
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
                              {srcFuncs.map((fn, fi) => (
                                <div key={fi} style={{ padding: '2px 0', fontFamily: 'monospace', borderBottom: '1px solid #e5e7eb' }}>{fn}</div>
                              ))}
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

      {/* 콜트리 보기 (신규 — tree-sitter 정밀 함수 호출 트리. entry 기반 깊이탐색 + ASIL 강조) */}
      {viewMode === 'calltree' && (
        <CallTreeView job={job} cacheRoot={cacheRoot} buildSelector={buildSelector}
          sourceRoot={sourceRoot} seedFns={callTreeSeeds} toast={toast} />
      )}

      {/* 그래프 보기 (신규 — 요구사항 1개의 하위 추적 그래프. SVG 노드-엣지, filtered row로 완결.
          focusFunctions=영향도 연동 변경함수 → 그래프 안 해당 UDS/시험 노드 강조) */}
      {viewMode === 'graph' && (
        <TraceReqGraphView rows={filtered} focusFunctions={focusFunctions} />
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
 * SRS-ID 루트 → 문서 단계(SDS/UDS/STS/SUTS/SITS/VectorCAST) 트리로 재구성한다.
 * 한 요구사항이 어느 단계까지 추적됐고 어디서 끊겼는지(빈 단계 = 회색 칩)를
 * 펼치지 않아도 한눈에 본다.
 *  - 상태 분류: deriveStatus 재사용 → 표/대시보드/백엔드 _cache_trace_summary와 lockstep.
 *  - P/F: 표(L1246-1252)와 동일 규칙. STS/SUTS/SITS의 result='mapped'는 '시험 통과'가
 *    아니라 '매핑 존재'이므로 중립색 유지(ISO 26262: 매핑 존재 ≠ 시험 통과).
 *  - SDS↔UDS 정확 부모-자식 엣지는 row 데이터에 없으므로(평탄 배열) 거짓 중첩 대신
 *    SRS 직속 단계 노드로 평면 배치한다. VectorCAST만 실행 P/F 보유. */

const TREE_STAGES = [
  { key: 'SDS',  label: 'SDS',  kind: 'design' },
  { key: 'UDS',  label: 'UDS',  kind: 'design' },
  { key: 'STS',  label: 'STS',  kind: 'test' },
  { key: 'SUTS', label: 'SUTS', kind: 'test' },
  { key: 'SITS', label: 'SITS', kind: 'test' },
  { key: 'VectorCAST', label: 'VectorCAST', kind: 'test' },
];

// STS/SUTS/SITS는 'mapped' 리터럴(실 P/F 아님) → 중립. VectorCAST만 실제 결과.
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
  if (stageKey === 'UDS') return { type: 'ids', items: Array.isArray(r.source_ids) ? r.source_ids : [] };
  const raw = Array.isArray(r.tests) ? r.tests : [];
  if (stageKey === 'STS')  return { type: 'tests', items: Array.isArray(r.sts_tests)  ? r.sts_tests  : raw.filter(t => t.source === 'STS') };
  if (stageKey === 'SUTS') return { type: 'tests', items: Array.isArray(r.suts_tests) ? r.suts_tests : raw.filter(t => t.source === 'SUTS') };
  if (stageKey === 'SITS') return { type: 'tests', items: Array.isArray(r.sits_tests) ? r.sits_tests : raw.filter(t => t.source === 'SITS') };
  if (stageKey === 'VectorCAST') return { type: 'tests', items: raw.filter(t => t.source === 'VectorCAST' || !['STS', 'SUTS', 'SITS'].includes(t.source)) };
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
// 헤더(STS/SUTS/SITS/VectorCAST)가 곧 소스이고, 함수 중첩은 _unitTestMap이 SUTS 전용이라
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
        <span style={{ fontWeight: 600 }}>단계 SRS → SDS → UDS → STS → SUTS → SITS → VectorCAST</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: COVERAGE_COLORS.covered.border, marginRight: 4, verticalAlign: 'middle' }} />연결됨</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: '#d1d5db', marginRight: 4, verticalAlign: 'middle' }} />끊김(연결 없음)</span>
        <span>P/F는 VectorCAST 실행 결과만 (STS/SUTS/SITS는 매핑 존재 표시)</span>
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
 * 추적성 매트릭스와 같은 섹션('추적성 분석') 안에서 함수 호출 관계를 보여준다.
 * 백엔드 POST /api/jenkins/call-tree (engine='precise', build_call_tree_precise)가
 * parse_c_project(tree-sitter)로 호출엣지를 추출하고, 노드에 ASIL/파일/시그니처를 실어준다.
 * - entry(진입 함수)는 빌드 소스의 known 함수명과 일치해야 적중. 매트릭스 source_ids에서 자동완성.
 * - 표준 라이브러리는 백엔드에서 제외. include_external 시 미정의(외부) 호출만 별도 표시.
 * - 루트는 항상 펼침, 하위는 클릭 펼침(깊은 트리 DOM 비용 절감). cycle/truncated 플래그 표시. */
function CallTreeNode({ node, path, expanded, onToggle, depth, includeExternal }) {
  const children = Array.isArray(node?.calls) ? node.calls : [];
  const externals = includeExternal && Array.isArray(node?.externals) ? node.externals : [];
  const hasChildren = children.length > 0 || externals.length > 0;
  const isOpen = depth === 0 || expanded.has(path);
  const asil = node?.asil ? String(node.asil).toUpperCase() : '';
  return (
    <li style={{ listStyle: 'none' }}>
      <div
        role={hasChildren ? 'button' : undefined}
        tabIndex={hasChildren ? 0 : undefined}
        aria-expanded={hasChildren ? isOpen : undefined}
        onClick={hasChildren ? () => onToggle(path) : undefined}
        onKeyDown={hasChildren ? (e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onToggle(path); } }) : undefined}
        title={node?.file || ''}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 6px', fontSize: 11,
          cursor: hasChildren ? 'pointer' : 'default', borderRadius: 4 }}
      >
        <span style={{ fontFamily: 'monospace', width: 12, display: 'inline-block', color: 'var(--text-muted)' }}>
          {hasChildren ? (isOpen ? '▾' : '▸') : '·'}
        </span>
        <strong style={{ fontFamily: 'monospace' }}>{node?.name}</strong>
        {asil && (
          <span style={{ fontSize: 9, padding: '0 5px', borderRadius: 8, fontWeight: 700, color: '#fff',
            background: _ASIL_COLORS[asil] || '#6b7280' }}>ASIL {asil}</span>
        )}
        {node?.cycle && <span style={{ fontSize: 9, color: '#d97706' }} title="재귀/순환 호출 — 더 펼치지 않음">↻ 순환</span>}
        {node?.truncated && <span style={{ fontSize: 9, color: 'var(--text-muted)' }} title="최대 깊이 도달 — 더 펼치지 않음">… 깊이제한</span>}
        {node?.signature && (
          <code style={{ fontSize: 9, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 }}>
            {node.signature}
          </code>
        )}
      </div>
      {isOpen && hasChildren && (
        <ul style={{ margin: 0, paddingLeft: 18, borderLeft: '1px dashed var(--border)' }}>
          {children.map((c, i) => (
            <CallTreeNode key={`${path}.${i}`} node={c} path={`${path}.${i}`}
              expanded={expanded} onToggle={onToggle} depth={depth + 1} includeExternal={includeExternal} />
          ))}
          {externals.map((e, i) => (
            <li key={`ext-${path}-${i}`} style={{ listStyle: 'none', padding: '2px 6px', fontSize: 10, color: 'var(--text-muted)' }}>
              <span style={{ fontFamily: 'monospace' }}>{e?.name}</span>{' '}
              <em>[{e?.header || '?'} | {e?.library || '?'}]</em>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function CallTreeView({ job, cacheRoot, buildSelector, sourceRoot, seedFns, toast }) {
  const [entry, setEntry] = useState('');
  const [depth, setDepth] = useState(5);
  const [includeExternal, setIncludeExternal] = useState(false);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(() => new Set());
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const toggle = useCallback((id) => {
    setExpanded(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  }, []);

  const load = useCallback(async () => {
    const entries = String(entry || '').split(/[\n,]/).map(s => s.trim()).filter(Boolean);
    if (!entries.length) { toast('warning', '진입 함수명을 입력하세요 (예: main).'); return; }
    setLoading(true);
    try {
      const res = await post('/api/jenkins/call-tree', {
        job_url: job?.url || '',
        cache_root: cacheRoot || '.devops_pro_cache',
        build_selector: buildSelector || 'lastSuccessfulBuild',
        source_root: sourceRoot || '',
        entry: entries.join(','),
        max_depth: Math.max(1, Math.min(20, Number(depth) || 5)),
        include_external: includeExternal,
        engine: 'precise',
      });
      if (!mountedRef.current) return;
      setData(res);
      setExpanded(new Set());
      const miss = Array.isArray(res?.missing) ? res.missing : [];
      const st = res?.stats || {};
      if (miss.length) {
        toast('warning', `미발견 함수 ${miss.length}개: ${miss.slice(0, 5).join(', ')}${miss.length > 5 ? '…' : ''} — 빌드 소스의 함수명과 정확히 일치해야 합니다.`);
      } else {
        toast('success', `콜트리 생성 (${st.engine || '?'} · 함수 ${st.functions ?? 0} · 엣지 ${st.edges ?? 0})`);
      }
    } catch (e) {
      if (mountedRef.current) toast('error', `콜트리 생성 실패: ${e.message}`);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [entry, depth, includeExternal, job, cacheRoot, buildSelector, sourceRoot, toast]);

  const trees = Array.isArray(data?.trees) ? data.trees : [];
  const st = data?.stats || {};

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
        <button type="button" onClick={load} disabled={loading}
          style={{ padding: '6px 14px', fontSize: 12, fontWeight: 600, border: 'none', borderRadius: 4, cursor: loading ? 'default' : 'pointer',
            background: loading ? 'var(--border)' : 'var(--accent)', color: '#fff' }}>
          {loading ? '분석 중…' : '콜트리 생성'}
        </button>
      </div>

      {!data && !loading && (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 4px' }}>
          진입 함수명을 입력하고 <strong>콜트리 생성</strong>을 누르면 tree-sitter로 분석한 함수 호출 트리를 보여줍니다.
          매트릭스가 로드돼 있으면 입력란에서 설계 함수명 자동완성을 제안합니다.
        </div>
      )}

      {data && (
        <div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
            <span>엔진 <strong style={{ color: st.engine === 'tree-sitter' ? '#16a34a' : '#d97706' }}>{st.engine || '?'}</strong></span>
            <span>스캔 파일 {st.files_scanned ?? 0}</span>
            <span>함수 {st.functions ?? 0}</span>
            <span>호출 엣지 {st.edges ?? 0}</span>
            {Array.isArray(data.missing) && data.missing.length > 0 && (
              <span style={{ color: '#d97706' }}>미발견 {data.missing.length}</span>
            )}
          </div>
          {trees.length === 0 ? (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 12, textAlign: 'center', border: '1px dashed var(--border)', borderRadius: 6 }}>
              표시할 호출 트리가 없습니다.
              {Array.isArray(data.missing) && data.missing.length > 0 && (
                <> 입력한 함수({data.missing.join(', ')})를 빌드 소스에서 찾지 못했습니다 — 함수명/소스 캐시를 확인하세요.</>
              )}
            </div>
          ) : (
            <ul style={{ margin: 0, padding: 0 }}>
              {trees.map((t, i) => (
                <CallTreeNode key={i} node={t} path={`${i}`} expanded={expanded} onToggle={toggle} depth={0} includeExternal={includeExternal} />
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/* ── 요구사항 상하위 추적 그래프 (additive '그래프' 뷰) ──
   요구사항 1개를 선택하면 그 하위 추적(SDS→UDS→STS/SUTS/SITS→VectorCAST)을 레벨별 SVG
   노드-엣지 그래프로 보여준다. hiMA UCOneIDTrace(요구사항 ID 의존성 그래프)의 child 방향에
   대응 — hiMA의 MSAGL Sugiyama 대신 레벨이 7컬럼으로 고정이라 컬럼 배치로 단순화(레이아웃 엔진 불필요).
   데이터는 matrix row만으로 완결(백엔드 무변경): _stageMembers(단계 멤버) + _unitTestMap(UDS함수↔
   SUTS단위시험 정확 매핑 엣지). 상위(부모 요구사항)는 row에 구조화 데이터가 없어(설계서 prose에 묻힘)
   이번 범위에서 제외 — 하위 추적에 집중. 모든 시각화는 SVG(innerHTML 없음 → XSS 무관). */
const _STAGE_COLORS = { SDS: '#0d9488', UDS: '#7c3aed', STS: '#2563eb', SUTS: '#0891b2', SITS: '#db2777', VectorCAST: '#ea580c' };
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
function _buildReqGraph(row, focusSet) {
  const G = _GRAPH;
  const reqId = _reqGraphId(row) || '(이름없음)';
  const reqName = String(row?.requirement_name ?? '').trim();
  const asil = String(row?.asil ?? row?.requirement_asil ?? row?.ASIL ?? '').trim().toUpperCase();
  const fset = focusSet instanceof Set && focusSet.size ? focusSet : null;

  // 단계별 멤버(캡 적용 — 시험 수십 개 컬럼이 무한정 길어지는 것 방지)
  const columns = TREE_STAGES.map((s, ci) => {
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
  const width = (TREE_STAGES.length + 1) * G.COL_W;

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
      reqEdges.push({ from: '__root__', to: m.id, color: _STAGE_COLORS[col.stage] || '#9ca3af', kind: 'req' });
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

  return { reqId, reqName, asil, columns, edges, width, height, nodeXY, rootY };
}

function _bez(x1, y1, x2, y2) {
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
}

// 그래프 노드 1개 (root/단계 공용). label은 truncate, 전체는 <title> 툴팁.
// active=hover/선택 강조(dim), kbFocused=키보드 포커스 링(dim과 분리), node.impacted=영향도 변경함수.
function ReqGraphNode({ node, color, active, kbFocused, onClick, onHover, onFocus, onBlur }) {
  const G = _GRAPH;
  const label = String(node.label || '');
  const shown = label.length > 20 ? label.slice(0, 19) + '…' : label;
  const impacted = !!node.impacted;
  return (
    <g transform={`translate(${node.x},${node.y})`} style={{ cursor: 'pointer' }} opacity={active ? 1 : 0.28}
      role="button" tabIndex={0} aria-label={impacted ? `${label} (변경 영향 함수)` : label}
      onClick={onClick}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick?.(); } }}
      onMouseEnter={() => onHover?.(node.id)} onMouseLeave={() => onHover?.(null)}
      onFocus={() => onFocus?.(node.id)} onBlur={() => onBlur?.()}>
      <title>{impacted ? `${label} — 변경 영향 함수(영향도 연동)` : label}</title>
      {kbFocused && <rect x={-3} y={-3} width={G.NODE_W + 6} height={G.NODE_H + 6} rx={8} fill="none" stroke="#2563eb" strokeWidth={2} strokeDasharray="3 2" />}
      <rect width={G.NODE_W} height={G.NODE_H} rx={6} style={{ fill: 'var(--bg-elevated, #ffffff)' }}
        stroke={impacted ? '#b45309' : color} strokeWidth={impacted ? 3 : (node.isRoot ? 2.5 : 1.5)} />
      <rect width={5} height={G.NODE_H} rx={2} fill={color} />
      {impacted && <circle cx={G.NODE_W - 9} cy={9} r={4} fill="#b45309" />}
      <text x={12} y={G.NODE_H / 2 + 4} fontSize={11} fontWeight={node.isRoot || impacted ? 700 : 500} style={{ fill: 'var(--fg)' }}>{shown}</text>
    </g>
  );
}

function TraceReqGraphView({ rows, focusFunctions = null }) {
  const list = useMemo(() => (Array.isArray(rows) ? rows.filter(r => _reqGraphId(r)) : []), [rows]);
  const [selId, setSelId] = useState('');
  const [selNode, setSelNode] = useState(null);
  const [hoverId, setHoverId] = useState(null);
  const [focusId, setFocusId] = useState(null); // 키보드 포커스(강조 dim과 분리)

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

  const graph = useMemo(() => (selectedRow ? _buildReqGraph(selectedRow, focusSet) : null), [selectedRow, focusSet]);

  // 표시 그래프 교체 시 노드 상세/hover/focus 리셋 — selId가 아니라 graph에 묶는다.
  // (selId='' 첫항목 폴백 상태에서 부모 filter 변경으로 list[0]=다른 요구사항이 돼도
  //  graph 참조가 바뀌므로 stale selNode/유령 dimming을 차단. graph는 selectedRow 메모.)
  useEffect(() => { setSelNode(null); setHoverId(null); setFocusId(null); }, [graph]);

  // hover/선택 강조는 키보드 focus와 분리(focusId는 dim 트리거 안 함 — Tab 순회 깜빡임 방지).
  const activeNodeId = hoverId || (selNode ? selNode.id : null);
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
  const headerLabels = ['요구사항', ...TREE_STAGES.map(s => s.label)];
  const isNodeActive = (id) => !activeNodeId || id === activeNodeId || neighborSet.has(id);
  const isEdgeActive = (e) => !activeNodeId || e.from === activeNodeId || e.to === activeNodeId;
  const totalHiddenFail = graph.columns.reduce((n, c) => n + (c.hiddenFail || 0), 0);
  const impactedCount = graph.columns.reduce((n, c) => n + c.members.filter(m => m.impacted).length, 0);

  return (
    <div>
      {/* 요구사항 선택 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', marginBottom: 10 }}>
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
      </div>

      {graph && (
        <>
          {/* 요약 + 범례 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 11, color: 'var(--text-muted)', marginBottom: 8, alignItems: 'center' }}>
            <span><strong style={{ color: 'var(--fg)' }}>{graph.reqId}</strong>{graph.reqName ? ` — ${graph.reqName}` : ''}</span>
            {graph.asil && <span style={{ padding: '1px 7px', borderRadius: 10, background: (_ASIL_COLORS[graph.asil] || '#6b7280'), color: '#fff', fontWeight: 700 }}>ASIL {graph.asil}</span>}
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
          </div>

          {/* SVG 그래프 */}
          <div style={{ overflow: 'auto', border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg)', maxHeight: 580 }}>
            <svg width={graph.width} height={graph.height} style={{ display: 'block', minWidth: '100%' }} role="group" aria-label={`${graph.reqId} 하위 추적 그래프`}>
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
                // 초기(미선택) 상태에선 req 엣지를 옅게 깔아 hairball 밀도를 낮추고(unit 매핑은 약간 진하게),
                // hover/선택 시 관련 엣지만 0.55/0.9로 부각, 무관 엣지는 0.06으로 후퇴.
                const op = active
                  ? (e.kind === 'unit' ? 0.9 : 0.55)
                  : (activeNodeId ? 0.06 : (e.kind === 'unit' ? 0.5 : 0.16));
                return <path key={i} d={_bez(x1, y1, x2, y2)} fill="none"
                  stroke={e.kind === 'unit' ? '#2563eb' : e.color}
                  strokeWidth={e.kind === 'unit' ? 2 : 1.2}
                  strokeDasharray={e.kind === 'unit' ? '4 2' : undefined}
                  opacity={op} />;
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
