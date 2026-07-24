/**
 * traceMatrix.js — 추적성 매트릭스 생성 orchestration(프로젝트 요약 탭 자동생성용).
 *
 * SrsSdsSection의 buildMatrix와 동일한 fetch 시퀀스(requirements-preview → uds/sds/hsis
 * extract-mapping → sts/suts/sits/syts/syits extract-traceability → vectorcast-rag →
 * traceability-matrix)를 자립 함수로 옮겼다. ⚠ 매트릭스 '계산'은 서버측(generate_uds_
 * traceability_matrix)이라 입력만 충실히 모으면 SrsSdsSection과 동일 결과 + 동일 캐시
 * (trace_matrix_summary.json)를 만든다. SrsSdsSection은 건드리지 않는다(임계 탭 회귀 0).
 *
 * traceability-matrix 호출은 서버에서 trace_matrix_summary.json을 부작용으로 캐시하므로,
 * 요약 탭은 이 함수 호출 후 trace-summary를 재조회하면 된다(영속 → 재방문 시 재생성 없음).
 */
import { post, getUsername, buildUrl } from './api.js';

const FAIL_R = new Set(['fail', 'failed', 'false', '0', 'ng']);

// linked_docs → 문서 경로 묶음. vectorcast는 배열(복수 폴더), 나머지는 문자열 경로.
function _docs(linkedDocs) {
  const d = linkedDocs || {};
  return {
    srs: d.srs || '', uds: d.uds || '', sds: d.sds || '', hsis: d.hsis || '', syrs: d.syrs || '',
    sts: d.sts || '', suts: d.suts || '', sits: d.sits || '', syts: d.syts || '', syits: d.syits || '',
    vectorcast: Array.isArray(d.vectorcast) ? d.vectorcast.filter(Boolean) : [],
  };
}

/**
 * 추적성 매트릭스를 생성한다(입력 수집 → 서버 traceability-matrix). 캐시 부작용으로 영속된다.
 * @returns {Promise<{ok:boolean, matrix?:object, warnings:string[], dataSources:string[], reason?:string}>}
 */
export async function buildTraceMatrix({ linkedDocs, sourceRoot = '', jobUrl = '', cacheRoot = '.devops_pro_cache', buildSelector = 'lastSuccessfulBuild' }, { onProgress } = {}) {
  const docs = _docs(linkedDocs);
  const warnings = [];
  const dataSources = [];
  const progress = (m) => { try { onProgress?.(m); } catch { /* ignore */ } };

  // Step 1: SRS 요구사항(멀티파트 — FormData/raw fetch, JSON post 헬퍼로 못 보냄. X-User + res.ok 명시).
  progress('요구사항 추출 중...');
  let reqItems = [];
  let mappingPairs = [];
  let udsFunctionIds = [];
  let udsFunctionAsil = {};
  try {
    const form = new FormData();
    if (docs.srs) form.append('req_paths', docs.srs);
    if (sourceRoot) form.append('source_root', sourceRoot);
    const user = getUsername();
    const res = await fetch(buildUrl('/api/jenkins/uds/requirements-preview'), {
      method: 'POST', body: form, headers: user ? { 'X-User': user } : {},
    });
    if (res.ok) {
      const data = await res.json();
      reqItems = data?.preview?.items || [];
      mappingPairs = data?.traceability?.mapping_pairs || data?.mapping || [];
    } else {
      warnings.push(`요구사항 미리보기 실패: HTTP ${res.status}`);
    }
  } catch (e) {
    warnings.push(`요구사항 미리보기 실패: ${e.message}`);
  }

  // Step 2a: UDS 함수 매핑
  progress('UDS 함수 매핑 추출 중...');
  if (mappingPairs.length === 0 && docs.uds) {
    try {
      const uds = await post('/api/jenkins/uds/extract-mapping', { uds_path: docs.uds });
      mappingPairs = uds?.mapping_pairs || [];
      udsFunctionIds = uds?.all_function_ids || [];
      udsFunctionAsil = uds?.uds_function_asil || {};
    } catch (e) { warnings.push(`UDS 매핑 추출 실패: ${e.message}`); }
  }

  // Step 2b: SDS 컴포넌트 매핑 + ASIL
  let sdsPairs = [];
  let componentAsil = {};
  if (docs.sds) {
    progress('SDS 컴포넌트 매핑 추출 중...');
    try {
      const sds = await post('/api/jenkins/sds/extract-mapping', { sds_path: docs.sds });
      sdsPairs = sds?.sds_pairs || [];
      componentAsil = sds?.component_asil || {};
      if (sdsPairs.length) dataSources.push(`SDS: ${sdsPairs.length}개 매핑`);
    } catch (e) { warnings.push(`SDS 매핑 추출 실패: ${e.message}`); }
  }

  // Step 2c: HSIS 인터페이스 매핑
  let hsisPairs = [];
  if (docs.hsis) {
    progress('HSIS 인터페이스 매핑 추출 중...');
    try {
      const hsis = await post('/api/jenkins/hsis/extract-mapping', { hsis_path: docs.hsis, syrs_path: docs.syrs });
      hsisPairs = hsis?.hsis_pairs || [];
      if (hsisPairs.length) dataSources.push(`HSIS: ${hsisPairs.length}개 인터페이스`);
    } catch (e) { warnings.push(`HSIS 매핑 추출 실패: ${e.message}`); }
  }

  // Step 3: 시험 추적성 — STS/SUTS/SITS/SyTS/SyITS(exact) + VectorCAST(fuzzy)
  const vcastRows = [];
  let sitsRows = [];
  for (const [key, ep, label] of [
    ['sts', '/api/jenkins/sts/extract-traceability', 'STS'],
    ['suts', '/api/jenkins/suts/extract-traceability', 'SUTS'],
  ]) {
    if (!docs[key]) continue;
    progress(`${label} 추적성 추출 중...`);
    try {
      const body = key === 'sts' ? { path: docs.sts, doc_type: 'sts' } : { path: docs[key] };
      const data = await post(ep, body);
      if (data?.warning) warnings.push(`${label}: ${data.warning}`);
      if (data?.vcast_rows?.length) {
        for (const row of data.vcast_rows) vcastRows.push({ ...row, source: row.source || label, confidence: 'exact' });
        dataSources.push(`${label}: ${data.vcast_rows.length}건`);
      } else if (Array.isArray(data?.available_sheets)) {
        warnings.push(`${label}: ${data.error || '시트 미인식'}. 사용 가능한 시트: ${data.available_sheets.join(', ')}`);
      }
    } catch (e) { warnings.push(`${label} 추출 실패: ${e.message}`); }
  }
  // SITS(요구열 유무 구분)
  if (docs.sits) {
    progress('SITS 추적성 추출 중...');
    try {
      const data = await post('/api/jenkins/sits/extract-traceability', { path: docs.sits });
      if (data?.vcast_rows?.length) {
        sitsRows = data.vcast_rows.map(r => ({ ...r, source: r.source || 'SITS', confidence: 'exact' }));
        const directN = data.vcast_rows.filter(r => r.requirement_id).length;
        dataSources.push(`SITS: ${data.vcast_rows.length}건${directN > 0 ? '' : '(요구열 없음·2-hop 의존)'}`);
        if (directN === 0 && data.warning) warnings.push(`SITS: ${data.warning}`);
      } else if (Array.isArray(data?.available_sheets)) {
        warnings.push(`SITS: ${data.warning || data.error || '시트 미인식'}. 사용 가능한 시트: ${data.available_sheets.join(', ')}`);
      }
    } catch (e) { warnings.push(`SITS 추출 실패: ${e.message}`); }
  }
  // SyTS/SyITS(시스템 시험 — SITS와 동일 구조, source 라벨만)
  for (const [key, ep, label] of [
    ['syts', '/api/jenkins/syts/extract-traceability', 'SyTS'],
    ['syits', '/api/jenkins/syits/extract-traceability', 'SyITS'],
  ]) {
    if (!docs[key]) continue;
    progress(`${label} 추적성 추출 중...`);
    try {
      const data = await post(ep, { path: docs[key], syrs_path: docs.syrs });
      if (data?.vcast_rows?.length) {
        for (const row of data.vcast_rows) vcastRows.push({ ...row, source: row.source || label, confidence: 'exact' });
        dataSources.push(`${label}: ${data.vcast_rows.length}건`);
      } else if (Array.isArray(data?.available_sheets)) {
        warnings.push(`${label}: ${data.warning || data.error || '시트 미인식'}. 사용 가능한 시트: ${data.available_sheets.join(', ')}`);
      }
    } catch (e) { warnings.push(`${label} 추출 실패: ${e.message}`); }
  }

  // Step 3d: VectorCAST(함수 단위 롤업, fuzzy) — SUTS와 동일 granularity로.
  progress('VectorCAST 데이터 수집 중...');
  try {
    const rag = await post('/api/jenkins/report/vectorcast-rag', {
      job_url: jobUrl, cache_root: cacheRoot, build_selector: buildSelector, vcast_log_paths: docs.vectorcast,
    });
    const rawRows = rag?.data?.test_rows || [];
    const vcWarnings = rag?.data?.parse_warnings || rag?.parse_warnings || [];
    if (!rawRows.length && Array.isArray(vcWarnings) && vcWarnings.length) {
      const head = vcWarnings.slice(0, 3).join(' / ');
      warnings.push(`VectorCAST: ${head}${vcWarnings.length > 3 ? ` 외 ${vcWarnings.length - 3}건` : ''}`);
    }
    const byFunc = new Map();
    for (const row of rawRows) {
      const sub = (row.subprogram || '').trim();
      if (!sub) continue;
      const res = String(row.result || '').toLowerCase();
      let agg = byFunc.get(sub);
      if (!agg) { agg = { sub, report: row.report || '', unit: row.unit || '', tc: 0, fail: 0 }; byFunc.set(sub, agg); }
      agg.tc += 1;
      if (FAIL_R.has(res)) agg.fail += 1;
    }
    let added = 0;
    for (const agg of byFunc.values()) {
      const label = agg.tc > 1 ? `${agg.sub} (${agg.tc} TC${agg.fail ? `, ${agg.fail} fail` : ''})` : agg.sub;
      vcastRows.push({ subprogram: agg.sub, testcase: label, result: agg.fail > 0 ? 'fail' : 'pass', unit: agg.unit, report: agg.report, requirement_id: '', source: 'VectorCAST', confidence: 'fuzzy' });
      added++;
    }
    if (added > 0) dataSources.push(`VectorCAST: ${added}개 함수`);
  } catch (e) { warnings.push(`VectorCAST 수집 실패: ${e.message}`); }

  if (reqItems.length === 0) {
    return { ok: false, warnings: [...warnings, 'SRS에서 요구사항을 추출하지 못했습니다. SRS 경로를 확인하세요.'], dataSources, reason: 'no_requirements' };
  }

  // Step 4: 서버 매트릭스 생성(계산은 서버측 — 캐시 trace_matrix_summary.json 부작용).
  progress(`매트릭스 생성 중 (${reqItems.length}개 요구사항)...`);
  try {
    const data = await post('/api/jenkins/uds/traceability-matrix', {
      requirement_items: reqItems,
      mapping_pairs: mappingPairs,
      uds_function_ids: udsFunctionIds,
      vcast_rows: vcastRows,
      sds_pairs: sdsPairs,
      hsis_pairs: hsisPairs,
      sits_rows: sitsRows,
      component_asil: componentAsil,
      uds_function_asil: udsFunctionAsil,
      job_url: jobUrl,
      cache_root: cacheRoot,
      build_selector: buildSelector,
    });
    return { ok: true, matrix: data?.matrix || data, warnings, dataSources };
  } catch (e) {
    return { ok: false, warnings: [...warnings, `매트릭스 생성 실패: ${e.message}`], dataSources, reason: 'matrix_failed' };
  }
}
