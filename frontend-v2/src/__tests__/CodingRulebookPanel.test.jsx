/**
 * CodingRulebookPanel — probe 목록 · 생성 후 카테고리 아코디언 · 제외 사유 · Markdown 저장(Q4).
 * 핵심: 빠진 규칙이 '문제 없음'으로 읽히지 않도록 제외 사유를 노출하고,
 * Markdown은 서버가 준 문자열을 그대로 저장한다(클라이언트 재조립 금지).
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;
const downloadBlob = vi.fn();

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));
vi.mock('../components/graphPrimitives.jsx', () => ({ downloadBlob: (...a) => downloadBlob(...a) }));

import CodingRulebookPanel from '../components/sections/CodingRulebookPanel.jsx';

const PROPS = { jobUrl: 'http://j/', cacheRoot: '' };

const PROBE = {
  ok: true, available: true, generated: false, cached: false,
  candidates: [
    { rule: 'M-1', latest: 120, evidence: 2 },
    { rule: 'M-9', latest: 30, evidence: 0 },
  ],
};

const BOOK = {
  ok: true, available: true, generated: true, build_number: 125,
  sections: [
    {
      category: 'required', label: '요구(Required)',
      rules: [{
        rule: 'M-1', title: 'pointer arithmetic', category: 'required',
        category_basis: "규칙 설명에 'required' 표기", violations: 120, trend: 'persistent',
        evidence_used: { fix_diffs: 1, unresolved_excerpts: 1 },
        intent: '포인터 산술을 배열 인덱스로 대체한다', rationale: '경계 검사 누락',
        avoid_pattern: 'p++; *p = v;', comply_pattern: 'buf[i] = v;',
        exceptions: ['DMA 순회'], confidence: 'medium',
      }],
    },
  ],
  excluded: [{ rule: 'M-9', reason: 'no_code_evidence' }],
  totals: { requested: 2, included: 1, excluded: 1, ai_enriched: 1 },
  note: '이 룰북은 초안입니다. 팀 검토·승인 전에는 사내 코딩 표준이 아닙니다.',
  markdown: '# 코딩 룰북 초안 — KJPDS02_PV\n\n## 요구(Required)\n',
  model: 'gemini-3.5-flash-lite', generated_at: '2026-07-26T09:00:00',
};

describe('CodingRulebookPanel', () => {
  beforeEach(() => { vi.clearAllMocks(); downloadBlob.mockClear(); mockResp = PROBE; });

  it('probe — 대상 규칙과 증거 수를 먼저 보여주고 증거 0건은 미리 경고한다', async () => {
    render(<CodingRulebookPanel {...PROPS} />);
    expect(await screen.findByText(/M-1 — 최근 위반 120 · 코드 증거 2건/)).toBeInTheDocument();
    expect(screen.getByText(/증거 없어 제외 예정/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '룰북 생성 (AI)' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Markdown 저장' })).toBeNull();
  });

  it('생성 후 카테고리 아코디언 + 규칙 카드(피할/준수 패턴)', async () => {
    const user = userEvent.setup();
    render(<CodingRulebookPanel {...PROPS} />);
    await screen.findByText(/M-1 — 최근 위반 120/);
    mockResp = BOOK;
    await user.click(screen.getByRole('button', { name: '룰북 생성 (AI)' }));
    expect(await screen.findByText(/요구\(Required\)/)).toBeInTheDocument();
    expect(screen.getByText('p++; *p = v;')).toBeInTheDocument();
    expect(screen.getByText('buf[i] = v;')).toBeInTheDocument();
    expect(screen.getByText(/포인터 산술을 배열 인덱스로/)).toBeInTheDocument();
    expect(screen.getByText(/규칙 설명에 'required' 표기/)).toBeInTheDocument();
    expect(screen.getByText(/수록 1건 · 제외 1 · AI 1/)).toBeInTheDocument();
  });

  it('제외된 규칙과 사유를 노출한다(빠진 규칙 침묵 금지)', async () => {
    const user = userEvent.setup();
    render(<CodingRulebookPanel {...PROPS} />);
    await screen.findByText(/M-1 — 최근 위반 120/);
    mockResp = BOOK;
    await user.click(screen.getByRole('button', { name: '룰북 생성 (AI)' }));
    expect(await screen.findByText(/제외된 규칙 1건/)).toBeInTheDocument();
    expect(screen.getByText(/M-9 — 코드 증거 없음\(일반론 방지\)/)).toBeInTheDocument();
  });

  it('Markdown 저장 — 서버가 준 문자열을 그대로 내보낸다', async () => {
    const user = userEvent.setup();
    render(<CodingRulebookPanel {...PROPS} />);
    await screen.findByText(/M-1 — 최근 위반 120/);
    mockResp = BOOK;
    await user.click(screen.getByRole('button', { name: '룰북 생성 (AI)' }));
    await user.click(await screen.findByRole('button', { name: 'Markdown 저장' }));
    expect(downloadBlob).toHaveBeenCalledTimes(1);
    const [blob, name] = downloadBlob.mock.calls[0];
    expect(name).toBe('coding-rulebook.md');
    expect(blob.type).toContain('text/markdown');
    expect(await blob.text()).toBe(BOOK.markdown);   // 클라이언트 재조립 금지
  });

  it('초안≠사내 표준 고지를 상시 노출', async () => {
    const user = userEvent.setup();
    render(<CodingRulebookPanel {...PROPS} />);
    await screen.findByText(/M-1 — 최근 위반 120/);
    mockResp = BOOK;
    await user.click(screen.getByRole('button', { name: '룰북 생성 (AI)' }));
    expect(await screen.findByText(/사내 코딩 표준이 아닙니다/)).toBeInTheDocument();
  });

  it('available:false reason 렌더', async () => {
    mockResp = { ok: true, available: false, reason: 'no_rules_in_trend' };
    render(<CodingRulebookPanel {...PROPS} />);
    expect(await screen.findByText(/위반 규칙 트렌드가 없어 룰북을 만들 수 없습니다/)).toBeInTheDocument();
  });
});
