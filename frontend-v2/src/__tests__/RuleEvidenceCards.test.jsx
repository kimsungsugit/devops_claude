/** UnresolvedEvidenceCard — 구간 증거 3상태(변경/무변경/실패 reason) + note 상시. */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));

import { UnresolvedEvidenceCard } from '../components/sections/RuleEvidenceCards.jsx';

const PROPS = {
  jobUrl: 'http://j/', cacheRoot: '', rule: 'Rule-1.1',
  file: { path: 'APP/foo.c', count: 6 }, fromBuild: 122, toBuild: 125,
};

const NOTE = '파일 변경/무변경과 위반 잔존은 같은 빌드 구간의 관측이며 인과 판정이 아닙니다.';

describe('UnresolvedEvidenceCard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('파일 변경 증거 — 배지 + counts + diff + note', async () => {
    mockResp = {
      ok: true, available: true, file_changed: true,
      counts: { from: 6, to: 6 }, diff: { text: '-int x = 42;\n+int x = X_INIT;', truncated: false },
      note: NOTE,
    };
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText('파일 변경됨 — 위반 유지')).toBeInTheDocument();
    expect(screen.getByText(/위반 6 → 6건/)).toBeInTheDocument();
    expect(screen.getByText(/구간 변경 diff/)).toBeInTheDocument();
    expect(screen.getByText(`⚖ ${NOTE}`)).toBeInTheDocument();
  });

  it('파일 무변경 — 유효 증거 배지(실패 아님), diff 없음, counts 결측은 —', async () => {
    mockResp = {
      ok: true, available: true, file_changed: false,
      counts: { from: null, to: 6 }, counts_reason: 'no_rcr', diff: null, note: NOTE,
    };
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText('파일 무변경 — 위반 잔존')).toBeInTheDocument();
    expect(screen.getByText(/위반 — → 6건/)).toBeInTheDocument();   // null은 '—'(0 위장 금지)
    expect(screen.getByText(/일부 빌드 RCR 없음/)).toBeInTheDocument();
    expect(screen.queryByText(/구간 변경 diff/)).toBeNull();
  });

  it('available:false reason 한글 매핑', async () => {
    mockResp = { ok: true, available: false, reason: 'file_ambiguous_in_snapshot' };
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/동일 이름 파일이 여러 개/)).toBeInTheDocument();
  });

  it('요청 실패 — 오류 노출(침묵 금지)', async () => {
    mockResp = new Error('500');
    render(<UnresolvedEvidenceCard {...PROPS} />);
    await userEvent.click(screen.getByText(/구간 증거 보기/));
    expect(await screen.findByText(/구간 증거 조회 오류/)).toBeInTheDocument();
  });
});
