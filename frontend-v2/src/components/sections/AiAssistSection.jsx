import { useState, useRef, useCallback, useEffect } from 'react';
import { post, api, defaultCacheRoot } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

export default function AiAssistSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const [ragStatus, setRagStatus] = useState(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [topK, setTopK] = useState(5);
  const [category, setCategory] = useState('');
  const bottomRef = useRef(null);
  const sendRef = useRef(null);

  // Auto-send when a suggested question is clicked
  useEffect(() => {
    if (sendRef.current && !pending) {
      const q = sendRef.current;
      sendRef.current = null;
      setInput('');
      setMessages(prev => [...prev, { role: 'user', content: q }]);
      setPending(true);
      setMessages(prev => [...prev, { role: 'assistant', content: '', pending: true }]);
      (async () => {
        try {
          const payload = { job_url: job?.url ?? '', cache_root: cacheRoot, build_selector: cfg.buildSelector || 'lastSuccessfulBuild', query: q, top_k: topK };
          if (category) payload.categories = [category];
          const data = await post('/api/jenkins/rag/query', payload);
          let answer = typeof data?.answer === 'string' ? data.answer
            : Array.isArray(data?.items) && data.items.length > 0
              ? data.items.map((item, i) => `**[${i+1}]**${item.score != null ? ` (${(item.score*100).toFixed(0)}%)` : ''}\n${item.content ?? item.text ?? ''}\n${item.source ? `📄 ${item.source}` : ''}`).join('\n---\n')
              : '관련 정보를 찾을 수 없습니다.';
          setMessages(prev => { const n=[...prev]; if(n[n.length-1]?.role==='assistant') n[n.length-1]={role:'assistant',content:answer}; return n; });
        } catch (e) {
          setMessages(prev => { const n=[...prev]; if(n[n.length-1]?.role==='assistant') n[n.length-1]={role:'assistant',content:`오류: ${e.message}`}; return n; });
        } finally { setPending(false); }
      })();
    }
  }, [input]); // triggers when setInput(q) completes

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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

  // 마운트 시 RAG 상태 자동 확인
  useEffect(() => {
    loadRagStatus();
  }, [loadRagStatus]);

  const send = useCallback(async () => {
    const q = input.trim();
    if (!q || pending) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setPending(true);
    setMessages(prev => [...prev, { role: 'assistant', content: '', pending: true }]);

    try {
      const payload = {
        job_url: job?.url ?? '',
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector || 'lastSuccessfulBuild',
        query: q,
        top_k: topK,
      };
      if (category) payload.categories = [category];

      const data = await post('/api/jenkins/rag/query', payload);

      let answer = '';
      if (typeof data?.answer === 'string') {
        answer = data.answer;
      } else if (Array.isArray(data?.items) && data.items.length > 0) {
        answer = data.items.map((item, i) => {
          const content = item.content ?? item.text ?? item.chunk ?? '';
          const source = item.source ?? item.metadata?.source ?? '';
          const score = item.score ?? item.relevance_score;
          return `**[${i + 1}]**${score != null ? ` (${(score * 100).toFixed(0)}%)` : ''}\n${content}\n` +
            (source ? `📄 ${source}\n` : '');
        }).join('\n---\n');
      } else {
        answer = '관련 정보를 찾을 수 없습니다. RAG 데이터를 먼저 수집해주세요.';
      }

      setMessages(prev => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === 'assistant') next[next.length - 1] = { role: 'assistant', content: answer };
        return next;
      });
    } catch (e) {
      const errMsg = `오류: ${e.message}`;
      setMessages(prev => {
        const next = [...prev];
        const last = next[next.length - 1];
        if (last?.role === 'assistant') next[next.length - 1] = { role: 'assistant', content: errMsg };
        return next;
      });
      toast('error', e.message);
    } finally {
      setPending(false);
    }
  }, [input, pending, job, cfg, cacheRoot, topK, category, toast]);

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
          <div className="row" style={{ gap: 6 }}>
            <select
              value={category}
              onChange={e => setCategory(e.target.value)}
              style={{ fontSize: 11, padding: '3px 6px' }}
            >
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
              {ragStatus?.categories && Object.keys(ragStatus.categories)
                .filter(c => !['requirements', 'uds', 'code', 'general'].includes(c))
                .map(c => <option key={c} value={c}>{c}</option>)
              }
            </select>
            <select
              value={topK}
              onChange={e => setTopK(Number(e.target.value))}
              style={{ fontSize: 11, padding: '3px 6px', width: 60 }}
            >
              {[3, 5, 10, 15, 20].map(n => <option key={n} value={n}>Top {n}</option>)}
            </select>
            <button className="btn-sm" onClick={loadRagStatus} disabled={statusLoading} style={{ fontSize: 10 }}>
              {statusLoading ? '...' : '상태 확인'}
            </button>
          </div>
        </div>

        {/* Category breakdown */}
        {ragStatus?.stats?.by_category && Object.keys(ragStatus.stats.by_category).length > 0 && (
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

      {/* Chat panel */}
      <div className="panel" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div className="panel-header" style={{ flexShrink: 0 }}>
          <span className="panel-title">AI 어시스턴트</span>
          {messages.length > 0 && (
            <button className="btn-sm" onClick={() => setMessages([])}>대화 초기화</button>
          )}
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
                  <button key={q} onClick={() => { setInput(q); sendRef.current = q; }} style={{ textAlign: 'left', fontSize: 12 }}>
                    {q}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            messages.map((m, i) => <ChatBubble key={i} message={m} />)
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
            onClick={send}
            disabled={pending || !input.trim()}
            style={{ height: 52, width: 60, flexShrink: 0 }}
          >
            {pending ? <span className="spinner" style={{ display: 'inline-block' }} /> : '전송'}
          </button>
        </div>
      </div>
    </div>
  );
}

function ChatBubble({ message }) {
  const isUser = message.role === 'user';
  return (
    <div style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
      <div style={{
        maxWidth: '82%',
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
    </div>
  );
}
