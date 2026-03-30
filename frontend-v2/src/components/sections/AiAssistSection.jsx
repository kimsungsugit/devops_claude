import { useState, useRef, useCallback, useEffect } from 'react';
import { post, defaultCacheRoot } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';

export default function AiAssistSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [pending, setPending] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = useCallback(async () => {
    const q = input.trim();
    if (!q || pending) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: q }]);
    setPending(true);
    setMessages(prev => [...prev, { role: 'assistant', content: '', pending: true }]);

    try {
      const data = await post('/api/jenkins/rag/query', {
        job_url: job?.url ?? '',
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector || 'lastSuccessfulBuild',
        query: q,
        top_k: 5,
      });

      // Build answer from items or direct answer field
      let answer = '';
      if (typeof data?.answer === 'string') {
        answer = data.answer;
      } else if (Array.isArray(data?.items) && data.items.length > 0) {
        answer = data.items.map((item, i) =>
          `**[${i + 1}]** ${item.content ?? item.text ?? item.chunk ?? ''}\n\n` +
          (item.source ? `📄 출처: ${item.source}\n` : '')
        ).join('\n---\n');
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
  }, [input, pending, job, cfg, cacheRoot, toast]);

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="panel" style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 220px)', minHeight: 400 }}>
      <div className="panel-header">
        <span className="panel-title">🤖 AI 어시스턴트 (RAG)</span>
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
              ].map(q => (
                <button key={q} onClick={() => setInput(q)} style={{ textAlign: 'left', fontSize: 12 }}>
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
      <div className="row mt-2" style={{ gap: 8, alignItems: 'flex-end' }}>
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
