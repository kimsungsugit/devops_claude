import React, { useState, useEffect, useCallback } from 'react';
import { api, authHeaders, toApiError } from '../../api.js';
import { useToast } from '../../App.jsx';

// FormData(multipart) POST — api() 헬퍼는 JSON 전용이라 raw fetch 유지하되
// auth 헤더는 authHeaders()(Bearer + X-User)로 붙인다. X-User 만 보내면 커밋 1b6bb99
// (2026-08-04) 이후 UserContextMiddleware 가 401 로 막는다.
// (R97) 실패에 HTTP 상태와 서버 사유(detail)를 싣는다 — 409(같은 프로젝트에 맵이 이미 있음)를 덮어쓰기 확인으로 바꿔
// 다시 보내려면 상태가 필요하고, 422(행 0개)·400(문서 못 엶)은 사유가 없으면 사용자가 고칠 곳을 모른다.
const post = async (url, body) => {
  const res = await fetch(url, {
    method: 'POST',
    body,
    headers: authHeaders(),
  });
  if (!res.ok) {
    // (R97 리뷰2 I-i · 리뷰3 W1) 409 · 422 의 갈래는 **표지로** 고른다(문구가 바뀌어도 안 깨지게). 실서버 본문은 전역 핸들러
    //   봉투 `{ok:false, error:{message, detail:{reason_code, roots_moved, key}}}` 다 — `j.detail` 만 읽던 예전 판은 실서버에서
    //   사유 · 표지를 다 잃어, 루트만 바뀐 HD 맵을 맨 "409 Conflict … 덮어쓸까요?" 로 덮게 했다. 해석은 api.js 와 같은
    //   `toApiError`(봉투 우선, FastAPI 기본 `{detail}` 폴백).
    const err = await toApiError(res);
    const info = err.detail && typeof err.detail === 'object' ? err.detail : {};
    err.reasonCode = typeof info.reason_code === 'string' ? info.reason_code : '';
    err.rootsMoved = info.roots_moved === true;
    err.key = typeof info.key === 'string' ? info.key : '';
    throw err;
  }
  return res.json();
};

// (R97 리뷰 W6) 맵 쓰기는 관리자 전용이다(프로젝트 맵이 ASIL · 시험 범위의 근거). 401/403 은 "생성 실패" 가 아니라 권한 문제라고
// 말해야 사용자가 문서 · 경로를 의심하며 헤매지 않는다.
const failText = (e) => {
  if (e?.status === 403 || e?.status === 401) {
    return '관리자만 프로젝트 맵을 만들거나 루트를 다시 등록할 수 있습니다 — 관리자 계정으로 로그인하세요';
  }
  return `생성 실패: ${e?.message || ''}`;
};

// 맵 판정(백엔드 `report_gen.project_maps`)의 상태 → 화면 문구. 값이 없으면 미생성으로 둔다(지어내지 않는다).
const STATUS_KO = {
  applied: '적용',
  none: '이 프로젝트 맵 없음',
  not_this_project: '다른 프로젝트 맵만 있음',
  ambiguous: '프로젝트 모호',
  invalid: '맵 손상',
  no_roots: '소스 루트를 넣으면 판정',
};

// 맵이 안 걸릴 때 — "미생성" 아래에 판정과 사유를 적는다(남의 맵만 있다 · 모호 · 손상은 사람이 고칠 일이다).
function MapAbsent({ info }) {
  const st = info?.status;
  return (
    <>
      <div style={{ fontSize: 14, color: 'var(--color-warning)' }}>미생성</div>
      {st && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }} title={info?.reason || ''}>
          {STATUS_KO[st] || st}{info?.reason ? ` — ${info.reason}` : ''}
        </div>
      )}
    </>
  );
}

export default function ProjectSetupSection() {
  // toast는 prop이 아닌 useToast() 컨텍스트에서 — Detail은 toast prop을 넘기지 않아
  // 기존 toast prop은 항상 undefined(no-op)였다. 컨텍스트 직접 사용으로 정상화.
  const toast = useToast();
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sdsPath, setSdsPath] = useState('');
  const [sourceRoot, setSourceRoot] = useState('');
  const [refUdsPath, setRefUdsPath] = useState('');

  // (R97) 상태는 **이 소스 루트의 프로젝트**에 걸릴 맵이다(루트 없이 부르면 등록 목록만). 타이핑마다 부르지 않는다 —
  // 마운트 때 한 번, 생성 직후 그 루트로 한 번.
  const loadStatus = useCallback(async (root = '') => {
    try {
      // api() 헬퍼 — X-User 자동 + res.ok 검사. 이전 raw fetch는 401 silent fail.
      const qs = root ? `?source_root=${encodeURIComponent(root)}` : '';
      const data = await api(`/api/local/project-setup/status${qs}`);
      setStatus(data);
    } catch { /* ignore — status 로드 실패는 비치명 */ }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  // 409(같은 프로젝트에 같은 맵이 있음) → 사람이 확인하면 overwrite=true 로 한 번 더. 옛 파일은 서버가 .prev 로 남긴다.
  // (R97 리뷰 W7 · 리뷰2 I-i) 소스 루트만 바뀐 경우 서버가 `roots_moved: true` 표지를 싣는다 — 그때 덮어쓰면 손으로 정한 verify=X 가
  //   사라지므로 확인 문구가 '루트 다시 등록' 길을 먼저 말한다. 갈래는 서버 문구가 아니라 표지로 고른다.
  const postWithOverwrite = async (url, form, what) => {
    try {
      return await post(url, form);
    } catch (e) {
      if (e?.status !== 409 || e?.reasonCode === 'manifest_unreadable') throw e;   // 덮어쓰기로 풀리지 않는 409
      const ask = e.rootsMoved
        ? `${e.message}\n\n소스 루트만 바뀐 것이면 [취소] 후 '루트 다시 등록' 을 쓰세요. 그래도 ${what} 를 새로 만들어 덮어쓸까요? (옛 파일은 .prev 로 백업)`
        : `${e.message}\n\n${what} 를 덮어쓸까요? (옛 파일은 .prev 로 백업)`;
      if (!window.confirm(ask)) return null;
      form.set('overwrite', 'true');
      return post(url, form);
    }
  };

  // (R97 리뷰 W7) 맵은 그대로 두고 매니페스트 루트만 레지스트리 루트로 — 레지스트리 루트가 바뀌어 맵이 안 걸릴 때
  const updateRoots = async () => {
    if (!sourceRoot) {
      toast?.('warning', '소스 루트를 입력하세요');
      return;
    }
    setLoading(true);
    try {
      const form = new FormData();
      form.append('source_root', sourceRoot);
      const result = await post('/api/local/project-setup/update-roots', form);
      toast?.('success', `루트 다시 등록: ${result.key} (${(result.roots_after || []).join(', ')})`);
      loadStatus(sourceRoot);
    } catch (e) {
      toast?.('error', failText(e).replace('생성 실패', '루트 등록 실패'));
    }
    setLoading(false);
  };

  // 생성 결과가 루트 판정으로 안 걸리는 맵이면(매니페스트 루트가 이 루트를 못 담음) 성공 토스트만 두지 않는다
  const warnIfNotCovered = (result) => {
    if (result && result.roots_covered === false) {
      toast?.('warning', '맵은 썼지만 매니페스트 루트가 이 소스 루트를 담지 않아 루트로는 걸리지 않습니다 — \'루트 다시 등록\' 을 확인하세요');
    }
  };

  const generateComponentMap = async () => {
    if (!sdsPath || !sourceRoot) {
      toast?.('warning', 'SDS 경로와 소스 루트를 입력하세요');
      return;
    }
    setLoading(true);
    try {
      const form = new FormData();
      form.append('sds_path', sdsPath);
      form.append('source_root', sourceRoot);
      const result = await postWithOverwrite('/api/local/project-setup/generate-component-map', form, 'component_map');
      if (result) {
        const how = result.method === 'structure_table' ? 'SDS 구조 표' : 'SDS 파티션 이름 매칭(구조 표 없음)';
        const proj = result.project_map?.key ? ` → ${result.project_map.key}` : '';
        toast?.('success', `component_map 생성(${how}): ${result.stats?.matched || 0}개 매핑${proj}`);
        warnIfNotCovered(result);
      }
      loadStatus(sourceRoot);
    } catch (e) {
      toast?.('error', failText(e));
    }
    setLoading(false);
  };

  const generateOverride = async () => {
    if (!refUdsPath) {
      toast?.('warning', '레퍼런스 UDS 경로를 입력하세요');
      return;
    }
    // (R97) 어느 프로젝트의 맵인지 정할 근거 — 서버도 없으면 400 이다
    if (!sourceRoot) {
      toast?.('warning', '소스 루트를 입력하세요 — override 가 어느 프로젝트의 것인지 정합니다');
      return;
    }
    setLoading(true);
    try {
      const form = new FormData();
      form.append('uds_path', refUdsPath);
      form.append('source_root', sourceRoot);
      const result = await postWithOverwrite('/api/local/project-setup/generate-override', form, 'override');
      if (result) {
        toast?.('success', `override 생성: ${result.stats?.total_functions || 0}개 함수`);
        warnIfNotCovered(result);
      }
      loadStatus(sourceRoot);
    } catch (e) {
      toast?.('error', failText(e));
    }
    setLoading(false);
  };

  const projects = Array.isArray(status?.projects) ? status.projects : [];
  const rootsMoved = status?.roots_moved || null;

  const inputStyle = {
    width: '100%', padding: '8px 12px', fontSize: 13,
    border: '1px solid var(--border)', borderRadius: 6,
    background: 'var(--bg)', color: 'var(--fg)',
  };

  return (
    <div style={{ padding: 16 }}>
      <h3 style={{ marginBottom: 16 }}>프로젝트 설정 (ISO 26262 문서 생성 준비)</h3>

      {/* Status */}
      {status && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
          <div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>component_map.json</div>
            {status.component_map?.exists ? (
              <>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-success)' }}>
                  {status.component_map.entries}개
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  verify=O: {status.component_map.verify_o} / verify=X: {status.component_map.verify_x}
                </div>
              </>
            ) : (
              <MapAbsent info={status.component_map} />
            )}
          </div>
          <div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>override.json (함수 단위)</div>
            {status.override?.exists ? (
              <>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-success)' }}>
                  {status.override.functions}개
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  ASIL: {status.override.with_asil} / SwCom: {status.override.swcom_count}개
                </div>
              </>
            ) : (
              <MapAbsent info={status.override} />
            )}
          </div>
        </div>
      )}

      {/* (R97 리뷰 W7) 이 루트의 프로젝트 맵이 있는데 매니페스트 루트가 지금 루트를 못 담는다 — 맵이 아니라 루트를 다시 등록할 일 */}
      {rootsMoved && (
        <div role="alert" style={{ marginBottom: 16, padding: 12, border: '1px solid var(--color-warning)', borderRadius: 8 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--color-warning)', marginBottom: 4 }}>
            프로젝트 {rootsMoved.key} 의 맵이 이 소스 루트에 걸리지 않습니다 (roots_covered=false)
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>{rootsMoved.hint}</div>
          <button className="btn-secondary" onClick={updateRoots} disabled={loading}>루트 다시 등록</button>
        </div>
      )}

      {/* (R97) 등록된 프로젝트 맵 — 맵은 그 프로젝트(소스 루트 · SCM id)에만 걸린다 */}
      {projects.length > 0 && (
        <div style={{ marginBottom: 20, fontSize: 12, color: 'var(--text-muted)' }}>
          <div style={{ marginBottom: 4 }}>등록된 프로젝트 맵 (docs/project_maps)</div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {projects.map(p => (
              <li key={p.key}>
                {p.project || p.key}
                {p.scm_id ? ` (${p.scm_id})` : ''}
                {' — '}
                {Object.keys(p.maps || {}).length
                  ? Object.entries(p.maps || {}).map(([k, m]) => `${k} ${STATUS_KO[m?.status] || m?.status || '—'}`).join(' · ')
                  : '맵 없음'}
                {p.roots_covered === false ? ' — 이 소스 루트를 담지 않음(roots_covered=false)' : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Generate Component Map */}
      <div style={{ marginBottom: 20, padding: 16, border: '1px solid var(--border)', borderRadius: 8 }}>
        <h4 style={{ marginBottom: 12 }}>1. Component Map 생성 (SDS 기반)</h4>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          SDS 문서에서 파일-to-SwCom 매핑을 자동 추출합니다. UDS/SUTS/STS/SITS 생성 시 SwCom 분배에 사용됩니다.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            style={inputStyle} placeholder="SDS 문서 경로 (예: D:\docs\SDS.docx)"
            value={sdsPath} onChange={e => setSdsPath(e.target.value)}
          />
          <input
            style={inputStyle} placeholder="소스 루트 경로 (예: D:\Project\Ados\PDS64_RD,D:\Project\Ados\PDS64_FBL)"
            value={sourceRoot} onChange={e => setSourceRoot(e.target.value)}
          />
          <button className="btn-primary" onClick={generateComponentMap} disabled={loading}>
            {loading ? '생성 중...' : 'Component Map 생성'}
          </button>
        </div>
      </div>

      {/* Generate Override */}
      <div style={{ padding: 16, border: '1px solid var(--border)', borderRadius: 8 }}>
        <h4 style={{ marginBottom: 12 }}>2. Override Map 생성 (레퍼런스 UDS 기반)</h4>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          기존 UDS 문서에서 함수별 SwCom/ASIL/Related ID를 역추출합니다. 새 UDS/SUTS 생성 시 100% 정확도를 위해 사용됩니다.
          레퍼런스 UDS가 없으면 생략 가능합니다 (SDS 기반 자동 할당).
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            style={inputStyle} placeholder="레퍼런스 UDS 경로 (예: D:\docs\UDS.docx)"
            value={refUdsPath} onChange={e => setRefUdsPath(e.target.value)}
          />
          <button className="btn-primary" onClick={generateOverride} disabled={loading}>
            {loading ? '생성 중...' : 'Override Map 생성'}
          </button>
        </div>
      </div>
    </div>
  );
}
