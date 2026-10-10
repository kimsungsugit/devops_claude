/**
 * impactGuard 단위 테스트
 *
 * 요구사항 추적: 영향분석 결과 오귀속 차단 (ISO 26262 — 문서 재생성 판정·추적성 오보고)
 *
 * 핵심 대비: 두 게이트의 정책이 의도적으로 다르다.
 *  - impactMatchesJob / targetConsistent : 파괴적 동작(트리거)용. 증거 없으면 거부.
 *  - impactConflict                      : 표시용. 모순이 증명될 때만 차단.
 */
import { describe, it, expect } from 'vitest';
import {
  strictScmIdForJob, scmIdForJob, impactMatchesJob, impactConflict, targetConsistent,
  contextConflict, mismatchText, IMPACT_MISMATCH_KO,
} from '../impactGuard.js';
import { pickScmForJob, pickScmForJobWithSource } from '../projectLoader.js';

const JOB = 'http://jenkins.example.com/job/KJPDS02_PV/';

/** 실제 잡 결과 형태 — trigger.scm_id + trigger.metadata.job_url */
const mkImpact = ({ scm = 'kjpds02_pv', jobUrl = JOB } = {}) => ({
  trigger: {
    scm_id: scm,
    metadata: jobUrl
      ? { job_url: jobUrl, build_number: 122, changed_files_source: 'svn_revision_range' }
      : { build_number: 122, changed_files_source: 'local_diff_fallback' },
  },
  changed_files: ['Ap_MotorCtrl.c'],
  impact: { direct: ['g_MotorCtrl'], indirect_1hop: [], indirect_2hop: [] },
});

describe('pickScmForJobWithSource — 매칭 근거 기록', () => {
  it('Jenkins job 이름과 토큰이 정확히 일치하면 exact', () => {
    const list = [{ id: 'kjpds02' }, { id: 'kjpds02_pv' }];
    expect(pickScmForJobWithSource(list, JOB)).toEqual({ entry: list[1], source: 'exact' });
  });

  it('job URL에 토큰이 포함되기만 하면 substring (최장 우선)', () => {
    const list = [{ id: 'kjpds02' }, { id: 'kjpds02_pv' }];
    const r = pickScmForJobWithSource(list, 'http://jenkins/job/KJPDS02_PV_Nightly/');
    expect(r).toEqual({ entry: list[1], source: 'substring' });
  });

  it('후보가 하나뿐이라 승인한 경우는 sole — job URL과 접점이 없음을 표시한다', () => {
    const list = [{ id: 'pds64', name: 'PDS64' }];
    expect(pickScmForJobWithSource(list, 'http://jenkins/job/nightly-build/'))
      .toEqual({ entry: list[0], source: 'sole' });
  });

  it('후보가 여럿인데 아무것도 안 맞으면 null', () => {
    const list = [{ id: 'aaa1' }, { id: 'bbb1' }];
    expect(pickScmForJobWithSource(list, 'http://jenkins/job/zzz/'))
      .toEqual({ entry: null, source: null });
  });

  it('entry는 pickScmForJob과 항상 동일하다 (기존 동작 보존)', () => {
    const cases = [
      [[], JOB],
      [null, JOB],
      [[{ id: 'pds64' }], 'http://jenkins/job/unrelated/'],
      [[{ id: 'kjpds02' }, { id: 'kjpds02_pv' }], JOB],
      [[{ id: 'aaa1' }, { id: 'bbb1' }], 'http://jenkins/job/zzz/'],
    ];
    for (const [list, url] of cases) {
      expect(pickScmForJobWithSource(list, url).entry).toBe(pickScmForJob(list, url));
    }
  });
});

describe('strictScmIdForJob — 증거만 인정', () => {
  it('토큰 정확 일치는 증거로 인정한다', () => {
    expect(strictScmIdForJob([{ id: 'kjpds02' }, { id: 'kjpds02_pv' }], JOB)).toBe('kjpds02_pv');
  });

  it('후보 유일(sole)은 증거가 아니다 — job URL을 읽지도 않았기 때문', () => {
    expect(strictScmIdForJob([{ id: 'pds64' }], 'http://jenkins/job/nightly/')).toBe('');
  });

  it('단일 후보라도 토큰이 job URL에 있으면 증거로 인정한다', () => {
    expect(strictScmIdForJob([{ id: 'pds64' }], 'http://jenkins/job/pds64-nightly/')).toBe('pds64');
  });
});

describe('scmIdForJob — matchedScm은 근거가 있을 때만 채택', () => {
  it('matchedScmSource가 manual이면 matchedScm을 그대로 쓴다', () => {
    expect(scmIdForJob({ matchedScm: { id: 'hdpdm01' }, matchedScmSource: 'manual' }, JOB))
      .toBe('hdpdm01');
  });

  it('근거가 sole이면 matchedScm을 믿지 않고 재판정한다', () => {
    // scmList가 없으니 재판정도 실패 → '' (fail-closed)
    expect(scmIdForJob({ matchedScm: { id: 'hdpdm01' }, matchedScmSource: 'sole' }, JOB)).toBe('');
  });

  it('근거 필드 자체가 없으면(구 세션·구 캐시) 믿지 않는다', () => {
    expect(scmIdForJob({ matchedScm: { id: 'hdpdm01' } }, JOB)).toBe('');
  });

  it('matchedScm이 약해도 scmList로 재판정에 성공하면 그 값을 쓴다', () => {
    const r = scmIdForJob({
      matchedScm: { id: 'hdpdm01' },
      scmList: [{ id: 'kjpds02' }, { id: 'kjpds02_pv' }],
    }, JOB);
    expect(r).toBe('kjpds02_pv');
  });
});

describe('impactMatchesJob — 트리거용(증거 요구)', () => {
  it('impact의 job_url이 현재 Job과 같으면 통과', () => {
    expect(impactMatchesJob({ impactData: mkImpact() }, JOB)).toEqual({ ok: true, reason: 'ok' });
  });

  it('impact의 job_url이 다른 Job이면 거부', () => {
    const other = mkImpact({ jobUrl: 'http://jenkins.example.com/job/HDPDM01/' });
    expect(impactMatchesJob({ impactData: other }, JOB))
      .toEqual({ ok: false, reason: 'impact_job_mismatch' });
  });

  it('형제 필드 analysisResult.jobUrl이 다른 Job이면 거부', () => {
    const ar = { impactData: mkImpact(), jobUrl: 'http://jenkins.example.com/job/OTHER/' };
    expect(impactMatchesJob(ar, JOB)).toEqual({ ok: false, reason: 'job_mismatch' });
  });

  it('job_url 증거가 없으면 SCM 축을 요구한다 — 증거 없으면 거부', () => {
    const local = { impactData: mkImpact({ jobUrl: '' }), matchedScm: { id: 'kjpds02_pv' } };
    expect(impactMatchesJob(local, JOB)).toEqual({ ok: false, reason: 'no_provenance' });
  });

  it('job_url이 없어도 SCM 축 증거가 있으면 통과', () => {
    const local = {
      impactData: mkImpact({ jobUrl: '' }),
      matchedScm: { id: 'kjpds02_pv' }, matchedScmSource: 'exact',
    };
    expect(impactMatchesJob(local, JOB)).toEqual({ ok: true, reason: 'ok' });
  });

  it('Job이 아직 없으면 대조 기준이 없으므로 판정 불가로 통과시킨다', () => {
    expect(impactMatchesJob({ impactData: mkImpact() }, '')).toEqual({ ok: true, reason: 'no_job' });
  });
});

describe('impactConflict — 표시용(모순만 차단)', () => {
  it('증거가 전혀 없어도 모순이 없으면 표시를 막지 않는다', () => {
    // 트리거 게이트라면 no_provenance로 거부되는 shape. 표시용은 통과시켜야 한다 —
    // 안 그러면 로컬 트리거 결과·단일 SCM 저장소의 정상 데이터를 상시로 감춘다.
    const bare = { impactData: { changed_files: ['a.c'] } };
    expect(impactMatchesJob(bare, JOB).ok).toBe(false);
    expect(impactConflict(bare, JOB)).toEqual({ conflict: false, reason: 'ok' });
  });

  it('impact의 job_url이 다른 Job이면 차단', () => {
    const other = { impactData: mkImpact({ jobUrl: 'http://jenkins.example.com/job/HDPDM01/' }) };
    expect(impactConflict(other, JOB)).toEqual({ conflict: true, reason: 'impact_job_mismatch' });
  });

  it('화면이 보여주는 SCM과 결과를 만든 SCM이 다르면 차단', () => {
    expect(impactConflict({ impactData: mkImpact({ scm: 'kjpds02_pv' }) }, JOB, 'hdpdm01'))
      .toEqual({ conflict: true, reason: 'scm_mismatch' });
  });

  it('같은 SCM이면 통과', () => {
    expect(impactConflict({ impactData: mkImpact({ scm: 'kjpds02_pv' }) }, JOB, 'kjpds02_pv'))
      .toEqual({ conflict: false, reason: 'ok' });
  });

  it('impact가 없으면 차단할 것도 없다', () => {
    expect(impactConflict({ impactData: null }, JOB)).toEqual({ conflict: false, reason: 'no_impact' });
  });

  // ── 형제 필드 축 (analysisResult.jobUrl) ─────────────────────────────
  // 이 축은 나머지 두 축이 모두 vacuous일 때의 **유일 방어**다:
  //  - impact.trigger.metadata.job_url 은 선택 필드다(backend/schemas.py 기본값 "",
  //    /api/local/impact/trigger 는 아예 안 싣는다) → 로컬 트리거 결과에서 vacuous
  //  - SCM 축은 displayScmId 를 같은 analysisResult 에서 파생하므로 stale 상태에서 항상 일치
  // 실제 경로: Detail.switchProject 가 setSelectedJob(B) 후 loadProjectFromCache(B) 에서
  // throw 하면 catch 가 토스트만 띄워 'selectedJob=B × analysisResult=A' 가 영구 지속된다.

  it('안전: 결과 뭉치가 다른 Job의 것이면 나머지 축이 모두 vacuous여도 차단한다', () => {
    const stale = {
      jobUrl: 'http://jenkins.example.com/job/PROJECT_A/',
      impactData: mkImpact({ scm: 'proj_a', jobUrl: '' }),   // 축 2 vacuous (로컬 트리거)
    };
    // 축 3도 vacuous하게 만든다 — 화면이 보여주는 SCM이 결과의 SCM과 같은 stale 상황
    expect(impactConflict(stale, JOB, 'proj_a'))
      .toEqual({ conflict: true, reason: 'job_mismatch' });
  });

  it('안전: 같은 Job이면 형제 필드가 있어도 통과한다 (과차단 방지)', () => {
    const fresh = { jobUrl: JOB, impactData: mkImpact({ jobUrl: '' }) };
    expect(impactConflict(fresh, JOB, 'kjpds02_pv')).toEqual({ conflict: false, reason: 'ok' });
  });
});

describe('contextConflict — 결과 뭉치 전체의 stale 판정', () => {
  it('analysisResult.jobUrl이 다른 Job이면 impactData가 없어도 차단한다', () => {
    // impactConflict는 impactData가 없으면 no_impact로 즉시 통과시킨다. 그래서
    // 추적성 매트릭스 입력(matchedScm.linked_docs)의 오귀속은 이 축으로만 잡힌다.
    const stale = { jobUrl: 'http://jenkins.example.com/job/PROJECT_A/', matchedScm: { id: 'proj_a' } };
    expect(impactConflict(stale, JOB)).toEqual({ conflict: false, reason: 'no_impact' });
    expect(contextConflict(stale, JOB)).toEqual({ conflict: true, reason: 'job_mismatch' });
  });

  it('같은 Job이면 통과', () => {
    expect(contextConflict({ jobUrl: JOB }, JOB)).toEqual({ conflict: false, reason: 'ok' });
  });

  it('analysisResult가 없으면 판정 대상이 없다', () => {
    expect(contextConflict(null, JOB)).toEqual({ conflict: false, reason: 'no_context' });
  });
});

describe('mismatchText — 침묵 은닉 차단', () => {
  it('알려진 사유는 원인과 해소방법을 함께 준다', () => {
    const t = mismatchText('job_mismatch');
    expect(t).toContain(IMPACT_MISMATCH_KO.job_mismatch);
    expect(t).toContain('대시보드');
  });

  it('job_* 사유는 영향 탭 재분석을 안내하지 않는다', () => {
    // 그 경로로는 해소되지 않는다 — adoptImpact가 `{...prev, impactData}`로 병합해
    // stale jobUrl을 그대로 보존하므로, 재분석해도 job_mismatch는 안 풀린다.
    expect(mismatchText('job_mismatch')).not.toContain('변경 영향 평가');
    expect(mismatchText('impact_job_mismatch')).not.toContain('변경 영향 평가');
  });

  it('안전: 미지의 사유여도 빈 문자열을 돌려주지 않는다', () => {
    // 빈 문자열이면 호출처가 '표시할 게 없음'으로 읽어 데이터를 감춘 채 배너도 안 띄운다.
    // 새 사유가 추가돼도 최소한 '무언가를 감췄다'는 사실은 전달돼야 한다.
    expect(mismatchText('some_future_reason')).not.toBe('');
    expect(mismatchText('some_future_reason')).toContain('일치하지 않습니다');
  });

  it('정상 상태는 빈 문자열 — 배너를 띄우지 않는다', () => {
    for (const r of ['ok', 'no_impact', 'no_context', '', null, undefined]) {
      expect(mismatchText(r)).toBe('');
    }
  });
});

describe('targetConsistent — 트리거 대상 확정', () => {
  it('결과가 아직 없어도 통과한다 — 첫 분석을 걸 수 있어야 한다', () => {
    expect(targetConsistent({ scmList: [{ id: 'kjpds02_pv' }] }, JOB)).toBe(true);
  });

  it('결과가 없더라도 Job과 analysisResult가 서로 다른 프로젝트면 거부', () => {
    expect(targetConsistent({ jobUrl: 'http://jenkins.example.com/job/OTHER/' }, JOB)).toBe(false);
  });

  it('결과가 있으면 impactMatchesJob과 같은 판정을 따른다', () => {
    const other = { impactData: mkImpact({ jobUrl: 'http://jenkins.example.com/job/HDPDM01/' }) };
    expect(targetConsistent(other, JOB)).toBe(false);
  });
});
