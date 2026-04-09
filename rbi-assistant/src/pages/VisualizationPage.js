import React, { useState, useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import { getVisualizationData } from '../utils/api';
import './VisualizationPage.css';

const EDGE_COLORS = {
  modifies:   '#EF9F27',
  overrides:  '#E24B4A',
  depends_on: '#7F77DD',
  references: '#6B8AC9',
  clarifies:  '#1D9E75',
  supersedes: '#D85A30',
};

// Proper visible colors for dark background
const NODE_PALETTE = {
  commercial_banks:                 { fill: '#1a4a8a', stroke: '#5ba3f5', glow: '#3d8ef0' },
  NBFC:                             { fill: '#3d3890', stroke: '#9b96f7', glow: '#7b75e8' },
  payment_banks:                    { fill: '#0e5c3f', stroke: '#2ed89a', glow: '#1fba78' },
  small_financial_banks:            { fill: '#365210', stroke: '#8ec623', glow: '#6ea61a' },
  Regional_Rural_Bank:              { fill: '#6a3e08', stroke: '#e8951f', glow: '#c47a14' },
  local_area_banks:                 { fill: '#6a3e08', stroke: '#e8951f', glow: '#c47a14' },
  Urban_Cooperative_Bank:           { fill: '#7a2e10', stroke: '#f07840', glow: '#d45a28' },
  Rural_Cooperative_Bank:           { fill: '#7a2e10', stroke: '#f07840', glow: '#d45a28' },
  All_India_Financial_Institutions: { fill: '#7a2248', stroke: '#f06fa0', glow: '#d4457e' },
  Asset_Reconstruction_Companies:   { fill: '#7a1818', stroke: '#f05858', glow: '#d43535' },
  Credit_Information_Services:      { fill: '#2e3f58', stroke: '#8fa3c4', glow: '#6b7fa0' },
  KYC:                              { fill: '#0e5c3f', stroke: '#2ed89a', glow: '#1fba78' },
  AML:                              { fill: '#7a2e10', stroke: '#f07840', glow: '#d45a28' },
  PMLA:                             { fill: '#7a2e10', stroke: '#f07840', glow: '#d45a28' },
  forex:                            { fill: '#3d3890', stroke: '#9b96f7', glow: '#7b75e8' },
  governance:                       { fill: '#2e3f58', stroke: '#8fa3c4', glow: '#6b7fa0' },
  general:                          { fill: '#253548', stroke: '#6090b8', glow: '#4878a8' },
};
const DEFAULT_PAL = { fill: '#1e3050', stroke: '#5a8fc4', glow: '#4a78b0' };
const getPalette  = t => NODE_PALETTE[t] || DEFAULT_PAL;

/* ── Tooltip ── */
function Tooltip({ node, pos }) {
  if (!node || !pos) return null;
  const pal = getPalette(node.topic || '');
  return (
    <div className="graph-tooltip" style={{ left: pos.x, top: pos.y }}>
      <div className="gt-title">{node.label || node.id}</div>
      {node.type === 'topic' && <>
        <div className="gt-row"><span>Type</span><span>Topic cluster</span></div>
        <div className="gt-row"><span>Rules</span><span style={{ color: pal.stroke, fontWeight: 700 }}>{node.rule_count ?? 0}</span></div>
        <div className="gt-row"><span>Subtopics</span><span>{(node.subtopics || []).length}</span></div>
      </>}
      {node.type === 'rule' && <>
        <div className="gt-row"><span>Topic</span><span style={{ color: pal.stroke }}>{(node.topic || '').replace(/_/g, ' ')}</span></div>
        {node.subtopic && <div className="gt-row"><span>Subtopic</span><span>{node.subtopic.replace(/_/g, ' ')}</span></div>}
        {node.summary && <div className="gt-summary">{node.summary.slice(0, 120)}{node.summary.length > 120 ? '…' : ''}</div>}
      </>}
      <div className="gt-hint">Click for full details →</div>
    </div>
  );
}

/* ── Detail Panel ── */
function DetailPanel({ node, onClose }) {
  if (!node) return null;
  const reqs = node.requirements || [];
  const pal  = getPalette(node.topic || '');
  return (
    <div className="detail-panel fade-in">
      <button className="detail-close" onClick={onClose}>×</button>
      <div className="detail-type-badge" style={{ background: pal.fill + 'cc', color: pal.stroke, borderColor: pal.stroke + '55' }}>
        {node.type === 'topic' ? '🗂 Topic Cluster' : '📋 Rule'}
      </div>
      <div className="detail-title">{node.label || node.id}</div>
      {node.type === 'topic' ? (<>
        <DetailRow label="Topic" value={<span style={{ color: pal.stroke }}>{(node.id || '').replace('topic_', '').replace(/_/g, ' ')}</span>} />
        <DetailRow label="Rule Count" value={<span className="detail-num">{node.rule_count ?? 0}</span>} />
        <DetailRow label="Subtopics"  value={(node.subtopics || []).join(', ') || '—'} />
      </>) : (<>
        <DetailRow label="Rule ID"       value={<span className="mono-val">{node.id}</span>} />
        <DetailRow label="Topic / Sub"   value={<span style={{ color: pal.stroke }}>{(node.topic || '').replace(/_/g, ' ')} / {(node.subtopic || '').replace(/_/g, ' ')}</span>} />
        <DetailRow label="Summary"       value={node.summary || '—'} />
        {reqs.length > 0 && (
          <div className="detail-section">
            <div className="detail-label">Requirements</div>
            {reqs.map((r, i) => (
              <div className="req-block" key={i}>
                <span className="req-type">{r.type}</span>
                <span className="req-val">{r.value != null ? Number(r.value).toLocaleString('en-IN') : '—'}{r.currency ? ` ${r.currency}` : r.type === 'percentage_limit' ? '%' : ''}</span>
                {r.description && <div className="req-desc">{r.description}</div>}
              </div>
            ))}
          </div>
        )}
        <DetailRow label="Circular"      value={<span className="mono-val sm">{node.circular_id || '—'}</span>} />
        {node.effective_date && <DetailRow label="Effective Date" value={node.effective_date} />}
        <div className="detail-section">
          <div className="detail-label">Tags</div>
          <div className="tag-row">{(node.tags || []).map(t => <span className="dtag" key={t}>{t}</span>)}</div>
        </div>
        <DetailRow label="Status" value={<span style={{ color: node.is_active ? '#2ed89a' : '#f05050' }}>{node.is_active ? '● Active' : '● Inactive'}</span>} />
      </>)}
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

/* ── List View ── */
function ListView({ nodes, onSelect }) {
  const rules = nodes.filter(n => n.type === 'rule');
  if (!rules.length) return <div className="list-empty">No rules match the current filters.</div>;
  return (
    <div className="list-view">
      {rules.map(r => {
        const pal = getPalette(r.topic);
        return (
          <div className="rule-card" key={r.id} onClick={() => onSelect(r)}>
            <div className="rc-header">
              <span className="rc-id">{r.id}</span>
              <span className="rc-title">{r.label}</span>
              <span className="rc-topic-badge" style={{ background: pal.fill + 'cc', color: pal.stroke }}>{(r.topic || '').replace(/_/g, ' ')}</span>
            </div>
            <div className="rc-summary">{r.summary || ''}</div>
            <div className="rc-tags">{(r.tags || []).map(t => <span className="rc-tag" key={t}>{t}</span>)}</div>
          </div>
        );
      })}
    </div>
  );
}

/* ── Main ── */
export default function VisualizationPage() {
  const svgRef  = useRef(null);
  const simRef  = useRef(null);
  const wrapRef = useRef(null);

  const [data, setData]               = useState(null);
  const [loading, setLoading]         = useState(false);
  const [error, setError]             = useState('');
  const [view, setView]               = useState('graph');
  const [selected, setSelected]       = useState(null);
  const [tooltip, setTooltip]         = useState({ node: null, pos: null });
  const [search, setSearch]           = useState('');
  const [searchTimer, setSearchTimer] = useState(null);
  const [filters, setFilters]         = useState({ topic: '', subtopic: '', tag: '', is_active: 'true' });
  const [filterOpts, setFilterOpts]   = useState({ topics: [], subtopics: [], tags: [] });

  const loadData = useCallback(async (params = {}) => {
    setLoading(true); setError('');
    try {
      const res = await getVisualizationData({ limit: 300, ...params });
      setData(res.data);
      if (res.data.filters) setFilterOpts(res.data.filters);
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Failed to load');
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const buildParams = useCallback((ovr = {}) => {
    const f = { ...filters, ...ovr };
    const p = {};
    if (f.topic)    p.topic    = f.topic;
    if (f.subtopic) p.subtopic = f.subtopic;
    if (f.tag)      p.tag      = f.tag;
    if (f.is_active !== '') p.is_active = f.is_active;
    if (search.trim()) p.search = search.trim();
    return p;
  }, [filters, search]);

  const applyFilters = () => loadData(buildParams());

  const handleSearch = val => {
    setSearch(val);
    clearTimeout(searchTimer);
    setSearchTimer(setTimeout(() => {
      const p = buildParams(); if (val.trim()) p.search = val.trim(); else delete p.search;
      loadData(p);
    }, 450));
  };

  const resetFilters = () => { setFilters({ topic: '', subtopic: '', tag: '', is_active: 'true' }); setSearch(''); loadData(); };

  /* ── D3 ── */
  useEffect(() => {
    if (!data || view !== 'graph') return;
    const wrap = wrapRef.current;
    if (!wrap) return;
    const W = wrap.clientWidth, H = wrap.clientHeight;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();
    if (simRef.current) simRef.current.stop();

    const topicNodes = (data.nodes || []).filter(n => n.type === 'topic').map(n => ({ ...n }));
    const ruleNodes  = (data.nodes || []).filter(n => n.type === 'rule').map(n => ({ ...n }));
    const allNodes   = [...topicNodes, ...ruleNodes];
    if (!allNodes.length) { svg.append('text').attr('x', W/2).attr('y', H/2).attr('text-anchor','middle').attr('fill','#4a6080').attr('font-size','15px').text('No rules match the current filters.'); return; }

    // Pre-position topics in a circle
    const tR = Math.min(W, H) * 0.27;
    topicNodes.forEach((n, i) => {
      const a = (i / topicNodes.length) * 2 * Math.PI - Math.PI / 2;
      n.x = n.fx_hint = W / 2 + tR * Math.cos(a);
      n.y = n.fy_hint = H / 2 + tR * Math.sin(a);
    });

    const byId    = new Map(allNodes.map(n => [n.id, n]));
    const rawEdges = (data.edges || []).filter(e => {
      const s = e.source?.id || e.source, t = e.target?.id || e.target;
      return byId.has(s) && byId.has(t);
    }).map(e => ({ ...e }));

    const containEdges = rawEdges.filter(e => e.type === 'contains');
    const relEdges     = rawEdges.filter(e => e.type !== 'contains');

    /* ── Defs ── */
    const defs = svg.append('defs');

    // Node glow
    const gf = defs.append('filter').attr('id','nglow').attr('x','-60%').attr('y','-60%').attr('width','220%').attr('height','220%');
    gf.append('feGaussianBlur').attr('stdDeviation','2.5').attr('result','blur');
    const m1 = gf.append('feMerge'); m1.append('feMergeNode').attr('in','blur'); m1.append('feMergeNode').attr('in','SourceGraphic');

    // Topic glow
    const tgf = defs.append('filter').attr('id','tglow').attr('x','-80%').attr('y','-80%').attr('width','260%').attr('height','260%');
    tgf.append('feGaussianBlur').attr('stdDeviation','7').attr('result','blur');
    const m2 = tgf.append('feMerge'); m2.append('feMergeNode').attr('in','blur'); m2.append('feMergeNode').attr('in','SourceGraphic');

    // Radial gradients per topic
    topicNodes.forEach(n => {
      const p = getPalette(n.topic), safe = n.id.replace(/[^a-z0-9]/gi,'_');
      const g = defs.append('radialGradient').attr('id',`rg_${safe}`).attr('cx','35%').attr('cy','30%').attr('r','70%');
      g.append('stop').attr('offset','0%').attr('stop-color',p.stroke).attr('stop-opacity',0.95);
      g.append('stop').attr('offset','60%').attr('stop-color',p.fill).attr('stop-opacity',0.85);
      g.append('stop').attr('offset','100%').attr('stop-color','#060e1f').attr('stop-opacity',0.5);
    });

    // Arrow marker
    defs.append('marker').attr('id','arr').attr('viewBox','0 -4 8 8').attr('refX',16).attr('refY',0)
      .attr('markerWidth',5).attr('markerHeight',5).attr('orient','auto')
      .append('path').attr('d','M0,-4L8,0L0,4').attr('fill','#4a6080').attr('fill-opacity',0.65);

    /* ── Background grid ── */
    const bgG = svg.append('g');
    for (let x = 0; x < W; x += 44) bgG.append('line').attr('x1',x).attr('y1',0).attr('x2',x).attr('y2',H).attr('stroke','#162238').attr('stroke-width',0.5);
    for (let y = 0; y < H; y += 44) bgG.append('line').attr('x1',0).attr('y1',y).attr('x2',W).attr('y2',y).attr('stroke','#162238').attr('stroke-width',0.5);

    /* ── Main group (zoom) ── */
    const g = svg.append('g');
    svg.call(d3.zoom().scaleExtent([0.08,6]).on('zoom', e => { g.attr('transform', e.transform); setTooltip({ node:null, pos:null }); }));
    svg.on('click', () => { setSelected(null); setTooltip({ node:null, pos:null }); });

    /* ── Contain edges (faint dashed) ── */
    const cLines = g.append('g').selectAll('line').data(containEdges).enter().append('line')
      .attr('stroke', d => { const n = byId.get(d.source?.id||d.source); return n ? getPalette(n.topic).stroke : '#2a3f60'; })
      .attr('stroke-width', 0.6).attr('stroke-opacity', 0.12).attr('stroke-dasharray','3 7');

    /* ── Relationship edges ── */
    const rLines = g.append('g').selectAll('line').data(relEdges).enter().append('line')
      .attr('stroke', d => EDGE_COLORS[d.type] || '#4a6080')
      .attr('stroke-width', d => (d.type==='overrides'||d.type==='supersedes') ? 2.4 : 1.6)
      .attr('stroke-opacity', 0.5)
      .attr('stroke-dasharray', d => d.type==='references' ? '5 4' : d.type==='depends_on' ? '8 3' : 'none')
      .attr('marker-end','url(#arr)');

    /* ── Nodes ── */
    const nodeG = g.append('g').selectAll('g').data(allNodes).enter().append('g')
      .style('cursor','pointer')
      .on('click', (ev, d) => { ev.stopPropagation(); setSelected(d); setTooltip({ node:null, pos:null }); })
      .on('mouseover', (ev, d) => {
        const rect = wrap.getBoundingClientRect();
        let x = ev.clientX - rect.left + 18, y = ev.clientY - rect.top + 18;
        if (x + 270 > wrap.clientWidth)  x -= 290;
        if (y + 200 > wrap.clientHeight) y -= 200;
        setTooltip({ node:d, pos:{ x, y } });
        nodeG.style('opacity', n => n.id === d.id ? 1 : rawEdges.some(e => { const s=e.source?.id||e.source,t=e.target?.id||e.target; return (s===d.id&&t===n.id)||(t===d.id&&s===n.id); }) ? 0.9 : 0.2);
        rLines.attr('stroke-opacity', e => { const s=e.source?.id||e.source,t=e.target?.id||e.target; return (s===d.id||t===d.id) ? 0.95 : 0.06; });
      })
      .on('mouseout', () => {
        setTooltip({ node:null, pos:null });
        nodeG.style('opacity', 1);
        rLines.attr('stroke-opacity', 0.5);
      })
      .call(d3.drag()
        .on('start',(e,d)=>{ if(!e.active) simRef.current.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
        .on('drag', (e,d)=>{ d.fx=e.x; d.fy=e.y; })
        .on('end',  (e,d)=>{ if(!e.active) simRef.current.alphaTarget(0); d.fx=null; d.fy=null; })
      );

    /* Topic nodes */
    nodeG.filter(d => d.type==='topic').each(function(d) {
      const ng = d3.select(this);
      const p  = getPalette(d.topic);
      const r  = d.size || 38;
      const gid = `rg_${d.id.replace(/[^a-z0-9]/gi,'_')}`;

      // Outer soft halo
      ng.append('circle').attr('r', r+16).attr('fill', p.glow).attr('fill-opacity', 0.08);
      // Dashed ring
      ng.append('circle').attr('r', r+8).attr('fill','none').attr('stroke', p.stroke).attr('stroke-width', 0.7).attr('stroke-opacity', 0.25).attr('stroke-dasharray','4 6');
      // Main circle
      ng.append('circle').attr('r', r).attr('fill', `url(#${gid})`).attr('stroke', p.stroke).attr('stroke-width', 2.5).attr('filter','url(#tglow)');
      // Inner ring
      ng.append('circle').attr('r', r*0.6).attr('fill','none').attr('stroke', p.stroke).attr('stroke-width', 0.8).attr('stroke-opacity', 0.4);
      // Rule count
      ng.append('text').attr('text-anchor','middle').attr('dy', d.rule_count>99?'-0.15em':'0.1em').attr('fill','#ffffff').attr('font-size', d.rule_count>99?'13px':'17px').attr('font-weight','800').attr('font-family','DM Sans,sans-serif').text(d.rule_count||'');
      ng.append('text').attr('text-anchor','middle').attr('dy','1.25em').attr('fill', p.stroke).attr('font-size','8px').attr('font-weight','600').attr('font-family','DM Sans,sans-serif').attr('letter-spacing','0.5px').text('RULES');
      // Label below
      ng.append('text').attr('text-anchor','middle').attr('dy', r+18).attr('fill', p.stroke).attr('font-size','11px').attr('font-weight','700').attr('font-family','DM Sans,sans-serif').text(d.label);
    });

    /* Rule nodes */
    nodeG.filter(d => d.type==='rule').each(function(d) {
      const ng = d3.select(this);
      const p  = getPalette(d.topic);
      // Halo
      ng.append('circle').attr('r', 11).attr('fill', p.glow).attr('fill-opacity', 0.15);
      // Main
      ng.append('circle').attr('r', 7).attr('fill', p.fill).attr('stroke', p.stroke).attr('stroke-width', 1.8).attr('filter','url(#nglow)');
      // Inner dot
      ng.append('circle').attr('r', 2.5).attr('fill', p.stroke).attr('fill-opacity', 0.95);
    });

    /* ── Simulation ── */
    const sim = d3.forceSimulation(allNodes)
      .force('link',    d3.forceLink(rawEdges).id(d=>d.id).distance(d => d.type==='contains'?65:d.type==='overrides'||d.type==='supersedes'?160:110).strength(d => d.type==='contains'?0.3:0.45))
      .force('charge',  d3.forceManyBody().strength(d => d.type==='topic'?-1400:-60).distanceMax(380))
      .force('center',  d3.forceCenter(W/2, H/2).strength(0.04))
      .force('collide', d3.forceCollide().radius(d => d.type==='topic'?(d.size||38)+22:13).strength(0.75))
      .force('x', d3.forceX(d => d.fx_hint||W/2).strength(d => d.type==='topic'?0.45:0.008))
      .force('y', d3.forceY(d => d.fy_hint||H/2).strength(d => d.type==='topic'?0.45:0.008));

    simRef.current = sim;

    sim.on('tick', () => {
      cLines
        .attr('x1', d => (byId.get(d.source?.id||d.source)||{}).x||0)
        .attr('y1', d => (byId.get(d.source?.id||d.source)||{}).y||0)
        .attr('x2', d => (byId.get(d.target?.id||d.target)||{}).x||0)
        .attr('y2', d => (byId.get(d.target?.id||d.target)||{}).y||0);
      rLines
        .attr('x1', d => d.source?.x??0).attr('y1', d => d.source?.y??0)
        .attr('x2', d => d.target?.x??0).attr('y2', d => d.target?.y??0);
      nodeG.attr('transform', d => `translate(${d.x??0},${d.y??0})`);
    });

    return () => sim.stop();
  }, [data, view]); // eslint-disable-line

  const stats      = data?.stats || {};
  const topicStats = stats.topic_stats || {};

  return (
    <div className="viz-page">
      {/* ── Sidebar ── */}
      <aside className="viz-sidebar">
        <div className="viz-sidebar-header">Filters</div>
        <div className="viz-filter-group">
          {[
            { label:'Topic',   id:'topic',    opts: filterOpts.topics,    fmt: t => t.replace(/_/g,' '), placeholder:'All topics' },
            { label:'Subtopic',id:'subtopic', opts: filterOpts.subtopics, fmt: s => s.replace(/_/g,' '), placeholder:'All subtopics' },
            { label:'Tag',     id:'tag',      opts: filterOpts.tags,      fmt: t => t,                   placeholder:'All tags' },
          ].map(({ label, id, opts, fmt, placeholder }) => (
            <React.Fragment key={id}>
              <label className="viz-filter-label">{label}</label>
              <select className="viz-select" value={filters[id]} onChange={e => setFilters(f => ({ ...f, [id]: e.target.value }))}>
                <option value="">{placeholder}</option>
                {opts.map(o => <option key={o} value={o}>{fmt(o)}</option>)}
              </select>
            </React.Fragment>
          ))}
          <label className="viz-filter-label">Status</label>
          <select className="viz-select" value={filters.is_active} onChange={e => setFilters(f => ({ ...f, is_active: e.target.value }))}>
            <option value="true">Active only</option>
            <option value="">All</option>
            <option value="false">Inactive only</option>
          </select>
        </div>
        <button className="viz-btn viz-btn--gold" onClick={applyFilters}>Apply Filters</button>
        <button className="viz-btn viz-btn--outline" onClick={resetFilters}>Reset</button>

        <div className="viz-stat-block">
          <div className="viz-stat-row"><span>Total rules</span><span className="viz-stat-val">{stats.total_rules ?? '—'}</span></div>
          <div className="viz-stat-row"><span>Topics</span><span className="viz-stat-val">{Object.keys(topicStats).length || '—'}</span></div>
          <div className="viz-stat-row"><span>Edges</span><span className="viz-stat-val">{stats.total_edges ?? '—'}</span></div>
        </div>

        {Object.keys(topicStats).length > 0 && <>
          <div className="viz-pills-label">Quick filter</div>
          <div className="viz-pills">
            {Object.entries(topicStats).map(([tid, info]) => {
              const pal = getPalette(tid), active = filters.topic === tid;
              return (
                <button key={tid} className={`viz-pill ${active?'active':''}`}
                  style={{ background: active ? pal.fill+'ee' : pal.fill+'55', color: pal.stroke, borderColor: active ? pal.stroke : 'transparent' }}
                  onClick={() => { const nT = active?'':tid; setFilters(f=>({...f,topic:nT})); loadData(buildParams({topic:nT})); }}>
                  {tid.replace(/_/g,' ')} ({info.total})
                </button>
              );
            })}
          </div>
        </>}

        <div className="viz-pills-label" style={{ marginTop:16 }}>Relationship types</div>
        <div className="viz-legend">
          {Object.entries(EDGE_COLORS).map(([type, color]) => (
            <div className="viz-legend-item" key={type}>
              <span className="viz-legend-line" style={{ background: color }} />
              <span>{type}</span>
            </div>
          ))}
        </div>

        <div className="viz-tips">
          <div className="viz-tip">🖱 Scroll to zoom · Drag to pan</div>
          <div className="viz-tip">💡 Hover node to highlight connections</div>
          <div className="viz-tip">👆 Click node to open detail panel</div>
        </div>
      </aside>

      {/* ── Main ── */}
      <div className="viz-main">
        <div className="viz-topbar">
          <span className="viz-topbar-title">Rule Visualizer</span>
          <input className="viz-search" type="text" placeholder="Search rules…" value={search} onChange={e => handleSearch(e.target.value)} />
          <div className="view-toggle">
            <button className={`view-btn ${view==='graph'?'active':''}`} onClick={() => setView('graph')}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" style={{marginRight:5,verticalAlign:'middle'}}>
                <circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/>
                <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/><line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
              </svg>Graph
            </button>
            <button className={`view-btn ${view==='list'?'active':''}`} onClick={() => setView('list')}>
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" style={{marginRight:5,verticalAlign:'middle'}}>
                <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/>
                <circle cx="3" cy="6" r="1"/><circle cx="3" cy="12" r="1"/><circle cx="3" cy="18" r="1"/>
              </svg>List
            </button>
          </div>
        </div>

        <div className="viz-canvas-wrap" ref={wrapRef}>
          <svg ref={svgRef} className="viz-svg" style={{ display: view==='graph'?'block':'none' }} />
          {view==='list' && data && <ListView nodes={data.nodes||[]} onSelect={setSelected} />}
          {loading && <div className="viz-loading"><div className="viz-spinner"/><span>Loading rules…</span></div>}
          {error   && <div className="viz-error">{error}</div>}
          {view==='graph' && <Tooltip node={tooltip.node} pos={tooltip.pos} />}
          <DetailPanel node={selected} onClose={() => setSelected(null)} />
        </div>
      </div>
    </div>
  );
}
