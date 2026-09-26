import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import DocProposalTable from '../components/sections/impact/DocProposalTable.jsx';

// (R76 N94) 타입 출처 라벨 — "소스 선언 그대로" 와 "typedef 를 풀어서 안 것" 과 "이름 규칙 추정" 을 화면이 가른다.
const draft = (typeSource) => ({
  mode: 'boundary',
  rows: [{ variable: 'g_Speed', type: 'uint16_t', typeSource, boundary: '0 ~ 65535', verdict: '유지' }],
});

describe('DocProposalTable — 타입 출처 라벨', () => {
  it('typedef 를 풀어서 안 타입엔 그 사실을 적는다', () => {
    render(<DocProposalTable title="t" draft={draft('globals_map_typedef')} />);
    expect(screen.getByText('typedef 해상')).toBeInTheDocument();
    expect(screen.queryByText('이름 규칙 추정')).toBeNull();
  });

  it('선언 그대로 아는 타입엔 아무 라벨도 붙이지 않는다', () => {
    render(<DocProposalTable title="t" draft={draft('globals_map')} />);
    expect(screen.getByText('uint16_t')).toBeInTheDocument();
    expect(screen.queryByText('typedef 해상')).toBeNull();
    expect(screen.queryByText('이름 규칙 추정')).toBeNull();
  });

  it('이름 규칙 추정은 예전 라벨 그대로', () => {
    render(<DocProposalTable title="t" draft={draft('name_pattern')} />);
    expect(screen.getByText('이름 규칙 추정')).toBeInTheDocument();
    expect(screen.queryByText('typedef 해상')).toBeNull();
  });
});
