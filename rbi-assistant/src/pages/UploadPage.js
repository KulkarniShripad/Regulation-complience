import React, { useState, useRef } from 'react';
import { uploadCircular, FOLDER_SUBTOPICS } from '../utils/api';
import './UploadPage.css';

const TOPICS = Object.keys(FOLDER_SUBTOPICS);

export default function UploadPage() {
  const [file, setFile]     = useState(null);
  const [topic, setTopic]   = useState('general');
  const [title, setTitle]   = useState('');
  const [status, setStatus] = useState(null); // null | 'loading' | 'success' | 'error'
  const [result, setResult] = useState(null);
  const [error, setError]   = useState('');
  const [drag, setDrag]     = useState(false);
  const fileRef             = useRef(null);

  const handleFile = (f) => {
    if (!f) return;
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      setError('Only PDF files are accepted.');
      return;
    }
    if (f.size > 50 * 1024 * 1024) {
      setError('File too large. Maximum size is 50 MB.');
      return;
    }
    setFile(f);
    setError('');
    setStatus(null);
    setResult(null);
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files[0];
    handleFile(f);
  };

  const onUpload = async () => {
    if (!file) return;
    setStatus('loading');
    setError('');
    setResult(null);
    try {
      const res = await uploadCircular(file, topic, title || null);
      setResult(res.data);
      setStatus('success');
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Upload failed';
      setError(msg);
      setStatus('error');
    }
  };

  const reset = () => {
    setFile(null); setStatus(null); setResult(null); setError('');
    setTitle(''); setTopic('general');
  };

  return (
    <div className="upload-page">
      <div className="upload-topbar">
        <h2 className="page-title">Upload RBI Circular</h2>
        <span className="page-subtitle">Add new regulatory documents to the compliance knowledge base</span>
      </div>

      <div className="upload-content">
        {/* Left: form */}
        <div className="upload-form-col">
          {/* Drop zone */}
          <div
            className={`drop-zone ${drag ? 'drag-over' : ''} ${file ? 'has-file' : ''}`}
            onDragOver={e => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            onClick={() => !file && fileRef.current?.click()}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".pdf"
              style={{ display: 'none' }}
              onChange={e => handleFile(e.target.files[0])}
            />
            {file ? (
              <div className="file-selected">
                <div className="file-icon">📄</div>
                <div className="file-info">
                  <div className="file-name">{file.name}</div>
                  <div className="file-size">{(file.size / 1024).toFixed(1)} KB</div>
                </div>
                <button className="file-remove" onClick={(e) => { e.stopPropagation(); reset(); }}>×</button>
              </div>
            ) : (
              <div className="drop-content">
                <div className="drop-icon">📂</div>
                <div className="drop-text">Drop PDF here or <span className="drop-link">browse</span></div>
                <div className="drop-hint">PDF only · Max 50 MB</div>
              </div>
            )}
          </div>

          {/* Form fields */}
          <div className="form-group">
            <label className="form-label">Topic / Category</label>
            <select className="form-select" value={topic} onChange={e => setTopic(e.target.value)}>
              {TOPICS.map(t => (
                <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>
              ))}
            </select>
            <div className="form-hint">
              Subtopics: {(FOLDER_SUBTOPICS[topic] || []).join(' · ')}
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Title <span className="optional">(optional)</span></label>
            <input
              type="text"
              className="form-input"
              placeholder="e.g., RBI/2024-25/101 KYC Amendment"
              value={title}
              onChange={e => setTitle(e.target.value)}
            />
          </div>

          {error && <div className="upload-error">{error}</div>}

          <button
            className="upload-btn"
            disabled={!file || status === 'loading'}
            onClick={onUpload}
          >
            {status === 'loading'
              ? <><span className="btn-spinner" /> Processing…</>
              : <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="17 8 12 3 7 8"/>
                    <line x1="12" y1="3" x2="12" y2="15"/>
                  </svg>
                  Upload &amp; Ingest Circular
                </>
            }
          </button>
        </div>

        {/* Right: result / info */}
        <div className="upload-result-col">
          {status === 'success' && result && (
            <div className="result-card result-card--success fade-in">
              <div className="result-icon">✅</div>
              <h3 className="result-title">Circular Ingested Successfully</h3>
              <div className="result-grid">
                <div className="result-item">
                  <span className="result-label">Circular ID</span>
                  <span className="result-value font-mono">{result.circular_id}</span>
                </div>
                <div className="result-item">
                  <span className="result-label">Title</span>
                  <span className="result-value">{result.title}</span>
                </div>
                <div className="result-item">
                  <span className="result-label">Topic</span>
                  <span className="result-value">{result.topic?.replace(/_/g, ' ')}</span>
                </div>
                <div className="result-item">
                  <span className="result-label">Rules Extracted</span>
                  <span className="result-value result-value--gold">{result.rules_extracted}</span>
                </div>
                <div className="result-item">
                  <span className="result-label">Chunks Embedded</span>
                  <span className="result-value result-value--gold">{result.chunks_embedded}</span>
                </div>
                <div className="result-item">
                  <span className="result-label">Word Count</span>
                  <span className="result-value">{result.word_count?.toLocaleString()}</span>
                </div>
              </div>
              <button className="reset-btn" onClick={reset}>Upload Another</button>
            </div>
          )}

          {status !== 'success' && (
            <div className="upload-info-card">
              <h3 className="info-title">What happens when you upload?</h3>
              <div className="info-steps">
                {[
                  ['📑', 'Text extraction', 'PyMuPDF extracts all text from the PDF circular.'],
                  ['🔍', 'Rule parsing', 'Obligation keywords identify clauses with compliance requirements.'],
                  ['🧠', 'Embedding', 'Sentence Transformer creates semantic vectors stored in Qdrant.'],
                  ['💾', 'Indexing', 'Rules and metadata are stored in MongoDB for fast retrieval.'],
                ].map(([icon, step, desc], i) => (
                  <div className="info-step" key={i}>
                    <div className="info-step-icon">{icon}</div>
                    <div>
                      <div className="info-step-title">{step}</div>
                      <div className="info-step-desc">{desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
