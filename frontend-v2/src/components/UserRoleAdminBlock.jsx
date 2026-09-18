import { useCallback, useEffect, useState } from 'react';
import { useToast } from '../App.jsx';
import { api, post } from '../api.js';
import { useAdminMode } from '../contexts/AdminContext.jsx';

/**
 * (R48-a) 계정·승인자 관리 — 설정 > 관리자 모드 안의 블록.
 *
 * 승인(4-eyes)은 **둘 이상의 신원**이 있어야 성립한다. 지금까지 계정을 만드는 길이 `config/users.json`
 * 직접 편집뿐이라 실제로는 계정 1개(생성자 = 승인자)로 운영됐다. 이 블록이 `/api/auth/users*` 를 부른다.
 *
 * - 권한은 **백엔드**가 판정한다(JWT + admin). 여기서는 `useAdminMode().isAdmin`(= `/api/auth/me`)이 아니면
 *   폼을 그리지 않고 그 사실을 적는다 — localStorage 관리자 모드 토글은 표시 편의일 뿐 권한이 아니다.
 * - 임시 비밀번호는 admin 이 정해 **직접 전달**한다. 서버는 되돌려 주지 않고, 첫 로그인에서 변경을 강제한다.
 * - 삭제는 두 번 눌러야 한다(무장 → 확인). `window.confirm` 은 테스트·자동화에서 막히고, 한 번 클릭은 실수다.
 * - 오류는 토스트 + `role="alert"` 로 남긴다. 성공 토스트는 **2xx 뒤에만**(X9).
 */
export default function UserRoleAdminBlock() {
  const toast = useToast();
  const { isAdmin, loading: adminLoading } = useAdminMode();
  const [data, setData] = useState(null);       // {users, admins, approvers}
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ username: '', temp_password: '', approver: true, admin: false });
  const [armed, setArmed] = useState('');       // 삭제 무장된 username

  const load = useCallback(async () => {
    setBusy(true); setErr('');
    try {
      const d = await api('/api/auth/users');
      setData(d && Array.isArray(d.users) ? d : { users: [], admins: [], approvers: [] });
    } catch (e) {
      setData(null);
      setErr(`계정 목록을 불러오지 못했습니다: ${e?.message || e}`);
    } finally {
      setBusy(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- admin 판정이 서면 1회 조회(콜백 첫 줄의 로딩 플래그 setState)
  useEffect(() => { if (isAdmin) load(); }, [isAdmin, load]);

  const create = async (e) => {
    e.preventDefault();
    const username = form.username.trim();
    if (!username || form.temp_password.length < 8) {
      toast('warning', '계정 이름과 8자 이상의 임시 비밀번호가 필요합니다.');
      return;
    }
    setBusy(true); setErr('');
    try {
      const d = await post('/api/auth/users', { username, temp_password: form.temp_password, approver: !!form.approver, admin: !!form.admin });
      if (!d?.created) throw new Error('서버가 생성을 확인하지 않았습니다');
      toast('success', `계정 ${username} 을 만들었습니다 — 첫 로그인에서 비밀번호 변경이 강제됩니다.`);
      setForm({ username: '', temp_password: '', approver: true, admin: false });
      await load();
    } catch (e2) {
      const msg = e2?.code === 'USER_EXISTS' ? `이미 있는 계정입니다: ${username}` : (e2?.message || String(e2));
      setErr(msg);
      toast('error', `계정 생성 실패: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const setRole = async (username, role, value) => {
    setBusy(true); setErr('');
    try {
      await api(`/api/auth/users/${encodeURIComponent(username)}/roles`, { method: 'PUT', body: JSON.stringify({ [role]: value }) });
      toast('success', `${username}: ${role === 'approver' ? '승인자' : 'admin'} ${value ? '부여' : '해제'}`);
      await load();
    } catch (e) {
      const msg = e?.code === 'SELF_DEMOTE' ? '자기 자신의 admin 권한은 해제할 수 없습니다'
        : e?.code === 'LAST_ADMIN' ? '마지막 admin 은 해제할 수 없습니다'
          : (e?.message || String(e));
      setErr(msg);
      toast('error', `역할 변경 실패: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (username) => {
    if (armed !== username) { setArmed(username); return; }
    setBusy(true); setErr(''); setArmed('');
    try {
      await api(`/api/auth/users/${encodeURIComponent(username)}`, { method: 'DELETE' });
      toast('success', `계정 ${username} 을 삭제했습니다.`);
      await load();
    } catch (e) {
      const msg = e?.code === 'SELF_DELETE' ? '자기 자신은 삭제할 수 없습니다'
        : e?.code === 'LAST_ADMIN' ? '마지막 admin 은 삭제할 수 없습니다'
          : (e?.message || String(e));
      setErr(msg);
      toast('error', `삭제 실패: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="field" data-testid="user-role-admin-block" style={{ marginTop: 12 }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>👥 계정·승인자</div>
      <div className="text-sm text-muted" style={{ marginBottom: 8 }}>
        검토 기록(승인)은 <strong>admin 또는 승인자</strong>만 남기고, 자기가 만든 run 은 판정할 수 없습니다(4-eyes).
        그래서 생성하는 사람과 다른 <strong>승인자 계정</strong>이 하나 이상 있어야 승인 절차가 성립합니다.
      </div>
      {adminLoading && <div className="text-sm text-muted">권한 확인 중…</div>}
      {!adminLoading && !isAdmin && (
        <p role="status" className="text-sm text-muted">
          백엔드 admin(<code>config/admin_users.json</code>)이 아니라 계정을 관리할 수 없습니다 — 이 화면의 관리자 모드 토글은 표시 편의일 뿐 권한이 아닙니다.
        </p>
      )}
      {isAdmin && (
        <>
          {err && <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 12, marginBottom: 6 }}>{err}</div>}
          {data && (
            <div style={{ overflowX: 'auto', marginBottom: 10 }}>
              <table className="board-table" aria-label="계정 목록">
                <thead><tr><th>계정</th><th>admin</th><th>승인자</th><th>상태</th><th /></tr></thead>
                <tbody>
                  {data.users.length === 0 && (
                    <tr><td colSpan={5} className="text-muted">계정이 없습니다.</td></tr>
                  )}
                  {data.users.map((u) => (
                    <tr key={u.username}>
                      <td><code>{u.username}</code></td>
                      <td>
                        <button type="button" className="btn-sm" disabled={busy}
                          aria-label={`${u.username} admin ${u.is_admin ? '해제' : '부여'}`}
                          onClick={() => setRole(u.username, 'admin', !u.is_admin)}>
                          {u.is_admin ? '✓ admin' : '— 부여'}
                        </button>
                      </td>
                      <td>
                        <button type="button" className="btn-sm" disabled={busy}
                          aria-label={`${u.username} 승인자 ${u.is_approver ? '해제' : '부여'}`}
                          onClick={() => setRole(u.username, 'approver', !u.is_approver)}>
                          {u.is_approver ? '✓ 승인자' : '— 부여'}
                        </button>
                      </td>
                      <td className="text-sm">
                        {u.must_change_password
                          ? <span className="pill pill-warning" style={{ fontSize: 10 }}>임시 비밀번호(변경 대기)</span>
                          : <span className="text-muted">활성</span>}
                      </td>
                      <td>
                        <button type="button" className="btn-sm" disabled={busy}
                          aria-label={armed === u.username ? `${u.username} 정말 삭제` : `${u.username} 삭제`}
                          onClick={() => remove(u.username)}
                          style={armed === u.username ? { color: 'var(--color-danger)', fontWeight: 700 } : undefined}>
                          {armed === u.username ? '정말 삭제' : '삭제'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="text-sm text-muted" style={{ marginTop: 4 }}>
                승인자 {(data.approvers || []).length}명 · admin {(data.admins || []).length}명
                {(data.approvers || []).length === 0 && <strong> — 승인자가 없어 아직 누구도 4-eyes 승인을 남길 수 없습니다.</strong>}
              </div>
            </div>
          )}
          <form onSubmit={create} aria-label="계정 생성" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <input aria-label="새 계정 이름" value={form.username} autoComplete="off"
              onChange={(e) => setForm({ ...form, username: e.target.value })} placeholder="계정 이름 (영문/숫자 2~64자)" style={{ maxWidth: 200 }} />
            <input aria-label="임시 비밀번호" type="password" value={form.temp_password} autoComplete="new-password"
              onChange={(e) => setForm({ ...form, temp_password: e.target.value })} placeholder="임시 비밀번호 (8자 이상)" style={{ maxWidth: 200 }} />
            <label className="text-sm"><input type="checkbox" checked={form.approver} onChange={(e) => setForm({ ...form, approver: e.target.checked })} /> 승인자</label>
            <label className="text-sm"><input type="checkbox" checked={form.admin} onChange={(e) => setForm({ ...form, admin: e.target.checked })} /> admin</label>
            <button type="submit" className="btn-primary btn-sm" disabled={busy}>계정 만들기</button>
          </form>
          <div className="text-sm text-muted" style={{ marginTop: 4 }}>
            임시 비밀번호는 서버가 되돌려 주지 않습니다 — 본인에게 직접 전달하세요. 첫 로그인에서 변경이 강제됩니다.
          </div>
        </>
      )}
    </div>
  );
}
