// 문서 작성급 초안 표 — 순수 프레젠테이션.
//
// ImpactGuideSection.jsx가 3500줄이 넘어 표·확장·마커·TSV를 그 안에 더 얹을 수 없어 분리했다.
// 판정(유지/값수정/신규추가)은 전부 `src/impactDocDraft.js`가 결정하고 여기서는 그리기만 한다.
//
// ⚠ 정직성 표시 규약
//   - 근거(TC·행)가 없으면 빈 칸으로 둔다. 행 번호를 지어내지 않는다.
//   - 원문에 없는 값은 '현재' 칸을 비운다(임의 행을 끌어다 쓰지 않는다).
//   - 절단이 있으면 '총 N건 중 M건'을 항상 노출한다(침묵 절단 금지).
//   - `[검증 필요]` 마커는 생성기 표기 그대로 통과시킨다.

import { useState } from 'react';
import { VERDICT, buildTsv, normalizeNumeric } from '../../../impactDocDraft.js';

const PREVIEW_ROWS = 3;

const VERDICT_TONE = {
  [VERDICT.KEEP]: 'neutral',
  [VERDICT.RECHECK]: 'warning',
  [VERDICT.MODIFY]: 'warning',
  [VERDICT.ADD]: 'success',
  [VERDICT.UNKNOWN]: 'danger',
  [VERDICT.REVERIFY]: 'warning',
};

const cellStyle = { padding: '2px 4px', borderBottom: '1px solid var(--border)', verticalAlign: 'top' };
const headStyle = { ...cellStyle, fontWeight: 600, whiteSpace: 'nowrap', textAlign: 'left', color: 'var(--text-muted)' };
const monoStyle = { fontFamily: 'var(--font-mono, monospace)', fontSize: 9, overflowWrap: 'anywhere' };

function VerdictPill({ verdict }) {
  if (!verdict) return null;
  return <span className={`pill pill-${VERDICT_TONE[verdict] || 'neutral'}`} style={{ fontSize: 8 }}>{verdict}</span>;
}

// 원문값 → 제안값. 같으면 한 번만(유지), 다르면 화살표로 대비.
// ⚠ 비교는 **문자열이 아니라 수치**로 한다. 원문(`doc_content`)은 `_cap_kv`가 전부 문자열화하고,
//   생성기(`doc_proposal`)는 native int를 그대로 싣고, 경계표는 unsigned를 hex로 준다 — 세 표기가
//   섞여 있어 문자열 비교를 하면 `0`과 `0x0`에 변경 화살표가 그려진다. 그러면 판정은 '유지'인데
//   셀은 "0을 0x0으로 고쳐라"라고 말하는 자기모순이 한 행 안에서 발생한다.
function CellValue({ current, proposed }) {
  if (!current && !proposed) return <span className="text-muted">—</span>;
  if (current && proposed && current !== proposed) {
    const a = normalizeNumeric(current);
    const b = normalizeNumeric(proposed);
    if (a !== null && b !== null && a === b) {
      // 같은 값인데 표기만 다름 — 변경이 아니므로 화살표를 그리지 않고 표기 차이만 밝힌다.
      return (
        <span style={monoStyle}>
          {proposed}<span className="text-muted" style={{ fontSize: 8 }}> (원문 표기 {current})</span>
        </span>
      );
    }
    return (
      <span style={monoStyle}>
        <span style={{ color: 'var(--color-danger)' }}>{current}</span>
        {' → '}
        <span style={{ color: 'var(--color-success)' }}>{proposed}</span>
      </span>
    );
  }
  return <span style={monoStyle}>{proposed || current}</span>;
}

/**
 * @param {object} props
 * @param {string} props.title      박스 헤더(출처 라벨 포함 — '(생성기 산출)' / '(문서 원문 기준)')
 * @param {string} props.tone       색상 토큰 이름(warning=기존 문서 수정 / info=신규 작성)
 * @param {object} props.draft      impactDocDraft의 reconcile* 산출({mode, columns, rows, ...})
 * @param {Array}  props.meta       상단 메타 [{label, value}] — Component/Test Method/…
 * @param {Array}  props.notes      하단 정직성 노트 문자열 목록
 * @param {Array}  props.tsvColumns TSV 열 정의 [{key,label}] — 없으면 표 열을 그대로 쓴다
 * @param {Array}  props.tsvRows    TSV 행(평탄화) — 없으면 표 행에서 만든다
 */
export default function DocProposalTable({
  title, tone = 'warning', draft, meta, notes, tsvColumns, tsvRows, onLoadFull, loadingFull,
  prose, onEnrichProse, proseField,
}) {
  const [expanded, setExpanded] = useState(false);
  const [copyState, setCopyState] = useState('');
  const [fallbackText, setFallbackText] = useState('');

  const rows = (draft && Array.isArray(draft.rows)) ? draft.rows : [];
  if (!rows.length && !(meta || []).length) return null;
  const shown = expanded ? rows : rows.slice(0, PREVIEW_ROWS);
  const seqMode = draft.mode === 'sequence' || draft.mode === 'subcase';
  // 'tc' 모드 — 원문 통합 TC별로 "왜 다시 봐야 하는가"를 말한다(값 제안이 아니라 재검증 지시).
  const tcMode = draft.mode === 'tc';
  const columns = seqMode ? (draft.columns || []) : [];

  // TSV — 열 순서는 호출부(백엔드 문서 컬럼)가 정한다. JS에 하드코딩하지 않는다.
  const tsv = () => {
    if (Array.isArray(tsvColumns) && Array.isArray(tsvRows)) return buildTsv(tsvColumns, tsvRows);
    if (seqMode) {
      const cols = [{ key: '_label', label: '전략/케이스' }, { key: '_verdict', label: '판정' },
        { key: '_evidence', label: '근거' },
        ...columns.map((c) => ({ key: c.key, label: `${c.side === 'expected' ? 'Exp' : 'In'} ${c.name}` }))];
      // ⚠ 화면(`CellValue`)은 `proposed || current`로 그리는데 TSV가 `proposed || ''`면 **반대**가
      //   된다: 생성기가 안 채운(또는 절단된) 컬럼이 화면엔 원문값으로 보이는데 TSV엔 공란으로
      //   나가, Excel에 붙여넣는 순간 그 열의 **실제 값이 지워진다**(ISO 문서 데이터 손실).
      //   화면과 같은 폴백을 쓴다.
      const flat = rows.map((r) => ({
        _label: r.label || r.strategy || '', _verdict: r.verdict, _evidence: r.evidence || '',
        ...Object.fromEntries(columns.map((c) => {
          const cell = r.cells[c.key] || {};
          return [c.key, cell.proposed || cell.current || ''];
        })),
      }));
      return buildTsv(cols, flat);
    }
    if (tcMode) {
      return buildTsv([
        { key: 'tcId', label: 'TC ID' }, { key: 'chain', label: '통합 콜체인(원문)' },
        { key: 'method', label: 'Method' }, { key: 'precondition', label: 'Precondition' },
        { key: 'verdict', label: '판정' }, { key: 'evidence', label: '근거' },
        { key: 'focus', label: '확인할 것' },
      ], rows);
    }
    const cols = [{ key: 'variable', label: '변수' }, { key: 'type', label: '타입' },
      { key: 'boundary', label: '경계' }, { key: 'proposed', label: '제안 Input' },
      { key: 'expectedCurrent', label: '현재 Expected' }, { key: 'verdict', label: '판정' },
      { key: 'evidence', label: '근거' }];
    return buildTsv(cols, rows);
  };

  // 클립보드 3단 폴백 — 실패를 침묵시키지 않는다(각 단계 사유를 UI에 표기).
  const onCopy = async () => {
    const text = tsv();
    setFallbackText('');
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
        setCopyState('복사됨 — Excel에 붙여넣기');
        return;
      }
      throw new Error('clipboard API 사용 불가(비보안 컨텍스트)');
    } catch (e1) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        if (!ok) throw new Error('execCommand 거부');
        setCopyState('복사됨(폴백) — Excel에 붙여넣기');
      } catch (e2) {
        setCopyState(`자동 복사 실패(${e1.message} / ${e2.message}) — 아래에서 Ctrl+C`);
        setFallbackText(text);
      }
    }
  };

  const totals = draft.totals || {};
  const truncated = totals.docTotal > totals.docShown;
  // AI 서술문 — 통과한 필드만 표시하고, 폐기/실패는 **사유를 밝힌다**(침묵 금지).
  const proseText = (prose && prose.ok && (prose.fields || {})[proseField]) || '';
  const proseProblem = (() => {
    if (!prose || prose.loading) return '';
    if (prose.error) return prose.error;
    const dropped = (prose.dropped_fields || []).find((d) => d && d.field === proseField);
    if (dropped) {
      return dropped.reason === 'unknown_number'
        ? `결정론 값에 없는 수치(${dropped.token})가 포함돼 폐기 — 표의 값이 정본입니다`
        : `근거 없는 식별자(${dropped.token})가 포함돼 폐기`;
    }
    // 원시 enum을 그대로 노출하면 사용자가 다음에 무엇을 해야 할지 알 수 없다.
    if (prose.ok === false && prose.reason) return prose.reasonText || prose.reason;
    return '';
  })();

  return (
    <div style={{ fontSize: 10, marginTop: 4, padding: '4px 6px', background: 'var(--bg)', borderRadius: 4, borderLeft: `2px solid var(--color-${tone})` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 3 }}>
        <span style={{ fontWeight: 600, fontSize: 9, color: `var(--color-${tone})` }}>{title}</span>
        <button type="button" className="btn btn-ghost" style={{ fontSize: 8, padding: '1px 5px' }} onClick={onCopy}>
          📋 Excel용 TSV 복사
        </button>
        {/* 서술문만 AI 보강 — 아래 표의 **값 셀은 이 버튼으로 절대 바뀌지 않는다**(값=결정론 소유). */}
        {onEnrichProse && (
          <button type="button" className="btn btn-ghost" style={{ fontSize: 8, padding: '1px 5px' }}
            onClick={onEnrichProse} disabled={prose && prose.loading}>
            {prose && prose.loading ? '생성 중…' : '🤖 서술문 보강'}
          </button>
        )}
        {copyState && <span className="text-muted" style={{ fontSize: 8 }}>{copyState}</span>}
      </div>

      {proseText && (
        <div style={{ fontSize: 9, marginBottom: 3, padding: '2px 4px', background: 'var(--panel)', borderRadius: 3 }}>
          <span className="text-muted">시험 목적: </span>{proseText}
          <span className="pill pill-info" style={{ fontSize: 8, marginLeft: 4 }}>AI 보강</span>
        </div>
      )}
      {proseProblem && <div className="text-muted" style={{ fontSize: 9, marginBottom: 3 }}>· 서술문: {proseProblem}</div>}

      {(meta || []).length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', fontSize: 9, marginBottom: 3 }}>
          {meta.filter((m) => m && m.value).map((m) => (
            <span key={m.label}>
              <span className="text-muted">{m.label}: </span>{m.value}
              {/* 생성기 추론값은 문서 원문이 아니다 — 구분 없이 보여주면 그대로 옮겨 적힌다. */}
              {m.src === 'generator' && <span className="text-muted" style={{ fontSize: 8 }}> (추론)</span>}
            </span>
          ))}
        </div>
      )}

      {draft.callChain && (
        <div style={{ marginBottom: 3 }}>
          <div className="text-muted" style={{ fontSize: 9 }}>Call Chain</div>
          <div style={monoStyle}>{draft.callChain}</div>
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', fontSize: 9, width: '100%' }}>
            <thead>
              <tr>
                {seqMode && (
                  <>
                    <th style={headStyle}>전략/케이스</th>
                    {columns.map((c) => (
                      <th key={c.key} style={headStyle}>
                        <span className="text-muted">{c.side === 'expected' ? 'Exp ' : 'In '}</span>{c.name}
                      </th>
                    ))}
                  </>
                )}
                {tcMode && (
                  <>
                    <th style={headStyle}>TC ID</th>
                    <th style={headStyle}>통합 콜체인(원문)</th>
                    <th style={headStyle}>Method</th>
                    <th style={headStyle}>확인할 것</th>
                  </>
                )}
                {!seqMode && !tcMode && (
                  <>
                    <th style={headStyle}>변수</th>
                    <th style={headStyle}>타입</th>
                    <th style={headStyle}>경계</th>
                    <th style={headStyle}>Input 원문 → 제안</th>
                    <th style={headStyle}>현재 Expected</th>
                  </>
                )}
                <th style={headStyle}>판정</th>
                <th style={headStyle}>근거</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.key}>
                  {seqMode && (
                    <>
                      <td style={cellStyle}>
                        <div style={monoStyle}>{r.strategy || `#${r.caseNum ?? r.seqNum}`}</div>
                        {r.label && r.label !== r.strategy && <div className="text-muted">{r.label}</div>}
                        {r.precondition && <div className="text-muted">Pre: {r.precondition}</div>}
                        {/* 부분 대조·미파싱 같은 판정 한계 — 없으면 판정을 단정으로 오독한다. */}
                        {r.note && <div className="text-muted" style={{ fontSize: 8 }}>⚠ {r.note}</div>}
                      </td>
                      {columns.map((c) => (
                        <td key={c.key} style={cellStyle}><CellValue {...(r.cells[c.key] || {})} /></td>
                      ))}
                    </>
                  )}
                  {tcMode && (
                    <>
                      <td style={{ ...cellStyle, ...monoStyle, whiteSpace: 'nowrap' }}>{r.tcId || <span className="text-muted">—</span>}</td>
                      <td style={{ ...cellStyle, ...monoStyle, maxWidth: 420 }}>
                        {r.chain || <span className="text-muted">원문에 콜체인 없음</span>}
                        {r.unit && <div className="text-muted" style={{ fontSize: 8 }}>Unit: {r.unit}</div>}
                        {r.precondition && <div className="text-muted" style={{ fontSize: 8 }}>Pre: {r.precondition}</div>}
                        {r.note && <div className="text-muted" style={{ fontSize: 8 }}>⚠ {r.note}</div>}
                      </td>
                      <td style={cellStyle}>{r.method || <span className="text-muted">—</span>}</td>
                      <td style={cellStyle}>{r.focus}</td>
                    </>
                  )}
                  {!seqMode && !tcMode && (
                    <>
                      <td style={{ ...cellStyle, ...monoStyle }}>{r.variable}</td>
                      <td style={cellStyle}>
                        {r.type || <span className="text-muted">미상</span>}
                        {r.typeSource === 'name_pattern' && <div className="text-muted" style={{ fontSize: 8 }}>이름 규칙 추정</div>}
                      </td>
                      <td style={cellStyle}>{r.boundary || <span className="text-muted">—</span>}</td>
                      <td style={cellStyle}>
                        {/* ⚠ 노트가 제안값을 **대체하면 안 된다** — 화면에선 '0x0을 쓰라'는 정보가
                            사라지는데 TSV 복사에는 그대로 들어가 화면과 Excel이 달라진다. */}
                        <CellValue current={r.current} proposed={r.proposed} />
                        {r.note && <div className="text-muted" style={{ fontSize: 8 }}>⚠ {r.note}</div>}
                      </td>
                      <td style={{ ...cellStyle, ...monoStyle }}>{r.expectedCurrent || <span className="text-muted">—</span>}</td>
                    </>
                  )}
                  <td style={cellStyle}><VerdictPill verdict={r.verdict} /></td>
                  <td style={{ ...cellStyle, fontSize: 8 }} className="text-muted">{r.evidence || ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 3, fontSize: 9 }}>
        {rows.length > PREVIEW_ROWS && (
          <button type="button" className="btn btn-ghost" style={{ fontSize: 8, padding: '1px 5px' }}
            onClick={() => setExpanded((v) => !v)}>
            {expanded ? '접기' : `전체 ${rows.length}건 보기`}
          </button>
        )}
        {rows.length > PREVIEW_ROWS && !expanded && (
          <span className="text-muted">제안 {rows.length}건 중 {PREVIEW_ROWS}건 표시</span>
        )}
        {truncated && (
          <span className="text-muted">원문 {totals.docTotal}건 중 {totals.docShown}건만 대조 — 나머지는 문서에서 확인</span>
        )}
        {/* job에는 요약만 실린다 — 생성기 전량(24 시퀀스)은 누를 때만 서버에서 만든다(페이로드 억제). */}
        {onLoadFull && (
          <button type="button" className="btn btn-ghost" style={{ fontSize: 8, padding: '1px 5px' }}
            onClick={onLoadFull} disabled={loadingFull}>
            {loadingFull ? '불러오는 중…' : '⤓ 전체 초안 불러오기(생성기 전량)'}
          </button>
        )}
      </div>

      {(draft.unknownTypes || []).length > 0 && (
        <div className="text-muted" style={{ fontSize: 9, marginTop: 2 }}>
          · 타입 미상 {draft.unknownTypes.length}건({draft.unknownTypes.slice(0, 3).join(', ')}
          {draft.unknownTypes.length > 3 ? ' …' : ''}) — 경계값 자동 유도 불가, 원문 타입 정의 확인
        </div>
      )}
      {(draft.newColumns || []).length > 0 && (
        <div className="text-muted" style={{ fontSize: 9, marginTop: 2 }}>
          · 문서에 없는 파라미터 {draft.newColumns.map((c) => `${c.name}(${c.type})`).join(', ')} — 신규 컬럼 추가 검토
        </div>
      )}
      {(notes || []).map((n) => (
        <div key={n} className="text-muted" style={{ fontSize: 9, marginTop: 2 }}>· {n}</div>
      ))}

      {fallbackText && (
        <textarea readOnly value={fallbackText} onFocus={(e) => e.target.select()}
          style={{ width: '100%', height: 60, marginTop: 3, fontSize: 8, fontFamily: 'var(--font-mono, monospace)' }} />
      )}
    </div>
  );
}
