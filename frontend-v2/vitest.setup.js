import '@testing-library/jest-dom/vitest';
import { configure } from '@testing-library/dom';

// ── 비동기 대기 기본 제한: 1,000ms → 5,000ms ────────────────────────────────
//
// testing-library 기본값은 1초다. 이 스위트는 84파일을 병렬 워커로 돌리므로
// (jsdom/happy-dom 환경 준비만 570초) 렌더-플러시 한 번이 1초를 넘는 순간
// `findBy*`/`waitFor` 가 터진다. 그러면 **같은 트리가 실행마다 통과/실패**한다 —
// 게이트 비결정이고, 회귀와 구별이 안 된다.
//
// 실측(2026-09-02): `DocGenStatusBoard — 응답 역전` 이 HEAD 에서 2회 중 1회 실패했고
// (그 테스트가 재는 건 **응답 순서**이지 지연이 아니다), 같은 실행에서 실패 집합이
// `ArchitectureGraphPanel`·`ImpactGuideSection` 으로 옮겨 다녔다.
//
// 저장소는 이미 이 문제를 **호출마다** `{ timeout: 6000 }`·`{ timeout: 10000 }` 으로
// 우회하고 있었다(`Dashboard.test.jsx`·`DocGenSection.test.jsx`). 그건 whack-a-mole 이라
// 안 적은 자리가 계속 남는다 → 기본값 자체를 올린다.
//
// ⚠ 통과하는 테스트는 느려지지 않는다. `waitFor` 는 콜백이 처음 통과하는 즉시 반환하고,
//   이 값은 **실패로 확정하기까지의 상한**일 뿐이다. 개별 호출의 명시 timeout 은 그대로
//   우선한다(6000/10000 은 여전히 그 값으로 동작).
configure({ asyncUtilTimeout: 5000 });
