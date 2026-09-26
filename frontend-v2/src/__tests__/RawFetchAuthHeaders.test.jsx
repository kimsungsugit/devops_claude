/**
 * raw `fetch` 는 `authHeaders()`(Bearer + X-User)를 반드시 붙인다.
 *
 * 사용자 보고(2026-08-06): **"요구사항 커버리지 탭에 매트릭스 생성이 안 돼."**
 *
 * 실체는 인증이었다. 커밋 `1b6bb99`(2026-08-04, "X-User 헤더 한 줄이 신원이었다")가
 * X-User 단독 신원을 차단하면서 `DEV_MODE_X_USER_FALLBACK=0` 환경에선 `Authorization:
 * Bearer` 가 없으면 `UserContextMiddleware` 가 **401** 로 막는다. 그런데 프론트의
 * multipart 호출 12곳은 `api()`/`post()` 헬퍼(JSON 전용)를 못 써서 raw fetch 였고,
 * 그것들이 **X-User 만** 보내고 있었다.
 *
 * 증상이 인증처럼 보이지 않았던 이유가 둘이다:
 *   1. `requirements-preview` 가 401 → `reqItems = []` → `loadMatrix` 의 "요구사항 0건"
 *      분기가 Step 4(`traceability-matrix`)를 **통째로 건너뛰고 조기 return** 한다.
 *      화면엔 "매트릭스 생성 불가 — SRS…" 로 보여 경로 문제로 읽힌다.
 *   2. 미들웨어가 로깅 미들웨어보다 **앞에서** 401 을 반환해 `logs/backend.log` 에
 *      요청 줄이 한 줄도 안 남는다. 로그만 보면 호출 자체가 없던 것처럼 보인다.
 *
 * 그래서 이 파일은 두 층으로 고정한다:
 *   A. **행동** — `buildTraceMatrix` 가 실제로 `Authorization` 을 실어 보내는가.
 *   B. **구조** — 새로 추가되는 raw fetch 가 auth 를 빠뜨리는가(원래 12곳이 그렇게 늘었다).
 *
 * ⚠ B 만으론 부족하다("가드는 관측량을 단언할 것"). A 가 없으면 헤더를 만들어 놓고
 *   fetch 에 안 넘기는 변형이 그대로 생존한다.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// ─────────────────────────────────────────────────────────────────────────────
// A. 행동 — 실제로 Authorization 이 나가는가
// ─────────────────────────────────────────────────────────────────────────────

const mockPost = vi.fn();
vi.mock('../api.js', () => ({
  post: (...a) => mockPost(...a),
  authHeaders: () => ({ Authorization: 'Bearer TESTTOKEN', 'X-User': 'tester' }),
  buildUrl: (p) => p,
}));

const { buildTraceMatrix } = await import('../traceMatrix.js');

describe('buildTraceMatrix — requirements-preview 인증', () => {
  beforeEach(() => {
    mockPost.mockReset();
    mockPost.mockResolvedValue({});
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ preview: { items: [] }, traceability: { mapping_pairs: [] } }),
    });
  });
  afterEach(() => { delete global.fetch; });

  it('Authorization Bearer 를 실어 보낸다 (X-User 단독이면 백엔드가 401)', async () => {
    await buildTraceMatrix({ linkedDocs: { srs: 'U:/x/SRS.docx' }, sourceRoot: 'C:/src' });

    const call = global.fetch.mock.calls.find(
      ([url]) => String(url).includes('/api/jenkins/uds/requirements-preview'),
    );
    expect(call, 'requirements-preview 가 호출되지 않았다').toBeTruthy();

    const headers = call[1]?.headers || {};
    expect(headers.Authorization).toBe('Bearer TESTTOKEN');
    expect(headers['X-User']).toBe('tester');
  });

  it('multipart 이므로 Content-Type 을 직접 설정하지 않는다 (boundary 는 브라우저 몫)', async () => {
    await buildTraceMatrix({ linkedDocs: { srs: 'U:/x/SRS.docx' } });

    const call = global.fetch.mock.calls.find(
      ([url]) => String(url).includes('/api/jenkins/uds/requirements-preview'),
    );
    const headers = call[1]?.headers || {};
    const ct = Object.keys(headers).find((k) => k.toLowerCase() === 'content-type');
    expect(ct, `Content-Type 을 직접 설정하면 multipart boundary 가 깨진다 (${ct})`).toBeUndefined();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// B. 구조 — 새 raw fetch 가 auth 를 빠뜨리는가
// ─────────────────────────────────────────────────────────────────────────────

// vitest 는 frontend-v2 를 cwd 로 돈다(`vitest.config` root). import.meta.url 은 이 설정에서
// file: 스킴이 아니라 fileURLToPath 가 죽는다 — cwd 기준으로 잡고 실재를 단언한다.
const SRC = path.resolve(process.cwd(), 'src');

/** `/api/health` 는 미들웨어 면제(공개), AuthContext 는 로그인 자체라 Bearer 를 직접 만든다. */
const EXEMPT_FILES = new Set(['contexts/AuthContext.jsx']);
const EXEMPT_URL_RE = /\/api\/health/;

function collectSources(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    const st = fs.statSync(full);
    if (st.isDirectory()) {
      if (name === '__tests__' || name === 'node_modules') continue;
      collectSources(full, out);
    } else if (/\.(js|jsx)$/.test(name) && full !== path.join(SRC, 'api.js')) {
      out.push(full);
    }
  }
  return out;
}

/** `fetch(` 의 여는 괄호부터 짝이 맞는 닫는 괄호까지 잘라낸다(문자열 리터럴 무시는 과하다 — 인자 안에 괄호가 있어도 균형은 맞는다). */
function sliceCall(src, openParenIdx) {
  let depth = 0;
  for (let i = openParenIdx; i < src.length; i++) {
    if (src[i] === '(') depth++;
    else if (src[i] === ')') {
      depth--;
      if (depth === 0) return src.slice(openParenIdx, i + 1);
    }
  }
  return src.slice(openParenIdx);
}

describe('raw fetch auth 헤더 (구조 가드)', () => {
  it('/api/ 를 부르는 raw fetch 는 전부 authHeaders() 를 붙인다', () => {
    const offenders = [];

    for (const file of collectSources(SRC)) {
      const src = fs.readFileSync(file, 'utf-8');
      const rel = path.relative(SRC, file).replace(/\\/g, '/');
      if (EXEMPT_FILES.has(rel)) continue;

      const re = /\bfetch\s*\(/g;
      let m;
      while ((m = re.exec(src)) !== null) {
        const call = sliceCall(src, m.index + m[0].length - 1);
        if (!call.includes('/api/')) continue;      // 외부 URL·상대경로는 대상 아님
        if (EXEMPT_URL_RE.test(call)) continue;      // 공개 endpoint
        if (call.includes('authHeaders()')) continue;

        const line = src.slice(0, m.index).split('\n').length;
        offenders.push(`${rel}:${line}`);
      }
    }

    expect(
      offenders,
      'raw fetch 가 authHeaders() 없이 /api/ 를 부른다 — Bearer 누락 시 백엔드가 401 로 막고,\n'
      + '        호출부에 따라 그 401 이 "경로 오류"·"데이터 0건"으로 위장한다.\n'
      + '        위반: ' + offenders.join(', '),
    ).toEqual([]);
  });

  it('가드 자신이 살아 있다 — authHeaders() 없는 fetch 를 실제로 잡아낸다', () => {
    // 이 가드가 "검사 대상 0건"으로 조용히 통과하는 상태(경로 오타·필터 과다)를 막는다.
    expect(fs.existsSync(SRC), `소스 루트를 못 찾았다: ${SRC}`).toBe(true);
    const scanned = collectSources(SRC);
    expect(scanned.length).toBeGreaterThan(20);

    const apiFetches = scanned.filter((f) => {
      const src = fs.readFileSync(f, 'utf-8');
      const re = /\bfetch\s*\(/g;
      let m;
      while ((m = re.exec(src)) !== null) {
        if (sliceCall(src, m.index + m[0].length - 1).includes('/api/')) return true;
      }
      return false;
    });
    expect(apiFetches.length, '/api/ raw fetch 가 하나도 안 잡히면 스캐너가 죽은 것').toBeGreaterThan(5);
  });
});
