import { useId, useState } from 'react';
import { PANEL } from './summaryCommon.js';

/**
 * SummaryPanel — '프로젝트 분석' 탭의 L1 데이터 카드 공용 래퍼.
 *
 * 왜 만들었나: 이 탭의 패널 11개가 **글자 그대로 같은 헤더 4줄**을 각자 복제하고 있었고,
 * 제목이 전부 `fontSize: var(--text-sm)(11px) / fontWeight: 600` 인 `<div>` 였다.
 * 결과가 두 가지 결함이다.
 *   ① 카드 14장이 같은 무게로 보여 무엇이 결론이고 무엇이 세부인지 화면이 말하지 않는다
 *      (그룹 헤딩 13px/700 과 패널 제목 11px/600 의 차이가 2px 뿐이었다).
 *   ② `<h1>~<h6>` 이 하나도 없어 스크린리더로 패널 간 점프가 불가능했다.
 * 여기서 `<h3>`(13px/700)로 올려 문서 heading 계층을 복원한다.
 *
 * 위계 3단 중 **L1**(측정 결과)만 이 컴포넌트를 쓴다.
 *   L1 데이터 = 이 카드 · L2 도구/설정 = 테두리 없는 muted 스트립 · L3 각주 = --text-xs muted
 * 설정 블록(예: 백필 가져오기 옵션)에 이걸 쓰면 위계가 다시 무너지므로 쓰지 말 것.
 *
 * 슬롯 4개가 기존 헤더 패턴 3종을 모두 흡수한다. **meta/problem/caption 은 접어도 보인다.**
 *   meta    — 제목 옆 muted 부연(빌드 번호·건수). 접어도 보이므로 "데이터가 사라졌다"로 안 읽힌다
 *   problem — 조회 실패·산출 불가 신호. **접힘 뒤로 숨으면 안 되는 유일한 축**(아래 ⚠ 참조)
 *   actions — 우측 정렬 버튼/셀렉트(생성·재생성·비교 등)
 *   caption — 제목 줄 아래 한 줄 설명(구 `marginBottom: sp-1` + 별도 캡션 div 패턴). 접어도 보인다
 *
 * ⚠ 접힘은 **CSS 숨김이며 언마운트가 아니다**. 언마운트하면 이미 받아 둔 데이터와 펼친 행이
 *   날아가고 다시 열 때 재요청이 난다. 요청 절감은 상위 서브탭의 lazy 마운트가 담당한다.
 *
 * ⚠ **접힘이 실패를 삼키면 안 된다.** 패널 본문에 있던 `{error && …}` / `{available===false && …}`
 *   는 접으면 시각·접근성 트리 양쪽에서 사라지고, 그러면 "접힌 정상" 과 "조회 실패" 가 화면에서
 *   똑같아진다(증거부재 ≠ 정상). 기본 접힘 패널은 반드시 `problem` 으로 그 신호를 헤더에 낸다.
 */
export default function SummaryPanel({
  title, meta, problem, actions, caption, children,
  defaultOpen = true, collapsible = true, id,
}) {
  const [open, setOpen] = useState(defaultOpen);
  const autoId = useId();
  const bodyId = `${id || autoId}-body`;
  const headingId = `${id || autoId}-title`;
  const shown = collapsible ? open : true;

  return (
    <section className="panel" style={PANEL} aria-labelledby={headingId}>
      <div style={{
        display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)',
        marginBottom: caption ? 'var(--sp-1)' : (shown ? 'var(--sp-2)' : 0),
      }}>
        {collapsible && (
          <button type="button" onClick={() => setOpen((v) => !v)}
            aria-expanded={open} aria-controls={bodyId}
            aria-label={`${title} ${open ? '접기' : '펼치기'}`}
            style={{
              fontSize: 'var(--text-xs)', lineHeight: 1, padding: '2px 6px',
              border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
              background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
            }}>
            {open ? '▾' : '▸'}
          </button>
        )}
        <h3 id={headingId} style={{ margin: 0, fontSize: 'var(--text-md)', fontWeight: 700, color: 'var(--text)' }}>
          {title}
        </h3>
        {meta}
        {problem}
        {actions && <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>{actions}</div>}
      </div>
      {caption && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: shown ? 'var(--sp-2)' : 0 }}>
          {caption}
        </div>
      )}
      <div id={bodyId} style={shown ? undefined : { display: 'none' }}>{children}</div>
    </section>
  );
}

/**
 * SummaryToolStrip — 위계 L2. 카드가 아니라 도구/설정 줄.
 * 테두리·배경·그림자가 없어 데이터 카드와 경쟁하지 않는다.
 */
export function SummaryToolStrip({ children, style }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 'var(--sp-1)',
      padding: 'var(--sp-1) var(--sp-2)',
      fontSize: 'var(--text-xs)', color: 'var(--text-muted)',
      ...style,
    }}>
      {children}
    </div>
  );
}
