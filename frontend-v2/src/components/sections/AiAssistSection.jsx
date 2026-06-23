import { useState, useRef, useCallback, useEffect } from 'react';
import { post, postSse, api, defaultCacheRoot } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

const NODE_LABELS = {
  classify_intent: '질문 분석',
  build_context: '컨텍스트 수집',
  select_model: '모델 선택',
  approval_gate: '승인 확인',
  llm_answer: '답변 생성',
};

function formatRagAnswer(data) {
  if (typeof data?.answer === 'string') return data.answer;
  if (Array.isArray(data?.items) && data.items.length > 0) {
    return data.items.map((item, i) => {
      const content = item.content ?? item.text ?? item.chunk ?? '';
      const source = item.source ?? item.metadata?.source ?? '';
      const score = item.score ?? item.relevance_score;
      return `**[${i + 1}]**${score != null ? ` (${(score * 100).toFixed(0)}%)` : ''}\n${content}\n` +
        (source ? `📄 ${source}\n` : '');
    }).join('\n---\n');
  }
  return '관련 정보를 찾을 수 없습니다. RAG 데이터를 먼저 수집해주세요.';
}

export default function AiAssistSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  // job 별 대화 thread 영속 키 (job 전환 시 별도 대화)
  const threadKey = `devops_chat_thread::${job?.url || 'local'}`;

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const [mode, setMode] = useState('ai'); // 'ai' = LLM 추론(/api/chat) | 'fast' = 벡터검색(RAG)
  const [threadId, setThreadId] = useState('');
  const [approval, setApproval] = useState(null);
  const [progress, setProgress] = useState('');
  const [ragStatus, setRagStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [topK, setTopK] = useState(5);
  const [category, setCategory] = useState('');
  const [showHistory, setShowHistory] = useState(false);
  const [conversations, setConversations] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const bottomRef = useRef(null);
  const abortRef = useRef(null);

  // job 전환 시: 해당 job 의 thread 복원 + 대화 초기화
  useEffect(() => {
    let tid = '';
    try { tid = localStorage.getItem(threadKey) || ''; } catch { /* noop */ }
    setThreadId(tid);
    setMessages([]);
    setApproval(null);
  }, [threadKey]);

  const persistThread = useCallback((tid) => {
    try { if (tid) localStorage.setItem(threadKey, tid); } catch { /* noop */ }
  }, [threadKey]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, approval, progress]);

  const loadRagStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const data = await post('/api/local/rag/status', {});
      setRagStatus(data);
    } catch {
      setRagStatus(null);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  useEffect(() => { loadRagStatus(); }, [loadRagStatus]);

  // 마지막 assistant 버블을 patch
  const patchLastAssistant = useCallback((patch) => {
    setMessages(prev => {
      const n = [...prev];
      const last = n[n.length - 1];
      if (last?.role === 'assistant') n[n.length - 1] = { ...last, ...patch, pending: false };
      return n;
    });
  }, []);

  const send = useCallback(async (qOverride) => {
    const q = (typeof qOverride === 'string' ? qOverride : input).trim();
    if (!q || pending) return;
    setInput('');
    setApproval(null);
    setMessages(prev => [...prev, { role: 'user', content: q }, { role: 'assistant', content: '', pending: true }]);
    setPending(true);

    // 빠른 검색 (기존 RAG 경로 — 폴백 유지)
    if (mode === 'fast') {
      try {
        const payload = {
          job_url: job?.url ?? '', cache_root: cacheRoot,
          build_selector: cfg.buildSelector || 'lastSuccessfulBuild', query: q, top_k: topK,
        };
        if (category) payload.categories = [category];
        const data = await post('/api/jenkins/rag/query', payload);
        patchLastAssistant({ content: formatRagAnswer(data) });
      } catch (e) {
        patchLastAssistant({ content: `오류: ${e.message}` });
        toast('error', e.message);
      } finally {
        setPending(false);
      }
      return;
    }

    // AI 추론 (SSE 스트리밍)
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await postSse('/api/chat/stream', {
        mode: job?.url ? 'jenkins' : 'local',
        question: q,
        session_id: threadId || undefined,
        thread_id: threadId || undefined,
        ui_context: { current_view: 'detail' },
        jenkins: {
          job_url: job?.url ?? '', cache_root: cacheRoot,
          build_selector: cfg.buildSelector || 'lastSuccessfulBuild',
        },
        save_history: true,
      }, {
        signal: ctrl.signal,
        onEvent: (_evType, data) => {
          const t = data?.type;
          if (t === 'graph_node_started') {
            setProgress(NODE_LABELS[data.payload?.node] || '처리 중');
          } else if (t === 'message') {
            const r = data;
            if (r.thread_id) {
              // W1: 함수형 업데이터 — onEvent 클로저의 stale threadId 비교 제거
              setThreadId(prev => prev || r.thread_id);
              persistThread(r.thread_id); // localStorage.setItem 은 idempotent
            }
            if (r.approval_required && r.approval_request) setApproval(r.approval_request);
            patchLastAssistant({
              content: r.answer || '(빈 응답)',
              evidence: r.evidence || [],
              nextSteps: r.next_steps || [],
            });
          } else if (t === 'error') {
            patchLastAssistant({ content: `오류: ${data.detail || 'internal error'}` });
          }
        },
      });
    } catch (e) {
      if (e.name !== 'AbortError') {
        patchLastAssistant({ content: `오류: ${e.message}` });
        toast('error', e.message);
      }
    } finally {
      setPending(false);
      setProgress('');
      abortRef.current = null;
      // W2: message 이벤트 없이 스트림이 끝난 경우(네트워크 이상 등) 빈 pending 버블 정리
      setMessages(prev => {
        const last = prev[prev.length - 1];
        if (last?.role === 'assistant' && last.pending && !last.content) {
          const n = [...prev];
          n[n.length - 1] = { ...last, content: '(응답을 받지 못했습니다)', pending: false };
          return n;
        }
        return prev;
      });
    }
  }, [input, pending, mode, job, cfg, cacheRoot, topK, category, threadId, toast, patchLastAssistant, persistThread]);

  const cancel = useCallback(() => {
    try { abortRef.current?.abort(); } catch { /* noop */ }
  }, []);

  const resolveApproval = useCallback(async (decision) => {
    if (!approval || pending) return;
    const ap = approval;
    setApproval(null);
    setPending(true);
    setMessages(prev => [...prev, { role: 'assistant', content: '', pending: true }]);
    try {
      const r = await post('/api/chat/approval/resolve', { approval_id: ap.approval_id, decision });
      patchLastAssistant({ content: r.answer || '', evidence: r.evidence || [], nextSteps: r.next_steps || [] });
    } catch (e) {
      toast('error', e.message);
      setMessages(prev => prev.slice(0, -1));
    } finally {
      setPending(false);
    }
  }, [approval, pending, toast, patchLastAssistant]);

  const resetChat = useCallback(() => {
    setMessages([]);
    setApproval(null);
    setThreadId('');
    try { localStorage.removeItem(threadKey); } catch { /* noop */ }
  }, [threadKey]);

  // 서버 대화 이력 (owner 는 X-User 헤더로 자동 격리)
  const loadConversations = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await api('/api/chat/history?limit=30');
      setConversations(Array.isArray(data?.conversations) ? data.conversations : []);
    } catch {
      setConversations([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const openConversation = useCallback(async (tid) => {
    if (!tid || pending) return;
    setHistoryLoading(true);
    try {
      const data = await api(`/api/chat/history/${encodeURIComponent(tid)}`);
      const msgs = Array.isArray(data?.messages)
        ? data.messages.map(m => ({ role: m.role === 'assistant' ? 'assistant' : 'user', content: m.text || '' }))
        : [];
      setMessages(msgs);
      setThreadId(tid);
      persistThread(tid);
      setApproval(null);
      setShowHistory(false);
    } catch (e) {
      toast('error', e.message);
    } finally {
      setHistoryLoading(false);
    }
  }, [pending, persistThread, toast]);

  const removeConversation = useCallback(async (tid, e) => {
    e?.stopPropagation();
    try {
      await api(`/api/chat/history/${encodeURIComponent(tid)}`, { method: 'DELETE' });
      setConversations(prev => prev.filter(c => c.thread_id !== tid));
      if (tid === threadId) {
        setMessages([]);
        setThreadId('');
        try { localStorage.removeItem(threadKey); } catch { /* noop */ }
      }
    } catch (err) {
      toast('error', err.message);
    }
  }, [threadId, threadKey, toast]);

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 220px)', minHeight: 400, gap: 12 }}>
      {/* RAG Status bar */}
      <div className="panel" style={{ padding: '8px 12px', flexShrink: 0 }}>
        <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>RAG 지식 베이스</span>
            {ragStatus ? (
              <StatusBadge tone="success">연결됨</StatusBadge>
            ) : (
              <StatusBadge tone="neutral">미확인</StatusBadge>
            )}
            {ragStatus?.stats?.total != null && (
              <span className="text-sm text-muted">{ragStatus.stats.total.toLocaleString()} chunks</span>
            )}
            {ragStatus?.stats?.by_category && (
              <span className="text-sm text-muted">
                {Object.keys(ragStatus.stats.by_category).length} 카테고리
              </span>
            )}
            {ragStatus?.kb_storage && (
              <span className="pill pill-neutral" style={{ fontSize: 10 }}>{ragStatus.kb_storage}</span>
            )}
          </div>
          <div className="row" style={{ gap: 6, alignItems: 'center' }}>
            {/* 모드 토글 */}
            <div className="row" style={{ gap: 0, border: '1px solid var(--border)', borderRadius: 'var(--radius-md, 6px)', overflow: 'hidden' }}>
              <button
                className="btn-sm"
                onClick={() => setMode('ai')}
                style={{ fontSize: 10, border: 'none', borderRadius: 0, background: mode === 'ai' ? 'var(--accent)' : 'transparent', color: mode === 'ai' ? 'var(--text-inverse)' : 'var(--text)' }}
                title="LLM 다단계 추론 + 도구 컨텍스트 + 스트리밍"
              >AI 추론</button>
              <button
                className="btn-sm"
                onClick={() => setMode('fast')}
                style={{ fontSize: 10, border: 'none', borderRadius: 0, background: mode === 'fast' ? 'var(--accent)' : 'transparent', color: mode === 'fast' ? 'var(--text-inverse)' : 'var(--text)' }}
                title="벡터 검색만 (빠름)"
              >빠른 검색</button>
            </div>
            {mode === 'fast' && (
              <>
                <select value={category} onChange={e => setCategory(e.target.value)} style={{ fontSize: 11, padding: '3px 6px' }}>
                  <option value="">전체 카테고리</option>
                  {ragStatus?.stats?.by_category ? (
                    Object.entries(ragStatus.stats.by_category).map(([cat, cnt]) => (
                      <option key={cat} value={cat}>{cat} ({cnt})</option>
                    ))
                  ) : (
                    <>
                      <option value="requirements">요구사항</option>
                      <option value="uds">UDS</option>
                      <option value="code">소스코드</option>
                      <option value="general">일반</option>
                    </>
                  )}
                </select>
                <select value={topK} onChange={e => setTopK(Number(e.target.value))} style={{ fontSize: 11, padding: '3px 6px', width: 60 }}>
                  {[3, 5, 10, 15, 20].map(n => <option key={n} value={n}>Top {n}</option>)}
                </select>
              </>
            )}
            <button className="btn-sm" onClick={loadRagStatus} disabled={statusLoading} style={{ fontSize: 10 }}>
              {statusLoading ? '...' : '상태 확인'}
            </button>
          </div>
        </div>

        {/* Category breakdown — 빠른 검색 모드에서만 */}
        {mode === 'fast' && ragStatus?.stats?.by_category && Object.keys(ragStatus.stats.by_category).length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
            {Object.entries(ragStatus.stats.by_category).map(([cat, cnt]) => (
              <span key={cat}
                className={`pill ${category === cat ? 'pill-info' : 'pill-neutral'}`}
                style={{ fontSize: 10, cursor: 'pointer' }}
                onClick={() => setCategory(prev => prev === cat ? '' : cat)}
                title={`${cat}: ${cnt} chunks`}
              >
                {cat} <strong>{cnt}</strong>
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 이력 사이드바 + 채팅 (가로 배치) */}
      <div style={{ flex: 1, display: 'flex', gap: 12, minHeight: 0 }}>
      {showHistory && (
        <div className="panel" style={{ width: 220, flexShrink: 0, display: 'flex', flexDirection: 'column', minHeight: 0, padding: 8 }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>대화 이력</span>
            <button className="btn-sm" onClick={loadConversations} disabled={historyLoading} style={{ fontSize: 10 }}>
              {historyLoading ? '...' : '새로고침'}
            </button>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {conversations.length === 0 ? (
              <div className="text-sm text-muted" style={{ padding: 8 }}>
                {historyLoading ? '불러오는 중...' : '저장된 대화가 없습니다.'}
              </div>
            ) : conversations.map(c => (
              <div key={c.thread_id}
                onClick={() => openConversation(c.thread_id)}
                className="row"
                style={{
                  justifyContent: 'space-between', alignItems: 'center', gap: 4,
                  padding: '6px 8px', borderRadius: 6, cursor: 'pointer',
                  background: c.thread_id === threadId ? 'var(--bg)' : 'transparent',
                  border: c.thread_id === threadId ? '1px solid var(--border)' : '1px solid transparent',
                }}>
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="text-sm" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.title || '(제목 없음)'}
                  </div>
                  <div className="text-muted" style={{ fontSize: 10 }}>{c.message_count || 0}개 메시지</div>
                </div>
                <button className="btn-sm" onClick={(e) => removeConversation(c.thread_id, e)} title="삭제"
                  style={{ fontSize: 10, flexShrink: 0 }}>✕</button>
              </div>
            ))}
          </div>
        </div>
      )}
      {/* Chat panel */}
      <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div className="panel-header" style={{ flexShrink: 0 }}>
          <span className="panel-title">AI 어시스턴트</span>
          <div className="row" style={{ gap: 8, alignItems: 'center' }}>
            <button
              className="btn-sm"
              onClick={() => setShowHistory(s => { const next = !s; if (next) loadConversations(); return next; })}
              style={{ fontSize: 11 }}
            >{showHistory ? '이력 닫기' : '이력'}</button>
            {threadId && <span className="text-sm text-muted" title={`thread: ${threadId}`}>대화 이어가는 중</span>}
            {messages.length > 0 && (
              <button className="btn-sm" onClick={resetChat}>새 대화</button>
            )}
          </div>
        </div>

        {/* Chat area */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '8px 0', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {messages.length === 0 ? (
            <div className="empty-state" style={{ padding: 24 }}>
              <div className="empty-icon">💬</div>
              <div className="empty-title">무엇이든 물어보세요</div>
              <div className="empty-desc">
                Jenkins 빌드 결과, 문서, 소스코드에 대해 질문하세요.
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, width: '100%', maxWidth: 360, marginTop: 8 }}>
                {[
                  '마지막 빌드에서 실패한 테스트는 무엇인가요?',
                  'QAC 위반 중 중요도 높은 항목을 알려주세요.',
                  'SRS 요구사항 중 변경 영향을 받는 항목은?',
                  '커버리지가 낮은 함수 목록을 알려줘.',
                ].map(q => (
                  <button key={q} onClick={() => send(q)} disabled={pending} style={{ textAlign: 'left', fontSize: 12 }}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => <ChatBubble key={i} message={m} onNextStep={send} />)
          )}

          {/* 진행 표시 (AI 추론 스트리밍) */}
          {pending && progress && (
            <div className="row" style={{ gap: 8, alignItems: 'center', paddingLeft: 8 }}>
              <span className="spinner" style={{ display: 'inline-block' }} />
              <span className="text-sm text-muted">{progress}</span>
              <button className="btn-sm" onClick={cancel} style={{ fontSize: 10 }}>중단</button>
            </div>
          )}

          {/* 승인 카드 */}
          {approval && (
            <ApprovalCard approval={approval} pending={pending} onResolve={resolveApproval} />
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <div className="row mt-2" style={{ gap: 8, alignItems: 'flex-end', flexShrink: 0 }}>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="질문을 입력하세요... (Enter: 전송, Shift+Enter: 줄바꿈)"
            rows={2}
            disabled={pending}
            style={{ flex: 1, resize: 'none', fontFamily: 'inherit' }}
          />
          <button
            className="btn-primary"
            onClick={() => send()}
            disabled={pending || !input.trim()}
            style={{ height: 52, width: 60, flexShrink: 0 }}
          >
            {pending ? <span className="spinner" style={{ display: 'inline-block' }} /> : '전송'}
          </button>
        </div>
      </div>
      </div>
    </div>
  );
}

function ApprovalCard({ approval, pending, onResolve }) {
  const tone = approval.risk_level === 'high' ? 'danger' : approval.risk_level === 'low' ? 'neutral' : 'warning';
  return (
    <div className="panel" style={{ padding: 12, border: '1px solid var(--border)', background: 'var(--bg)' }}>
      <div className="row" style={{ gap: 8, alignItems: 'center', marginBottom: 6 }}>
        <StatusBadge tone={tone}>승인 필요</StatusBadge>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{approval.title || '승인 필요 작업'}</span>
        {approval.risk_level && <span className="pill pill-neutral" style={{ fontSize: 10 }}>{approval.risk_level}</span>}
      </div>
      <div className="text-sm" style={{ marginBottom: 10, whiteSpace: 'pre-wrap' }}>{approval.summary || ''}</div>
      <div className="row" style={{ gap: 8 }}>
        <button className="btn-primary" disabled={pending} onClick={() => onResolve('approve')} style={{ fontSize: 12 }}>승인</button>
        <button className="btn-sm" disabled={pending} onClick={() => onResolve('reject')} style={{ fontSize: 12 }}>거절</button>
      </div>
    </div>
  );
}

function ChatBubble({ message, onNextStep }) {
  const isUser = message.role === 'user';
  const evidence = Array.isArray(message.evidence) ? message.evidence : [];
  const nextSteps = Array.isArray(message.nextSteps) ? message.nextSteps : [];
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      <div style={{
        maxWidth: '82%',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}>
        <div style={{
          padding: '8px 12px',
          borderRadius: isUser ? '12px 12px 4px 12px' : '12px 12px 12px 4px',
          background: isUser ? 'var(--accent)' : 'var(--bg)',
          color: isUser ? 'var(--text-inverse)' : 'var(--text)',
          border: isUser ? 'none' : '1px solid var(--border)',
          fontSize: 13,
          lineHeight: 1.6,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          opacity: message.pending && !message.content ? 0.5 : 1,
        }}>
          {message.content || (message.pending ? '⋯' : '')}
        </div>

        {/* 근거 (접이식) */}
        {!isUser && evidence.length > 0 && (
          <details style={{ fontSize: 11 }}>
            <summary className="text-muted" style={{ cursor: 'pointer' }}>근거 {evidence.length}건</summary>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
              {evidence.map((ev, i) => (
                <div key={ev.id || i} className="text-sm text-muted" style={{ borderLeft: '2px solid var(--border)', paddingLeft: 8 }}>
                  <strong>{ev.title || ev.source_type || `근거 ${i + 1}`}</strong>
                  {ev.snippet ? <div style={{ whiteSpace: 'pre-wrap' }}>{ev.snippet}</div> : null}
                </div>
              ))}
            </div>
          </details>
        )}

        {/* 다음 단계 (클릭 시 자동 전송) */}
        {!isUser && nextSteps.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {nextSteps.map((step, i) => (
              <button key={i} className="pill pill-info" style={{ fontSize: 10, cursor: 'pointer' }}
                onClick={() => onNextStep?.(step)} title="이 단계를 질문으로 전송">
                {step}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
