import React, { useState, useRef, useEffect } from 'react';
import { askQuery, TOPIC_COLORS, FOLDER_SUBTOPICS } from '../utils/api';
import './ChatPage.css';

const TOPICS = Object.keys(FOLDER_SUBTOPICS);

const SUGGESTED = [
  'What are the KYC requirements for opening a savings account?',
  'Explain NPA classification norms for commercial banks.',
  'What is the capital adequacy requirement under Basel III?',
  'Describe RBI guidelines on cash transaction reporting (CTR).',
];

function ConfidenceBadge({ level }) {
  const map = { high: '#1a9e6e', medium: '#c8a84b', low: '#d94f4f' };
  return (
    <span className="confidence-badge" style={{ borderColor: map[level] || '#888', color: map[level] || '#888' }}>
      {level} confidence
    </span>
  );
}

function MessageBubble({ msg }) {
  if (msg.role === 'user') {
    return (
      <div className="chat-msg chat-msg--user">
        <div className="chat-bubble chat-bubble--user">{msg.content}</div>
      </div>
    );
  }

  if (msg.loading) {
    return (
      <div className="chat-msg chat-msg--assistant">
        <div className="chat-avatar">₹</div>
        <div className="chat-bubble chat-bubble--assistant chat-bubble--loading">
          <span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" />
        </div>
      </div>
    );
  }

  const data = msg.data || {};
  const answer = data.answer || msg.content || '';

  return (
    <div className="chat-msg chat-msg--assistant fade-in">
      <div className="chat-avatar">₹</div>
      <div className="chat-bubble chat-bubble--assistant">
        {/* Answer text */}
        <div className="chat-answer">{answer}</div>

        {/* Metadata row */}
        <div className="chat-meta">
          {data.confidence && <ConfidenceBadge level={data.confidence} />}
          {data.fallback_used && (
            <span className="meta-tag meta-tag--warn">General knowledge</span>
          )}
          {data.sources_used > 0 && (
            <span className="meta-tag">{data.sources_used} source{data.sources_used !== 1 ? 's' : ''}</span>
          )}
          {data.rules_matched > 0 && (
            <span className="meta-tag">{data.rules_matched} rule{data.rules_matched !== 1 ? 's' : ''} matched</span>
          )}
        </div>

        {/* Rule IDs */}
        {data.relevant_rule_ids && data.relevant_rule_ids.length > 0 && (
          <div className="chat-rules">
            <div className="chat-rules-label">Referenced Rules</div>
            <div className="chat-rules-list">
              {data.relevant_rule_ids.map(id => (
                <span key={id} className="rule-chip">{id}</span>
              ))}
            </div>
          </div>
        )}

        {/* Source circulars */}
        {data.source_circulars && data.source_circulars.length > 0 && (
          <div className="chat-rules">
            <div className="chat-rules-label">Source Circulars</div>
            <div className="chat-rules-list">
              {data.source_circulars.map(id => (
                <span key={id} className="rule-chip rule-chip--circular">{id}</span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [topicFilter, setTopicFilter] = useState('');
  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const send = async (text) => {
    const q = (text || input).trim();
    if (!q || loading) return;
    setInput('');

    const userMsg = { role: 'user', content: q, id: Date.now() };
    const loadMsg = { role: 'assistant', loading: true, id: Date.now() + 1 };
    setMessages(prev => [...prev, userMsg, loadMsg]);
    setLoading(true);

    try {
      const res = await askQuery(q, topicFilter || null);
      const data = res.data;
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: 'assistant', content: data.answer, data, id: Date.now() + 2 },
      ]);
    } catch (err) {
      const errMsg = err.response?.data?.detail || err.message || 'Network error';
      setMessages(prev => [
        ...prev.slice(0, -1),
        { role: 'assistant', content: `⚠️ ${errMsg}`, id: Date.now() + 2 },
      ]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  };

  return (
    <div className="chat-page">
      {/* Top bar */}
      <div className="chat-topbar">
        <div className="chat-topbar-left">
          <h2 className="chat-title">Ask a Compliance Question</h2>
          <span className="chat-subtitle">Powered by RBI circular knowledge base</span>
        </div>
        <div className="chat-topbar-right">
          <label className="filter-label-sm">Filter by topic</label>
          <select
            className="chat-topic-select"
            value={topicFilter}
            onChange={e => setTopicFilter(e.target.value)}
          >
            <option value="">All topics</option>
            {TOPICS.map(t => (
              <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Messages */}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">
            <div className="chat-empty-icon">⚖️</div>
            <h3>What would you like to know?</h3>
            <p>Ask any question about RBI regulations, circulars, or compliance requirements.</p>
            <div className="suggested-grid">
              {SUGGESTED.map((s, i) => (
                <button key={i} className="suggested-chip" onClick={() => send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="chat-input-area">
        <div className="chat-input-wrap">
          <textarea
            ref={inputRef}
            className="chat-input"
            placeholder="Ask about any RBI regulation, circular, or compliance requirement…"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            rows={1}
            disabled={loading}
          />
          <button
            className="chat-send-btn"
            onClick={() => send()}
            disabled={!input.trim() || loading}
          >
            {loading
              ? <span className="send-spinner" />
              : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <line x1="22" y1="2" x2="11" y2="13"/>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"/>
                </svg>
              )
            }
          </button>
        </div>
        <div className="chat-input-hint">Press Enter to send · Shift+Enter for new line</div>
      </div>
    </div>
  );
}
