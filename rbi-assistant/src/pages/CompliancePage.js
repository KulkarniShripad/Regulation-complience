import React, { useState } from 'react';
import { checkCompliance, FOLDER_SUBTOPICS } from '../utils/api';
import './CompliancePage.css';

const TOPICS = Object.keys(FOLDER_SUBTOPICS);

const ENTITY_TYPES = [
  'commercial_bank', 'NBFC', 'payment_bank', 'small_finance_bank',
  'cooperative_bank', 'KYC', 'AML', 'forex',
];

const FIELD_GROUPS = [
  {
    label: 'Account & Entity',
    fields: [
      { key: 'account_type',   label: 'Account Type',    placeholder: 'e.g., savings, current, NRE' },
      { key: 'entity_type',    label: 'Entity Type',      placeholder: 'e.g., individual, corporate, NBFC' },
      { key: 'kyc_status',     label: 'KYC Status',       placeholder: 'e.g., full_kyc, simplified, pending' },
    ],
  },
  {
    label: 'Transaction Data',
    fields: [
      { key: 'transaction_amount',   label: 'Transaction Amount (₹)', placeholder: 'e.g., 500000' },
      { key: 'cash_transaction',     label: 'Cash Transaction (₹)',    placeholder: 'e.g., 200000' },
      { key: 'foreign_remittance',   label: 'Foreign Remittance (₹)',  placeholder: 'e.g., 1000000' },
    ],
  },
  {
    label: 'Capital & Ratios',
    fields: [
      { key: 'crar_percentage',         label: 'CRAR (%)',              placeholder: 'e.g., 11.5' },
      { key: 'npa_percentage',          label: 'NPA Ratio (%)',         placeholder: 'e.g., 3.2' },
      { key: 'priority_sector_percentage', label: 'Priority Sector (%)', placeholder: 'e.g., 38' },
    ],
  },
  {
    label: 'Deposit & Lending',
    fields: [
      { key: 'deposit_amount',    label: 'Deposit Amount (₹)',    placeholder: 'e.g., 200000' },
      { key: 'loan_amount',       label: 'Loan Amount (₹)',        placeholder: 'e.g., 5000000' },
      { key: 'monetary_limit',    label: 'Monetary Limit (₹)',     placeholder: 'e.g., 10000000' },
    ],
  },
];

function StatusBadge({ status }) {
  const map = {
    COMPLIANT:         { color: '#1a9e6e', bg: 'rgba(26,158,110,0.12)', icon: '✅', label: 'Compliant' },
    NON_COMPLIANT:     { color: '#d94f4f', bg: 'rgba(217,79,79,0.12)',  icon: '❌', label: 'Non-Compliant' },
    INSUFFICIENT_DATA: { color: '#c8a84b', bg: 'rgba(200,168,75,0.12)', icon: '⚠️', label: 'Insufficient Data' },
  };
  const s = map[status] || map.INSUFFICIENT_DATA;
  return (
    <div className="status-badge" style={{ background: s.bg, borderColor: s.color + '55', color: s.color }}>
      <span>{s.icon}</span>
      <span>{s.label}</span>
    </div>
  );
}

function ResultSection({ title, items, variant }) {
  const [open, setOpen] = useState(true);
  if (!items || items.length === 0) return null;
  return (
    <div className={`result-section result-section--${variant}`}>
      <button className="result-section-header" onClick={() => setOpen(o => !o)}>
        <span className="result-section-title">{title} ({items.length})</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"
          style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>
      {open && (
        <div className="result-items">
          {items.map((item, i) => (
            <div className="result-item-card" key={i}>
              <div className="ric-header">
                <span className="ric-id">{item.rule_id}</span>
                <span className="ric-topic" style={{ color: '#7F77DD' }}>
                  {(item.topic || '').replace(/_/g, ' ')} / {(item.subtopic || '').replace(/_/g, ' ')}
                </span>
              </div>
              <div className="ric-title">{item.title}</div>
              {item.violations && item.violations.map((v, j) => (
                <div className="ric-violation" key={j}>⚠ {v}</div>
              ))}
              {item.passed && item.passed.map((p, j) => (
                <div className="ric-passed" key={j}>✓ {p}</div>
              ))}
              {item.summary && <div className="ric-summary">{item.summary}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CompliancePage() {
  const [formData, setFormData]   = useState({});
  const [topic, setTopic]         = useState('');
  const [entityType, setEntityType] = useState('');
  const [rawMode, setRawMode]     = useState(false);
  const [rawText, setRawText]     = useState('');
  const [loading, setLoading]     = useState(false);
  const [result, setResult]       = useState(null);
  const [error, setError]         = useState('');

  const handleField = (key, val) => {
    setFormData(prev => val ? { ...prev, [key]: val } : Object.fromEntries(Object.entries(prev).filter(([k]) => k !== key)));
  };

  const buildInputString = () => {
    if (rawMode) return rawText;
    return Object.entries(formData).map(([k, v]) => `${k}: ${v}`).join('\n');
  };

  const handleSubmit = async () => {
    const inputStr = buildInputString();
    if (!inputStr.trim()) { setError('Please fill in at least one field.'); return; }
    setError(''); setLoading(true); setResult(null);
    try {
      const res = await checkCompliance(inputStr, topic || null, entityType || null);
      setResult(res.data);
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Check failed');
    } finally {
      setLoading(false);
    }
  };

  const reset = () => {
    setFormData({}); setRawText(''); setResult(null); setError('');
    setTopic(''); setEntityType('');
  };

  return (
    <div className="compliance-page">
      {/* Top bar */}
      <div className="compliance-topbar">
        <div>
          <h2 className="page-title">Compliance Checker</h2>
          <span className="page-subtitle">Validate operational data against active RBI rules</span>
        </div>
        <div className="compliance-topbar-right">
          <button className={`mode-toggle-btn ${!rawMode ? 'active' : ''}`} onClick={() => setRawMode(false)}>Form</button>
          <button className={`mode-toggle-btn ${rawMode  ? 'active' : ''}`} onClick={() => setRawMode(true)}>Raw Text</button>
        </div>
      </div>

      <div className="compliance-body">
        {/* LEFT: Input */}
        <div className="compliance-input-col">
          {/* Topic & entity filters */}
          <div className="comp-filter-row">
            <div className="comp-filter-item">
              <label className="comp-label">Topic (optional)</label>
              <select className="comp-select" value={topic} onChange={e => setTopic(e.target.value)}>
                <option value="">All topics</option>
                {TOPICS.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
              </select>
            </div>
            <div className="comp-filter-item">
              <label className="comp-label">Entity Type (optional)</label>
              <select className="comp-select" value={entityType} onChange={e => setEntityType(e.target.value)}>
                <option value="">Any entity</option>
                {ENTITY_TYPES.map(e => <option key={e} value={e}>{e.replace(/_/g, ' ')}</option>)}
              </select>
            </div>
          </div>

          {/* Form or raw */}
          {rawMode ? (
            <div className="raw-input-wrap">
              <label className="comp-label">Enter data as key: value (one per line) or JSON</label>
              <textarea
                className="raw-textarea"
                placeholder={`transaction_amount: 500000\nkyc_status: full_kyc\ncrar_percentage: 9.5\n\nOr paste JSON: {"transaction_amount": 500000}`}
                value={rawText}
                onChange={e => setRawText(e.target.value)}
                rows={12}
              />
            </div>
          ) : (
            <div className="field-groups">
              {FIELD_GROUPS.map(group => (
                <div className="field-group" key={group.label}>
                  <div className="field-group-label">{group.label}</div>
                  <div className="field-group-grid">
                    {group.fields.map(f => (
                      <div className="field-item" key={f.key}>
                        <label className="field-label">{f.label}</label>
                        <input
                          className="field-input"
                          type="text"
                          placeholder={f.placeholder}
                          value={formData[f.key] || ''}
                          onChange={e => handleField(f.key, e.target.value)}
                        />
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}

          {error && <div className="comp-error">{error}</div>}

          <div className="comp-actions">
            <button className="comp-submit-btn" disabled={loading} onClick={handleSubmit}>
              {loading
                ? <><span className="btn-spinner" /> Checking rules…</>
                : <>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                      <polyline points="9 11 12 14 22 4"/>
                      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
                    </svg>
                    Run Compliance Check
                  </>
              }
            </button>
            <button className="comp-reset-btn" onClick={reset}>Reset</button>
          </div>
        </div>

        {/* RIGHT: Results */}
        <div className="compliance-result-col">
          {!result && !loading && (
            <div className="comp-placeholder">
              <div className="comp-placeholder-icon">⚖️</div>
              <h3>Ready to Check</h3>
              <p>Fill in the form fields with your operational data, then run the compliance check to see which RBI rules apply and whether any limits are breached.</p>
              <div className="comp-placeholder-tips">
                <div className="tip">💡 Leave fields blank to skip them</div>
                <div className="tip">💡 Amounts should be in ₹ (rupees)</div>
                <div className="tip">💡 Ratios and percentages as numbers (e.g., 11.5)</div>
              </div>
            </div>
          )}

          {result && (
            <div className="result-panel fade-in">
              {/* Header */}
              <div className="result-header">
                <StatusBadge status={result.overall_status} />
                <div className="result-header-stats">
                  <span className="rhs-item">
                    <span className="rhs-num" style={{ color: '#d94f4f' }}>{result.violations_count}</span>
                    <span className="rhs-label">Violations</span>
                  </span>
                  <span className="rhs-divider">|</span>
                  <span className="rhs-item">
                    <span className="rhs-num" style={{ color: '#1a9e6e' }}>{result.passed_count}</span>
                    <span className="rhs-label">Passed</span>
                  </span>
                  <span className="rhs-divider">|</span>
                  <span className="rhs-item">
                    <span className="rhs-num" style={{ color: '#888' }}>{result.rules_evaluated}</span>
                    <span className="rhs-label">Evaluated</span>
                  </span>
                </div>
              </div>

              {/* AI Summary */}
              {result.summary && (
                <div className="result-summary">
                  <div className="result-summary-label">
                    <span>🤖</span> AI Analysis
                  </div>
                  <p>{result.summary}</p>
                </div>
              )}

              {/* Parsed input */}
              <div className="result-parsed">
                <div className="result-summary-label">Input Parsed</div>
                <div className="parsed-grid">
                  {Object.entries(result.input_parsed || {}).map(([k, v]) => (
                    <div className="parsed-item" key={k}>
                      <span className="parsed-key">{k.replace(/_/g, ' ')}</span>
                      <span className="parsed-val">{v}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Violations */}
              <ResultSection title="Violations Found" items={result.violations} variant="violation" />

              {/* Passed */}
              <ResultSection title="Checks Passed" items={result.passed} variant="passed" />

              <div className="result-footer">
                Checked at {new Date(result.checked_at).toLocaleString('en-IN')} · Topic: {result.topic_checked}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
