import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FragmentRow } from '../components/sections/DocGenStatusBoard.jsx';
import { post } from '../api.js';
import { extractOutputPath } from '../docgenOutputPath.js';

/**
 * "생성 완료" 다음에 사용자가 실제로 하는 일 — **파일을 찾는 것**.
 *
 * 경로를 안 보여주면 완료 토스트는 "어딘가에 만들어졌다" 이상을 말하지 않는다.
 * 그래서 이 파일은 두 가지만 본다: (1) 저장 위치가 화면에 나오는가,
 * (2) 경로가 없을 때 **빈칸으로 두지 않는가**(빈칸은 "저장 안 됨" 으로 읽힌다).
 */

const row = { key: 'suts', icon: '📘', label: 'SUTS', desc: 'SW 단위시험' };
const verdict = { tone: 'ok', label: '완료' };

function renderRow(over = {}) {
  const props = {
    row, run: null, busy: false, genState: null, verdict,
    isOpen: false, detail: null, onToggle: () => {}, onGenerate: () => {},
    disabled: false, prepIsOpen: false, prepState: null,
    onTogglePrep: () => {}, onPrepReload: () => {}, onPrepAction: () => {},
    lastResult: null, onOpenFolder: () => {}, onSaveAs: () => {},
    ...over,
  };
  return render(<table><tbody><FragmentRow {...props} /></tbody></table>);
}

describe('저장 위치 표시', () => {
  it('생성에 성공하면 저장 경로를 그 행에서 보여준다', () => {
    renderRow({ lastResult: { success: true, path: 'C:\\cache\\suts_20260811.xlsm', docType: 'suts' } });
    expect(screen.getByText('C:\\cache\\suts_20260811.xlsm')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '폴더 열기' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '다른 폴더에 저장' })).toBeInTheDocument();
  });

  it('경로가 없으면 빈칸이 아니라 사실을 말한다 — 빈칸은 "저장 안 됨" 으로 읽힌다', () => {
    renderRow({ lastResult: { success: true, path: '', docType: 'suts' } });
    expect(screen.getByText(/경로를 알려주지 않았습니다/)).toBeInTheDocument();
    // 열 곳을 모르므로 버튼도 걸지 않는다(누르면 실패하는 버튼은 없느니만 못하다).
    expect(screen.queryByRole('button', { name: '폴더 열기' })).toBeNull();
  });

  it('실패한 생성에는 저장 위치를 붙이지 않는다', () => {
    renderRow({ lastResult: { success: false, error: '템플릿 없음', docType: 'suts' } });
    expect(screen.queryByText(/저장 위치/)).toBeNull();
  });

  it('다른 문서의 결과를 이 행에 붙이지 않는다', () => {
    // 보드가 `docType` 으로 걸러 주지만, 행 스스로도 남의 결과를 그리면 안 된다.
    renderRow({ lastResult: null });
    expect(screen.queryByText(/저장 위치/)).toBeNull();
  });
});

describe('경로 추출 — 문서마다 payload shape 가 다르다', () => {
  it('STS/SUTS/SITS 는 진행 dict 의 output_path', () => {
    expect(extractOutputPath({ ok: true, output_path: 'C:\\a\\sts.xlsm' })).toBe('C:\\a\\sts.xlsm');
  });

  it('UDS 는 result.path — 여기를 안 보면 경로가 있는데도 "모른다" 고 말한다', () => {
    expect(extractOutputPath({ stage: 'done', result: { ok: true, path: 'C:\\a\\uds.docx' } }))
      .toBe('C:\\a\\uds.docx');
  });

  it('없으면 빈 문자열 — 추측한 경로는 없는 파일을 열러 가게 만든다', () => {
    expect(extractOutputPath({ stage: 'done' })).toBe('');
    expect(extractOutputPath(null)).toBe('');
    expect(extractOutputPath({ output_path: '   ' })).toBe('');
  });

  it('진행 dict 가 result 보다 우선한다(같은 키가 둘 다 있을 때)', () => {
    expect(extractOutputPath({ output_path: 'A', result: { path: 'B' } })).toBe('A');
  });
});

describe('오류 detail 이 객체일 때', () => {
  let origFetch;
  beforeEach(() => { origFetch = global.fetch; });
  afterEach(() => { global.fetch = origFetch; vi.restoreAllMocks(); });

  it('code 와 message 를 뽑는다 — 못 뽑으면 화면에 원시 JSON 이 뜨고 분기도 못 한다', async () => {
    global.fetch = vi.fn(async () => ({
      ok: false,
      status: 400,
      text: async () => JSON.stringify({ detail: { code: 'dest_exists', message: '같은 이름의 파일이 이미 있습니다: a.xlsm' } }),
    }));
    await expect(post('/api/docgen/save-as', {})).rejects.toMatchObject({
      code: 'dest_exists',
      message: '같은 이름의 파일이 이미 있습니다: a.xlsm',
    });
  });

  it('문자열 detail 은 기존대로 동작한다(회귀 방지)', async () => {
    global.fetch = vi.fn(async () => ({
      ok: false, status: 403, text: async () => JSON.stringify({ detail: 'path not allowed' }),
    }));
    await expect(post('/x', {})).rejects.toThrow('path not allowed');
  });
});
