import React, { useState, useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import { getVisualizationData, TOPIC_COLORS } from '../utils/api';
import './VisualizationPage.css';

const EDGE_COLORS = {
  modifies:   '#EF9F27',
  overrides:  '#E24B4A',
  depends_on: '#7F77DD',
  references: '#888780',
  clarifies:  '#1D9E75',
  supersedes: '#D85A30',
};

/* ─── Detail Panel ─── */
function DetailPanel({ node, onClose }) {
  if (!node) return null;
  const reqs = node.requirements || [];
  return (
    <div className="detail-panel fade-in">
      <button className="detail-close" onClick={onClose}>×</button>
      <div className="detail-title">{node.label || node.id}</div>

      {node.type === 'topic' ? (
        <>
          <DetailRow label="Topic" value={<span style={{ color: node.color }}>{(node.id || '').replace('topic_', '').replace(/_/g, ' ')}</span>} />
          <DetailRow label="Rule Count" value={node.rule_count ?? 0} />
          <DetailRow label="Subtopics" value={(node.subtopics || []).join(', ') || '—'} />
        </>
      ) : (
        <>
          <DetailRow label="Rule ID" value={<span className="mono-val">{node.id}</span>} />
          <DetailRow label="Topic / Subtopic" value={
            <span style={{ color: node.color }}>
              {(node.topic || '').replace(/_/g, ' ')} / {(node.subtopic || '').replace(/_/g, ' ')}
            </span>
          } />
          <DetailRow label="Summary" value={node.summary || '—'} />
          {reqs.length > 0 && (
            <div className="detail-section">
              <div className="detail-label">Requirements</div>
              {reqs.map((r, i) => (
                <div className="req-block" key={i}>
                  <span className="req-type">{r.type}</span>
                  <span className="req-val">
                    {r.value != null ? Number(r.value).toLocaleString('en-IN') : '—'}
                    {r.currency ? ` ${r.currency}` : (r.type === 'percentage_limit' ? '%' : '')}
                  </span>
                  {r.description && <div className="req-desc">{r.description}</div>}
                </div>
              ))}
            </div>
          )}
          <DetailRow label="Circular" value={<span className="mono-val sm">{node.circular_id || '—'}</span>} />
          {node.effective_date && <DetailRow label="Effective Date" value={node.effective_date} />}
          <div className="detail-section">
            <div className="detail-label">Tags</div>
            <div className="tag-row">
              {(node.tags || []).map(t => <span className="dtag" key={t}>{t}</span>)}
            </div>
          </div>
          <DetailRow label="Status" value={
            <span style={{ color: node.is_active ? '#1a9e6e' : '#d94f4f' }}>
              {node.is_active ? 'Active' : 'Inactive'}
            </span>
          } />
        </>
      )}
    </div>
  );
}

function DetailRow({ label, value }) {
  return (
    <div className="detail-section">
      <div className="detail-label">{label}</div>
      <div className="detail-value">{value}</div>
    </div>
  );
}

/* ─── List View ─── */
function ListView({ nodes, onSelect }) {
  const rules = nodes.filter(n => n.type === 'rule');
  if (rules.length === 0) {
    return <div className="list-empty">No rules match the current filters.</div>;
  }
  return (
    <div className="list-view">
      {rules.map(r => (
        <div className="rule-card" key={r.id} onClick={() => onSelect(r)}>
          <div className="rc-header">
            <span className="rc-id">{r.id}</span>
            <span className="rc-title">{r.label}</span>
            <span className="rc-topic-badge" style={{ background: r.color + '33', color: r.color }}>
              {(r.topic || '').replace(/_/g, ' ')}
            </span>
          </div>
          <div className="rc-summary">{r.summary || ''}</div>
          <div className="rc-tags">
            {(r.tags || []).map(t => <span className="rc-tag" key={t}>{t}</span>)}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ─── Main Component ─── */
export default function VisualizationPage() {
  const svgRef      = useRef(null);
  const simRef      = useRef(null);
  const wrapRef     = useRef(null);

  const [data, setData]           = useState(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState('');
  const [view, setView]           = useState('graph'); // 'graph' | 'list'
  const [selected, setSelected]   = useState(null);
  const [search, setSearch]       = useState('');
  const [searchTimer, setSearchTimer] = useState(null);

  // Filters
  const [filters, setFilters] = useState({ topic: '', subtopic: '', tag: '', is_active: 'true' });
  const [filterOpts, setFilterOpts] = useState({ topics: [], subtopics: [], tags: [] });

  const loadData = useCallback(async (params = {}) => {
    setLoading(true);
    setError('');
    try {
      const res = await getVisualizationData({ limit: 300, ...params });
      const d   = res.data;
      setData(d);
      if (d.filters) setFilterOpts(d.filters);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const applyFilters = useCallback(() => {
    const p = {};
    if (filters.topic)    p.topic    = filters.topic;
    if (filters.subtopic) p.subtopic = filters.subtopic;
    if (filters.tag)      p.tag      = filters.tag;
    if (filters.is_active !== '') p.is_active = filters.is_active;
    if (search.trim())    p.search   = search.trim();
    loadData(p);
  }, [filters, search, loadData]);

  const handleSearchChange = (val) => {
    setSearch(val);
    clearTimeout(searchTimer);
    setSearchTimer(setTimeout(() => {
      const p = {};
      if (filters.topic)    p.topic    = filters.topic;
      if (filters.subtopic) p.subtopic = filters.subtopic;
      if (filters.tag)      p.tag      = filters.tag;
      if (filters.is_active !== '') p.is_active = filters.is_active;
      if (val.trim()) p.search = val.trim();
      loadData(p);
    }, 450));
  };

  const resetFilters = () => {
    setFilters({ topic: '', subtopic: '', tag: '', is_active: 'true' });
    setSearch('');
    loadData();
  };

  /* ── D3 Graph ── */
  useEffect(() => {
    if (!data || view !== 'graph') return;
    const wrap = wrapRef.current;
    const svg  = d3.select(svgRef.current);
    if (!wrap) return;

    const W = wrap.clientWidth;
    const H = wrap.clientHeight;

    svg.selectAll('*').remove();
    if (simRef.current) simRef.current.stop();

    const nodes = (data.nodes || []);
    const topicNodes = nodes.filter(n => n.type === 'topic');
    const ruleNodes  = nodes.filter(n => n.type === 'rule');
    const allNodes   = [...topicNodes, ...ruleNodes];

    if (allNodes.length === 0) return;

    const R = Math.min(W, H) * 0.3;
    topicNodes.forEach((n, i) => {
      const angle  = (i / topicNodes.length) * 2 * Math.PI - Math.PI / 2;
      n.fx_hint    = W / 2 + R * Math.cos(angle);
      n.fy_hint    = H / 2 + R * Math.sin(angle);
    });

    const nodeIds = new Set(allNodes.map(n => n.id));
    const edges   = (data.edges || []).filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));

    const g = svg.append('g');
    svg.call(
      d3.zoom().scaleExtent([0.15, 5]).on('zoom', e => g.attr('transform', e.transform))
    );

    // Contain edges
    const containEdges = edges.filter(e => e.type === 'contains');
    const relEdges     = edges.filter(e => e.type !== 'contains');

    g.append('g').selectAll('line')
      .data(containEdges).enter().append('line')
      .attr('stroke', d => d.color || '#334')
      .attr('stroke-width', 0.6).attr('stroke-opacity', 0.2);

    const linkSel = g.append('g').selectAll('line')
      .data(relEdges).enter().append('line')
      .attr('stroke', d => d.color || '#444')
      .attr('stroke-width', 1.5).attr('stroke-opacity', 0.65)
      .attr('stroke-dasharray', d => d.type === 'references' ? '4 3' : 'none');

    const nodeG = g.append('g').selectAll('g')
      .data(allNodes).enter().append('g')
      .style('cursor', 'pointer')
      .on('click', (e, d) => setSelected(d))
      .call(
        d3.drag()
          .on('start', (e, d) => { if (!e.active) simRef.current.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
          .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
          .on('end',   (e, d) => { if (!e.active) simRef.current.alphaTarget(0); d.fx = null; d.fy = null; })
      );

    nodeG.append('circle')
      .attr('r', d => d.size || 20)
      .attr('fill',   d => d.color + (d.type === 'topic' ? '28' : '44'))
      .attr('stroke', d => d.color)
      .attr('stroke-width', d => d.type === 'topic' ? 2.5 : 1.5);

    nodeG.filter(d => d.type === 'topic')
      .append('text')
      .attr('text-anchor', 'middle').attr('dy', '0.35em')
      .attr('fill', d => d.color).attr('font-size', '12px').attr('font-weight', '800')
      .text(d => d.rule_count || '');

    nodeG.filter(d => d.type === 'topic')
      .append('text')
      .attr('text-anchor', 'middle').attr('dy', d => (d.size || 40) + 15)
      .attr('fill', d => d.color).attr('font-size', '10px').attr('font-weight', '700')
      .text(d => d.label);

    const sim = d3.forceSimulation(allNodes)
      .force('link',    d3.forceLink(edges).id(d => d.id).distance(d => d.type === 'contains' ? 80 : 130).strength(d => d.type === 'contains' ? 0.4 : 0.6))
      .force('charge',  d3.forceManyBody().strength(d => d.type === 'topic' ? -800 : -250))
      .force('center',  d3.forceCenter(W / 2, H / 2))
      .force('collide', d3.forceCollide().radius(d => (d.size || 20) + 12))
      .force('x', d3.forceX(d => d.fx_hint || W / 2).strength(d => d.type === 'topic' ? 0.5 : 0.02))
      .force('y', d3.forceY(d => d.fy_hint || H / 2).strength(d => d.type === 'topic' ? 0.5 : 0.02));

    simRef.current = sim;

    const allContain = g.selectAll('g:first-child line');
    sim.on('tick', () => {
      allContain.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      linkSel.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
             .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
      nodeG.attr('transform', d => `translate(${d.x},${d.y})`);
    });

    return () => sim.stop();
  }, [data, view]);

  const stats = data?.stats || {};
  const topicStats = stats.topic_stats || {};

  return (
    <div className="viz-page">
      {/* Sidebar filters */}
      <aside className="viz-sidebar">
        <div className="viz-sidebar-header">Filters</div>

        <div className="viz-filter-group">
          <label className="viz-filter-label">Topic</label>
          <select className="viz-select" value={filters.topic}
            onChange={e => setFilters(f => ({ ...f, topic: e.target.value }))}>
            <option value="">All topics</option>
            {filterOpts.topics.map(t => <option key={t} value={t}>{t.replace(/_/g, ' ')}</option>)}
          </select>

          <label className="viz-filter-label">Subtopic</label>
          <select className="viz-select" value={filters.subtopic}
            onChange={e => setFilters(f => ({ ...f, subtopic: e.target.value }))}>
            <option value="">All subtopics</option>
            {filterOpts.subtopics.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
          </select>

          <label className="viz-filter-label">Tag</label>
          <select className="viz-select" value={filters.tag}
            onChange={e => setFilters(f => ({ ...f, tag: e.target.value }))}>
            <option value="">All tags</option>
            {filterOpts.tags.map(t => <option key={t} value={t}>{t}</option>)}
          </select>

          <label className="viz-filter-label">Status</label>
          <select className="viz-select" value={filters.is_active}
            onChange={e => setFilters(f => ({ ...f, is_active: e.target.value }))}>
            <option value="true">Active only</option>
            <option value="">All</option>
            <option value="false">Inactive only</option>
          </select>
        </div>

        <button className="viz-btn viz-btn--gold" onClick={applyFilters}>Apply Filters</button>
        <button className="viz-btn viz-btn--outline" onClick={resetFilters}>Reset</button>

        {/* Stats */}
        <div className="viz-stat-block">
          <div className="viz-stat-row"><span>Total rules</span><span className="viz-stat-val">{stats.total_rules ?? '—'}</span></div>
          <div className="viz-stat-row"><span>Topics</span><span className="viz-stat-val">{Object.keys(topicStats).length || '—'}</span></div>
          <div className="viz-stat-row"><span>Edges</span><span className="viz-stat-val">{stats.total_edges ?? '—'}</span></div>
        </div>

        {/* Topic pills */}
        {Object.keys(topicStats).length > 0 && (
          <>
            <div className="viz-pills-label">Quick filter</div>
            <div className="viz-pills">
              {Object.entries(topicStats).map(([tid, info]) => (
                <button key={tid} className={`viz-pill ${filters.topic === tid ? 'active' : ''}`}
                  style={{ background: info.color + '28', color: info.color, borderColor: filters.topic === tid ? info.color : 'transparent' }}
                  onClick={() => {
                    const newTopic = filters.topic === tid ? '' : tid;
                    setFilters(f => ({ ...f, topic: newTopic }));
                    const p = {};
                    if (newTopic) p.topic = newTopic;
                    if (filters.subtopic) p.subtopic = filters.subtopic;
                    if (filters.tag) p.tag = filters.tag;
                    if (filters.is_active !== '') p.is_active = filters.is_active;
                    loadData(p);
                  }}>
                  {tid.replace(/_/g, ' ')} ({info.total})
                </button>
              ))}
            </div>
          </>
        )}

        {/* Edge legend */}
        <div className="viz-pills-label" style={{ marginTop: 16 }}>Relationship types</div>
        <div className="viz-legend">
          {Object.entries(EDGE_COLORS).map(([type, color]) => (
            <div className="viz-legend-item" key={type}>
              <span className="viz-legend-dot" style={{ background: color }} />
              <span>{type}</span>
            </div>
          ))}
        </div>
      </aside>

      {/* Main area */}
      <div className="viz-main">
        {/* Top bar */}
        <div className="viz-topbar">
          <span className="viz-topbar-title">Rule Visualizer</span>
          <input
            className="viz-search"
            type="text"
            placeholder="Search rules…"
            value={search}
            onChange={e => handleSearchChange(e.target.value)}
          />
          <div className="view-toggle">
            <button className={`view-btn ${view === 'graph' ? 'active' : ''}`} onClick={() => setView('graph')}>Graph</button>
            <button className={`view-btn ${view === 'list'  ? 'active' : ''}`} onClick={() => setView('list')}>List</button>
          </div>
        </div>

        {/* Canvas / List */}
        <div className="viz-canvas-wrap" ref={wrapRef}>
          {/* Graph */}
          <svg ref={svgRef} className="viz-svg" style={{ display: view === 'graph' ? 'block' : 'none' }} />

          {/* List */}
          {view === 'list' && data && (
            <ListView nodes={data.nodes || []} onSelect={setSelected} />
          )}

          {/* Loading */}
          {loading && (
            <div className="viz-loading">
              <div className="viz-spinner" />
              <span>Loading rules…</span>
            </div>
          )}

          {/* Error */}
          {error && <div className="viz-error">{error}</div>}

          {/* Detail panel */}
          <DetailPanel node={selected} onClose={() => setSelected(null)} />
        </div>
      </div>
    </div>
  );
}
