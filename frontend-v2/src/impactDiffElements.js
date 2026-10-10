/**
 * 함수 diff 원문에서 **변경 요소**를 뽑고, 그걸 문서별 편집 액션으로 바꾸는 순수 함수들.
 *
 * `ImpactGuideSection.jsx` 안에 있던 것을 그대로 옮겼다 — 컴포넌트 파일이 컴포넌트 아닌 것을
 * export 하면 Fast Refresh 가 동작하지 않는다(react-refresh/only-export-components).
 * 로직·주석은 손대지 않았고 호출처(컴포넌트·테스트)만 이 경로를 본다.
 */
export const EMPTY_DIFF_ELEMS = Object.freeze({
  changedGlobals: { added: [], removed: [] },
  macros: { added: [], removed: [] },
  addedLines: 0, removedLines: 0, hunks: 0, truncated: false, noSemanticChange: false, commentOnly: false,
});
// 전역/정적 명명 규약: (u|s)+숫자 타입 prefix + g_/s_ 또는 bare g_/s_. 타입 prefix를 실제 토큰으로
// 앵커해 msg_/flag_group/cfg_mode 류 오탐 방지([a-z]{0,3} 백트래킹 과매칭 수정, reviewer #1/#2).
const _GLOBALISH = /^(?:[us]\d{1,2})?g_/;
const _STATICISH = /^(?:[us]\d{1,2})?s_/;
// LHS write: 식별자 + (배열첨자|멤버접근 .f/->f)* + 대입/복합대입(=(?!=)로 ==, 알파벳 op로 <=/>=/!= 제외).
// 멤버 write(g_X.mode=…, g_H->cnt=…)도 base 전역을 잡는다(reviewer #6/#7).
const _WRITE_LHS = /^\s*([A-Za-z_]\w*)(?:\[[^\]]*\]|(?:\.|->)\w+)*\s*(?:=(?!=)|[-+*/%|&^]=|<<=|>>=)/;
// 전처리: ifdef/ifndef/define/undef는 직접 매크로명, #if/#elif는 defined(X)의 X만 캡처한다.
// pragma/include는 조건부 컴파일이 아니므로 매크로로 잡지 않는다(reviewer #3/#8).
const _PREPROC_DIRECT = /^\s*#\s*(?:ifdef|ifndef|define|undef)\s+([A-Za-z_]\w*)/;
const _PREPROC_COND = /^\s*#\s*(?:if|elif)\b/;
const _DEFINED_RE = /defined\s*\(?\s*([A-Za-z_]\w*)/g;
// C 주석 제거(문자열/문자 리터럴 인식) — 라인 단위. {code, ambiguous} 반환.
// 문자열 안의 //·/* 는 주석이 아니다(예 "http://…") — strip_c_comments(utils/text.py) 정규식의 과다제거를 피한다.
// ambiguous=true(다중라인 주석 경계·미닫힘 문자열)면 호출부가 보수적으로 semantic 처리(주석-only 판정 보류).
function _stripLineComments(line) {
  let out = '', i = 0, inStr = null, ambiguous = false;
  while (i < line.length) {
    const c = line[i], n = line[i + 1];
    if (inStr) {
      out += c;
      if (c === '\\' && i + 1 < line.length) { out += n; i += 2; continue; }  // 이스케이프
      if (c === inStr) inStr = null;
      i++; continue;
    }
    if (c === '"' || c === "'") { inStr = c; out += c; i++; continue; }
    if (c === '/' && n === '/') break;                     // 라인 주석 → 나머지 버림
    if (c === '/' && n === '*') {                            // 블록 주석 시작
      const close = line.indexOf('*/', i + 2);
      if (close === -1) { ambiguous = true; break; }         // 같은 라인서 안 닫힘 → 다중라인 보수적
      i = close + 2; continue;
    }
    if (c === '*' && n === '/') { ambiguous = true; break; } // '*/' 선행 = 이전 라인 주석 종료 → 보수적
    out += c; i++;
  }
  if (inStr) ambiguous = true;                               // 미닫힘 문자열 → 보수적
  return { code: out, ambiguous };
}
export function extractDiffElements(fd) {
  if (!fd) return EMPTY_DIFF_ELEMS;
  const gAdd = new Set(), gRem = new Set(), mAdd = new Set(), mRem = new Set();
  let addedLines = 0, removedLines = 0, hunks = 0, truncated = false;
  const minusSeq = [], plusSeq = [];  // -/+ 본문 라인(순서 보존·trim) — 포맷/이동만(의미 변경 없음) 판정용
  const minusStripped = [], plusStripped = [];  // 주석 제거본 — 주석-only(코드 동일·주석만 다름) 판정용
  let commentAmbiguous = false;  // 다중라인 주석 경계 등 → 주석-only 판정 보류(보수적)
  for (const raw of String(fd).split('\n')) {
    if (!raw) continue;
    if (raw.startsWith('@@ ')) { hunks++; continue; }
    if (raw.startsWith('+++') || raw.startsWith('---')) continue;
    if (raw.includes('줄 생략)')) { truncated = true; continue; }  // extract_function_diffs 절단 마커
    const sign = raw[0];
    if (sign !== '+' && sign !== '-') continue;
    const body = raw.slice(1);
    const _st = _stripLineComments(body);
    if (_st.ambiguous) commentAmbiguous = true;
    if (sign === '+') { addedLines++; plusSeq.push(body.trim()); plusStripped.push(_st.code.trim()); }
    else { removedLines++; minusSeq.push(body.trim()); minusStripped.push(_st.code.trim()); }
    const gSet = sign === '+' ? gAdd : gRem;
    const mSet = sign === '+' ? mAdd : mRem;
    const wm = _WRITE_LHS.exec(body);  // 1) 전역/정적 write target(멤버 write는 base 전역)
    if (wm && (_GLOBALISH.test(wm[1]) || _STATICISH.test(wm[1]))) gSet.add(wm[1]);
    const pd = _PREPROC_DIRECT.exec(body);  // 2) 전처리 매크로
    if (pd) mSet.add(pd[1]);
    else if (_PREPROC_COND.test(body)) {
      _DEFINED_RE.lastIndex = 0;
      let dm;
      while ((dm = _DEFINED_RE.exec(body)) !== null) mSet.add(dm[1]);  // #if defined(X) → X
    }
  }
  // 포맷/이동만(의미 변경 없음): -/+ 본문이 순서·내용(공백 정규화) 동일 → 블록 이동·재들여쓰기.
  // ⚠ 순서 비교(멀티셋 아님)라 문장 재정렬(a=1;b=a;→b=a;a=1;)은 다르게 나와 실변경으로 유지(오탐 방지).
  //   truncated diff(60줄/400KB 상한)는 안 보이는 부분에 실변경 가능 → 판정 보류(false).
  const rawEqual = minusSeq.length === plusSeq.length && minusSeq.every((v, i) => v === plusSeq[i]);
  const noSemanticChange = !truncated && minusSeq.length > 0 && rawEqual;
  // 주석-only(비의미): 주석 제거본은 순서·내용 동일한데 원문은 다름 = 차이가 주석에만 있음. noSemanticChange
  // (원문까지 동일=포맷/이동)와 배타. 다중라인 주석 경계(commentAmbiguous)·truncated면 보수적으로 false(=의미변경).
  const commentOnly = !truncated && !commentAmbiguous && minusSeq.length > 0 && !rawEqual
    && minusStripped.length === plusStripped.length
    && minusStripped.every((v, i) => v === plusStripped[i]);
  // cap 없이 전체 반환 — 개수를 정확히 표시(백엔드 60줄 cap이 1차 상한, 카드 표시는 listVars가 4개로 cap). reviewer #5.
  return {
    changedGlobals: { added: [...gAdd], removed: [...gRem] },
    macros: { added: [...mAdd], removed: [...mRem] },
    addedLines, removedLines, hunks, truncated, noSemanticChange, commentOnly,
  };
}
// diffElems 캐시 — 모달 재렌더(검색 타이핑 등) 시 재계산 회피(_sigDiffCache 동일 패턴).
const _diffElemCache = new Map();
export function extractDiffElementsCached(fd) {
  if (!fd) return EMPTY_DIFF_ELEMS;
  let v = _diffElemCache.get(fd);
  if (v === undefined) {
    v = extractDiffElements(fd);
    if (_diffElemCache.size < 4000) _diffElemCache.set(fd, v);
  }
  return v;
}

// 절대 소스경로(Windows) → file_diffs(백엔드 extract_file_diffs의 정규화 상대경로 키) 경계 suffix 매칭.
// basename 충돌은 '/' 경계 + 최장(가장 구체적) 매칭으로 완화(백엔드 _in_line_classified 규약과 대칭).
export function matchFileDiff(absFile, fileDiffs) {
  if (!absFile || !fileDiffs) return '';
  const abs = String(absFile).replace(/\\/g, '/').toLowerCase();
  if (fileDiffs[abs]) return fileDiffs[abs];
  let bestKey = '';
  for (const k of Object.keys(fileDiffs)) {
    if ((abs === k || abs.endsWith('/' + k)) && k.length > bestKey.length) bestKey = k;
  }
  return bestKey ? fileDiffs[bestKey] : '';
}

// 함수 변경을 각 문서(UDS/STS/SUTS/SITS/SDS)의 '구체 편집 액션'으로 변환한다.
// 매개변수 diff(pdiff)가 정상이면 실제 파라미터명을 넣어 "무엇을 어느 섹션에" 수준으로 구체화하고,
// 원문이 없으면(pdiff null/failed) change_type 기반의 일반 액션으로 폴백한다. 순수·결정론(LLM 무관).
// 참고: 백엔드 workflow/impact_ai_guide.py의 _DOC_CHANGE_SENSITIVITY도 변경유형→문서 매핑을
//   'AI 영향도 분석 가이드' 패널용으로 독립 유지한다(파라미터 단위 아님) — 한쪽 수정 시 다른 쪽도 검토.
// 반환: { uds:[{section,text,tone}], sts:[...], suts:[...], sits:[...], sds:[...] }
export function buildDocumentActions(d, pdiff, diffElems = EMPTY_DIFF_ELEMS) {
  const ct = (d.changeType || '').toUpperCase();
  const changed = !!d.changed;
  const ok = !!pdiff && !pdiff.failed;
  const added = ok ? pdiff.rows.filter(r => r.status === 'added') : [];
  const removed = ok ? pdiff.rows.filter(r => r.status === 'removed') : [];
  const chg = ok ? pdiff.rows.filter(r => r.status === 'changed') : [];
  const retChanged = ok && pdiff.returnChanged;
  const posWarn = ok && pdiff.positional;  // 이름 매칭 불가 → 파라미터 귀속이 위치 추정(오귀속 주의)
  const listAfter = (rows) => rows.map(r => `\`${r.after || r.before}\``).join(', ');
  const listBefore = (rows) => rows.map(r => `\`${r.before || r.after}\``).join(', ');
  const pairText = (rows) => rows.map(r => `\`${r.before}\`→\`${r.after}\``).join(', ');
  const reqN = d.requirements?.length || 0;
  const stsN = d.stsTestCases?.length || 0;
  const sutsN = d.sutsTestCases?.length || 0;
  const sitsN = d.sitsTestCases?.length || 0;
  const A = (section, text, tone = 'neutral', title = '') => ({ section, text, tone, title });

  // ── 본문 diff에서 추출한 실제 변경 요소(전역 변수·전처리) — BODY/VARIABLE 구체화 근거 ──
  const de = diffElems || EMPTY_DIFF_ELEMS;
  const _gAset = new Set(de.changedGlobals.added), _gRset = new Set(de.changedGlobals.removed);
  const gRemoved = de.changedGlobals.removed.filter(v => !_gAset.has(v));  // 초기화 제거(제거만)
  const gAdded = de.changedGlobals.added.filter(v => !_gRset.has(v));      // 초기화 추가(추가만)
  const gChanged = de.changedGlobals.added.filter(v => _gRset.has(v));     // 값 변경(양쪽 등장)
  const condMacros = [...new Set([...de.macros.removed, ...de.macros.added])];
  const hasGlobals = !!(gRemoved.length || gAdded.length || gChanged.length);
  const truncNote = de.truncated ? ' (diff 일부 생략 — 원문 확인)' : '';
  const listVars = (arr, cap = 4) => ({
    text: arr.slice(0, cap).map(v => `\`${v}\``).join(', ') + (arr.length > cap ? ` +${arr.length - cap}개` : ''),
    title: arr.join(', '),
  });
  const globalsSummary = () => {
    const parts = [], tp = [];
    if (gRemoved.length) { const l = listVars(gRemoved); parts.push(`제거 ${gRemoved.length}개(${l.text})`); tp.push(`제거: ${l.title}`); }
    if (gAdded.length) { const l = listVars(gAdded); parts.push(`추가 ${gAdded.length}개(${l.text})`); tp.push(`추가: ${l.title}`); }
    if (gChanged.length) { const l = listVars(gChanged); parts.push(`값변경 ${gChanged.length}개(${l.text})`); tp.push(`값변경: ${l.title}`); }
    return { text: parts.join(' · '), title: tp.join(' / ') };
  };
  const macroSummary = condMacros.length
    ? { text: `조건부 컴파일 ${listVars(condMacros, 3).text} 변경`, title: condMacros.join(', ') }
    : null;
  const bodyish = (ct === 'BODY' || ct === 'VARIABLE');  // 분류 경계가 모호한 reset류는 동일 처리
  const useDiff = bodyish && (hasGlobals || !!macroSummary);  // 전역 또는 전처리 변경이 있으면 구체화(reviewer #4)

  const uds = [], sts = [], suts = [], sits = [], sds = [];

  // 간접 영향(직접 변경 아님): 문서 본문 수정이 아니라 '계약 유지 확인 + 회귀'가 핵심.
  if (!changed) {
    // 간접영향 근거(백엔드 impact_paths) — 왜 이 함수가 영향받는지: 경유 노드(via)/최초 변경함수(seed).
    // 무향 콜그래프라 '호출 관계'로만 표기(caller/callee 단정 안 함 — 과대주장 방지).
    const _viaText = d.via && d.seed && d.via !== d.seed
      ? `\`${d.seed}\`(변경) → \`${d.via}\` 경유로 연결`
      : d.seed ? `변경 함수 \`${d.seed}\`와의 호출 관계로 영향`
        : d.via ? `\`${d.via}\`와의 호출 관계로 영향` : '';
    uds.push(A('영향 경로', _viaText
      ? `${d.hop}: ${_viaText} — 계약(시그니처/동작) 유지 시 문서 수정 없음`
      : `직접 변경 아님(${d.hop}) — 호출 인터페이스 계약 유지 시 문서 수정 없음`,
      _viaText ? 'info' : 'neutral'));
    sts.push(A('회귀', stsN ? `${stsN}개 관련 TC 재실행 판단` : '직접 매핑 TC 없음', 'neutral'));
    suts.push(A('회귀', sutsN ? `${sutsN}개 단위 TC 재실행` : '관련 단위 TC 없음', 'neutral'));
    sits.push(A('회귀', sitsN ? `${sitsN}개 관련 통합 TC 재실행 판단` : '통합 콜체인 재실행 — 계약 유지 확인', 'neutral'));
    sds.push(A('상호작용', 'Component Interaction(간접 호출 관계) 유효성 확인', 'neutral'));
    return { uds, sts, suts, sits, sds };
  }

  // 주석-only(비의미) 변경: C 주석만 바뀌고 코드·로직 불변 → 문서 수정 불필요. 각 문서에 중립 단일 안내로
  // 대체한다(모달의 '문서 수정 불필요' 노트·renderAuthoringProposal 억제와 일관 — 과거엔 편집 액션에
  // 'Description에 변경 로직 반영' 류 불릿이 남아 같은 화면에서 모순됐다, reviewer #1).
  // ⚠ noSemanticChange(포맷/이동)는 여기서 중립화하지 않는다: 순서보존 이동이 use를 넘는 맹점(move-past-use)이
  //   있어 실 동작변경일 수 있어(d5716f7) 편집 액션·AI 교차확인을 유지한다 — commentOnly만 확정 중립.
  if (de.commentOnly) {
    const _n = 'C 주석만 변경 — 코드·로직 불변, 문서 수정 불필요';
    return {
      uds: [A('주석만', _n, 'neutral')],
      sts: [A('주석만', _n, 'neutral')],
      suts: [A('주석만', _n, 'neutral')],
      sits: [A('주석만', _n, 'neutral')],
      sds: [A('주석만', _n, 'neutral')],
    };
  }

  // ── UDS (단위 상세 설계) ──
  if (ct === 'SIGNATURE') {
    if (posWarn) uds.push(A('주의', '매개변수 이름 매칭 불가 — 아래 귀속은 위치 추정(원문 대조 필요)', 'warning'));
    uds.push(A('Prototype', '함수 선언을 새 시그니처로 교체', 'info'));
    if (added.length) uds.push(A('Input/Output Parameters', `${listAfter(added)} 파라미터 행 추가`, 'success'));
    if (removed.length) uds.push(A('Input/Output Parameters', `${listBefore(removed)} 파라미터 행 삭제`, 'danger'));
    if (chg.length) uds.push(A('Input/Output Parameters', `${pairText(chg)} 타입 변경`, 'warning'));
    if (retChanged) uds.push(A('Return Value', `반환타입 \`${pdiff.returnBefore || '(void)'}\`→\`${pdiff.returnAfter || '(void)'}\` 갱신`, 'warning'));
    // 파라미터/반환 분해 결과가 비었을 때: 파싱 실패(구조 분해 불가)와 실질 무변화(공백/본문)를 구분(reviewer W4).
    if (!added.length && !removed.length && !chg.length && !retChanged) {
      uds.push(pdiff && pdiff.failed
        ? A('Input/Output Parameters', '매개변수 구조 파싱 불가 — 원문 대조 후 반영', 'warning')
        : A('Input/Output Parameters', '매개변수 목록 변화 없음 — 본문/주석/공백 변경 가능(원문 확인)', 'neutral'));
    }
    uds.push(A('Calling Function', '호출부 목록의 인자 사용 영향 확인', 'neutral'));
  } else if (bodyish) {
    if (useDiff) {
      if (hasGlobals) {
        const g = globalsSummary();
        uds.push(A('Used Globals (Global/Static)', `전역 ${g.text} — Used Globals 목록·모듈 표 Reset Value 재확인${truncNote}`, gRemoved.length ? 'danger' : 'warning', g.title));
      }
      uds.push(macroSummary
        ? A('Description', `${macroSummary.text} 반영`, 'info', macroSummary.title)
        : A('Description', '변경된 로직/변수를 Description·의사코드에 반영', 'info'));
    } else {
      // diff 미확보 폴백(일반 문구)
      uds.push(A('Used Globals (Global/Static)', ct === 'VARIABLE' ? '전역/정적 변수 정의·모듈 표 Reset Value 갱신' : '사용 전역 변수·호출 함수 관계 재확인', 'warning'));
      uds.push(A('Description', ct === 'VARIABLE' ? '변수 변경에 따른 동작 반영' : '변경된 로직을 Description/의사코드에 반영', 'info'));
    }
  } else if (ct === 'NEW') {
    uds.push(A('Function Information', '신규 함수 항목 생성 — Prototype/Parameters/Description/Called·Calling', 'success'));
  } else if (ct === 'DELETE') {
    uds.push(A('Function Information', '해당 함수 항목 제거 및 호출부 참조 정리', 'danger'));
  } else if (ct === 'HEADER') {
    uds.push(A('Interface/Dependency', '헤더 타입·매크로 변경이 인터페이스에 주는 영향 확인', 'neutral'));
  } else {
    // 알 수 없는 change_type 방어(다른 4개 문서와 동일하게 catch-all — reviewer Info #8).
    uds.push(A('Function Information', '변경 내용에 맞게 함수 정보 항목 확인·갱신', 'neutral'));
  }
  if (reqN) uds.push(A('추적성', `연관 요구사항 ${reqN}개와의 매핑 유지 확인`, 'neutral'));

  // ── STS (SW 요구 기반 시험) ──
  if (stsN) {
    if (ct === 'SIGNATURE') {
      if (added.length) sts.push(A('Pre-condition', `${listAfter(added)} 입력 초기 조건 추가`, 'success'));
      sts.push(A('Test Action', `${stsN}개 TC의 함수 호출 인자를 새 시그니처로 갱신`, 'warning'));
      if (retChanged) sts.push(A('Expected Result', '반환값 판정 기준 갱신', 'warning'));
    } else if (bodyish && useDiff) {
      if (hasGlobals) {
        const g = globalsSummary();
        sts.push(A('Pre-condition', `초기화 변경 전역의 초기 조건 재검토 — ${g.text}`, 'warning', g.title));
        sts.push(A('Expected Result', `${stsN}개 TC의 해당 전역 기대 상태 재확인`, 'info'));
      } else {
        sts.push(A('Pre-condition', `${macroSummary.text} 반영 — ${stsN}개 TC 재검토`, 'warning', macroSummary.title));
      }
    } else if (ct === 'BODY') {
      sts.push(A('Expected Result', `${stsN}개 TC의 기대 동작 재확인`, 'info'));
      sts.push(A('Test Action', '변경 로직에 맞게 시퀀스 재검토', 'info'));
    } else if (ct === 'VARIABLE') {
      sts.push(A('Pre-condition', '변수 초기값/설정 반영', 'warning'));
    } else if (ct === 'DELETE') {
      sts.push(A('커버리지', `${stsN}개 TC의 요구사항 커버리지 재확인`, 'danger'));
    } else {
      sts.push(A('검토', `${stsN}개 TC 영향 확인`, 'neutral'));
    }
  } else {
    sts.push(A('매핑', reqN ? '요구사항은 있으나 STS TC 미매핑 — 수동 확인' : '직접 매핑 요구사항/TC 없음', 'neutral'));
  }

  // ── SUTS (SW 단위시험) ──
  if (ct === 'SIGNATURE') {
    if (added.length) suts.push(A('Input Variables', `${listAfter(added)} 입력 변수 추가 — 경계값(MIN/MID/MAX/INV) 케이스`, 'success'));
    if (removed.length) suts.push(A('Input Variables', `${listBefore(removed)} 입력 변수 제거`, 'danger'));
    if (chg.length) suts.push(A('Input Variables', `${pairText(chg)} — 타입 변경, 경계값 재계산`, 'warning'));
    if (retChanged) suts.push(A('Output Variables', '기대 출력 타입/값 갱신', 'warning'));
    suts.push(A('회귀', sutsN ? `기존 ${sutsN}개 단위 TC 재검증` : '단위 TC 신규 필요', sutsN ? 'neutral' : 'warning'));
  } else if (bodyish && useDiff) {
    if (hasGlobals) {
      const g = globalsSummary();
      suts.push(A('Expected(Output) Variables', `변경 전역의 reset 기대값 케이스 재확인/삭제 — ${g.text} (변수별 SwUTC 기대출력)`, gRemoved.length ? 'danger' : 'warning', g.title));
    } else {
      suts.push(A('Expected(Output) Variables', `${macroSummary.text} — 경계값·기대출력 재확인`, 'warning', macroSummary.title));
    }
  } else if (ct === 'BODY') {
    suts.push(A('Expected(Output) Variables', sutsN ? `${sutsN}개 TC 경계값·기대출력 재계산` : '로직 변경 — TC 없음, 신규 생성 권장', sutsN ? 'info' : 'warning'));
  } else if (ct === 'NEW') {
    suts.push(A('신규 TC', '단위 TC 신규 작성 — 경계값 분석(ABV: MIN/MID/MAX/INV)', 'success'));
  } else if (ct === 'DELETE') {
    suts.push(A('TC 정리', sutsN ? `${sutsN}개 관련 단위 TC 비활성화` : '관련 단위 TC 없음', 'danger'));
  } else if (ct === 'VARIABLE') {
    suts.push(A('Input/Output Variables', '변경 전역의 입출력 매핑·기대값 확인', 'warning'));
  } else {
    suts.push(A('확인', sutsN ? `${sutsN}개 단위 TC 검토` : '관련 단위 TC 없음', 'neutral'));
  }

  // ── SITS (SW 통합시험) — Data Flow 전용 컬럼 없음 → Call Chain / Input·Expected Param ──
  if (ct === 'SIGNATURE') {
    sits.push(A('Call Chain', `${d.function}의 콜체인 인자 전달 재검증(호출·피호출 양방향)`, 'warning'));
    if (added.length) sits.push(A('Input·Expected Param', `통합 입력/기대 Param에 ${listAfter(added)} 반영`, 'success'));
  } else if (bodyish && useDiff) {
    if (hasGlobals) {
      const g = globalsSummary();
      sits.push(A('Precondition', `변경 전역 초기화가 통합 진입 상태(Precondition/env)에 주는 영향 확인 — ${g.text}`, 'warning', g.title));
    } else {
      sits.push(A('Precondition', `${macroSummary.text}이 통합 진입 상태/분기에 주는 영향 확인`, 'warning', macroSummary.title));
    }
  } else if (ct === 'BODY') {
    sits.push(A('시나리오', '통합 시나리오 기대값 재확인', 'info'));
  } else if (ct === 'VARIABLE') {
    sits.push(A('Precondition', '변경 전역이 통합 진입 상태에 주는 영향 확인', 'warning'));
  } else if (ct === 'NEW') {
    sits.push(A('Call Chain', '신규 함수의 콜체인 포함 여부 및 통합 케이스 확인', 'success'));
  } else if (ct === 'DELETE') {
    sits.push(A('Call Chain', '콜체인 단절/대체 경로 확인', 'danger'));
  } else if (ct === 'HEADER') {
    sits.push(A('의존성', '헤더 변경이 콜체인 인터페이스 의존성에 주는 영향 확인', 'neutral'));
  } else {
    sits.push(A('확인', '통합 콜체인·Param 영향 확인', 'neutral'));
  }
  // SwRS 허브 브리지로 조인된 실제 SITS TC가 있으면 재검증 대상으로 정량 표기(STS/SUTS와 대칭).
  if (sitsN) sits.push(A('통합 TC', `${sitsN}개 관련 SITS TC 재검증`, 'info'));

  // ── SDS (SW 아키텍처 설계 — 파서, 고정 섹션명 없음: 함수/모듈 매칭으로 서술) ──
  if (ct === 'SIGNATURE') {
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 매칭 항목의 인터페이스(포트/파라미터)에 시그니처 변경 반영 — 원본 heading 확인`, 'warning'));
  } else if (bodyish && useDiff) {
    const g = hasGlobals ? globalsSummary() : macroSummary;
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 매칭 항목에 ${hasGlobals ? '전역 ' : ''}${g.text} 반영 — 고정 섹션 아님(원본 heading·relatedModules 확인)`, 'warning', g.title));
  } else if (ct === 'BODY') {
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 동작 설명 갱신 — 원본 heading 확인`, 'info'));
  } else if (ct === 'VARIABLE') {
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 관련 데이터/인터페이스 갱신 — 원본 heading 확인`, 'warning'));
  } else if (ct === 'NEW') {
    sds.push(A('설계 추가', '신규 컴포넌트/함수 아키텍처 반영', 'success'));
  } else if (ct === 'DELETE') {
    sds.push(A('설계 제거', '아키텍처에서 컴포넌트/함수 제거', 'danger'));
  } else {
    sds.push(A('관련 함수/모듈 매칭', 'relatedFunctions/relatedModules·changeTypes 기준 영향 확인', 'neutral'));
  }

  return { uds, sts, suts, sits, sds };
}

