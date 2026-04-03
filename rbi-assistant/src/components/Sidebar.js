import React, { useState } from 'react';
import './Sidebar.css';

const NAV = [
  {
    id: 'chat',
    label: 'Ask a Question',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
    ),
  },
  {
    id: 'upload',
    label: 'Upload Circular',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
        <polyline points="17 8 12 3 7 8"/>
        <line x1="12" y1="3" x2="12" y2="15"/>
      </svg>
    ),
  },
  {
    id: 'visualize',
    label: 'Rule Visualizer',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="18" cy="5"  r="3"/><circle cx="6"  cy="12" r="3"/>
        <circle cx="18" cy="19" r="3"/>
        <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
        <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
      </svg>
    ),
  },
  {
    id: 'compliance',
    label: 'Compliance Check',
    icon: (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <polyline points="9 11 12 14 22 4"/>
        <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>
      </svg>
    ),
  },
];

export default function Sidebar({ active, onNav }) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      {/* Logo */}
      <div className="sidebar-logo">
        <div className="sidebar-emblem">₹</div>
        {!collapsed && (
          <div className="sidebar-brand">
            <span className="sidebar-brand-name">RBI Assistant</span>
            <span className="sidebar-brand-sub">Compliance Platform</span>
          </div>
        )}
        <button className="sidebar-collapse-btn" onClick={() => setCollapsed(!collapsed)} title="Toggle sidebar">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
            {collapsed
              ? <path d="M9 18l6-6-6-6"/>
              : <path d="M15 18l-6-6 6-6"/>
            }
          </svg>
        </button>
      </div>

      {/* Nav */}
      <nav className="sidebar-nav">
        {!collapsed && <div className="sidebar-section-label">Navigation</div>}
        {NAV.map(item => (
          <button
            key={item.id}
            className={`sidebar-nav-item ${active === item.id ? 'active' : ''}`}
            onClick={() => onNav(item.id)}
            title={collapsed ? item.label : ''}
          >
            <span className="sidebar-nav-icon">{item.icon}</span>
            {!collapsed && <span className="sidebar-nav-label">{item.label}</span>}
            {active === item.id && <span className="sidebar-nav-indicator" />}
          </button>
        ))}
      </nav>

      {/* Footer */}
      {!collapsed && (
        <div className="sidebar-footer">
          <div className="sidebar-footer-line">
            <span className="status-dot" />
            <span>Backend connected</span>
          </div>
          <div className="sidebar-footer-line">v2.0 · Gemini RAG</div>
        </div>
      )}
    </aside>
  );
}
