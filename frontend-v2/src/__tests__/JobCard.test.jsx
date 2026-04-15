/**
 * JobCard 컴포넌트 단위 테스트
 *
 * 요구사항 추적: SRS-UI-JOBCARD
 * - 빌드 상태 표시 (색상 tone 기반)
 * - Job 이름 렌더링
 * - 클릭 시 선택 핸들러 호출
 * - 선택 상태 CSS 클래스 적용
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

// api.js 의존성 mock (colorTone 유틸 포함)
vi.mock('../api.js', () => ({
  colorTone: (color) => {
    if (!color) return 'neutral';
    if (color.includes('blue'))    return 'success';
    if (color.includes('red'))     return 'danger';
    if (color.includes('anime'))   return 'running';
    if (color.includes('yellow'))  return 'warning';
    return 'neutral';
  },
}));

const { default: JobCard } = await import('../components/JobCard.jsx');

/* ── 테스트 픽스처 ── */
const makeJob = (overrides = {}) => ({
  name: 'my-pipeline',
  url: 'http://jenkins/job/my-pipeline/',
  color: 'blue',
  lastBuild: { number: 42, result: 'SUCCESS', timestamp: 1700000000000 },
  ...overrides,
});

describe('JobCard', () => {
  // ── 렌더링 ──────────────────────────────────────────────────────────

  it('Job 이름을 표시한다', () => {
    // Arrange
    const job = makeJob();

    // Act
    render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert
    expect(screen.getByText('my-pipeline')).toBeInTheDocument();
  });

  it('빌드 번호를 표시한다', () => {
    // Arrange
    const job = makeJob();

    // Act
    render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert
    expect(screen.getByText('빌드 #42')).toBeInTheDocument();
  });

  it('빌드 이력이 없을 때 안내 텍스트를 표시한다', () => {
    // Arrange
    const job = makeJob({ lastBuild: null });

    // Act
    render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert
    expect(screen.getByText('빌드 이력 없음')).toBeInTheDocument();
  });

  it('fullName을 name 대신 사용한다', () => {
    // Arrange
    const job = makeJob({ name: undefined, fullName: 'folder/my-pipeline' });

    // Act
    render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert
    expect(screen.getByText('folder/my-pipeline')).toBeInTheDocument();
  });

  it('SUCCESS 상태 배지를 렌더링한다 (blue color)', () => {
    // Arrange
    const job = makeJob({ color: 'blue' });

    // Act
    render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert — SUCCESS 텍스트가 배지(pill-success)와 lastBuild.result 두 군데에 있으므로 getAllByText 사용
    expect(screen.getAllByText('SUCCESS').length).toBeGreaterThanOrEqual(1);
  });

  it('FAILURE 상태 배지를 렌더링한다 (red color)', () => {
    // Arrange
    const job = makeJob({ color: 'red' });

    // Act
    render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert
    expect(screen.getByText('FAILURE')).toBeInTheDocument();
  });

  it('NONE 상태 배지를 렌더링한다 (색상 없음)', () => {
    // Arrange
    const job = makeJob({ color: '' });

    // Act
    render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert
    expect(screen.getByText('NONE')).toBeInTheDocument();
  });

  // ── 선택 상태 ─────────────────────────────────────────────────────

  it('selected=true 일 때 selected 클래스를 적용한다', () => {
    // Arrange
    const job = makeJob();

    // Act
    const { container } = render(<JobCard job={job} selected={true} onClick={vi.fn()} />);

    // Assert
    expect(container.querySelector('.job-card.selected')).toBeInTheDocument();
  });

  it('selected=false 일 때 selected 클래스를 적용하지 않는다', () => {
    // Arrange
    const job = makeJob();

    // Act
    const { container } = render(<JobCard job={job} selected={false} onClick={vi.fn()} />);

    // Assert
    expect(container.querySelector('.job-card.selected')).toBeNull();
  });

  // ── 클릭 핸들러 ───────────────────────────────────────────────────

  it('클릭 시 onClick 핸들러를 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const onClick = vi.fn();
    const job = makeJob();

    // Act
    render(<JobCard job={job} selected={false} onClick={onClick} />);
    await user.click(screen.getByRole('button'));

    // Assert
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('Enter 키 입력 시 onClick 핸들러를 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    const onClick = vi.fn();
    const job = makeJob();

    // Act
    render(<JobCard job={job} selected={false} onClick={onClick} />);
    const card = screen.getByRole('button');
    card.focus();
    await user.keyboard('{Enter}');

    // Assert
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});
