import { useMemo, useState } from 'react';
import { MOCK_RESULT } from '../data/mockResult';
import './screens.css';

export default function ResultScreen({ onOpenReport, onOpenDiff }) {
  const [view, setView] = useState('summary'); // summary | details | scoring
  const [filter, setFilter] = useState('all');
  const [activeId, setActiveId] = useState(MOCK_RESULT.claims[0].id);
  const [claims, setClaims] = useState(MOCK_RESULT.claims);

  const active = claims.find((c) => c.id === activeId) ?? claims[0];
  const filtered = useMemo(() => {
    if (filter === 'all') return claims;
    return claims.filter((c) => c.type === filter);
  }, [claims, filter]);

  const maxAbs = Math.max(...MOCK_RESULT.pos.steps.map((s) => Math.abs(s.delta)), 0.01);

  const toggleExcluded = (id) => {
    setClaims((list) => list.map((c) => (c.id === id ? { ...c, excluded: !c.excluded } : c)));
  };

  const openClaim = (id) => {
    setActiveId(id);
    setView('details');
  };

  return (
    <section className="screen screen--wide result-screen">
      <div className="result-head">
        <div className="result-head__left">
          <h2 className="screen-title" style={{ marginBottom: 6 }}>
            Result
          </h2>
          <p className="result-query muted">{MOCK_RESULT.query}</p>
        </div>
        <div className="result-head__actions">
          {view !== 'summary' ? (
            <button type="button" className="btn" onClick={() => setView('summary')}>
              ← Collapse
            </button>
          ) : null}
          <button type="button" className="btn" onClick={onOpenDiff}>
            What-if / diff
          </button>
          <button type="button" className="btn btn-primary" onClick={onOpenReport}>
            Memo
          </button>
        </div>
      </div>

      {view === 'summary' ? (
        <div className="summary-layout">
          <div className="panel summary-verdict">
            <h3>Verdict</h3>
            <div className="verdict-badge" data-v={MOCK_RESULT.verdict}>
              {MOCK_RESULT.verdict}
            </div>

            <div className="summary-metrics">
              <div className="summary-metric">
                <span>Confidence</span>
                <strong>{Math.round(MOCK_RESULT.confidence * 100)}%</strong>
              </div>
              <div className="summary-metric">
                <span>PoS</span>
                <strong>{(MOCK_RESULT.pos.final * 100).toFixed(0)}%</strong>
              </div>
              <div className="summary-metric">
                <span>rNPV P50</span>
                <strong>
                  {MOCK_RESULT.rnpv.p50}
                  {MOCK_RESULT.rnpv.unit}
                </strong>
              </div>
              <div className="summary-metric">
                <span>P10 – P90</span>
                <strong>
                  {MOCK_RESULT.rnpv.p10}–{MOCK_RESULT.rnpv.p90}
                </strong>
              </div>
            </div>

            <h3>Conditions</h3>
            <ul className="summary-list">
              {MOCK_RESULT.conditions.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>

            <button type="button" className="btn" onClick={() => setView('scoring')}>
              Open scoring (PoS / kill rules)
            </button>
          </div>

          <div className="panel summary-claims">
            <div className="summary-claims__head">
              <h3>Key claims</h3>
              <button type="button" className="btn btn-primary" onClick={() => setView('details')}>
                Open all evidence
              </button>
            </div>

            <div className="summary-claim-list">
              {claims.map((c) => (
                <div key={c.id} className="summary-claim-row" data-excluded={c.excluded ? '' : undefined}>
                  <div className="summary-claim-row__body">
                    <div className="claim-meta">
                      <span className="claim-type" data-t={c.type}>
                        {c.type}
                      </span>
                      <span className="tag">{c.id}</span>
                      <span className="tag">{c.direction}</span>
                    </div>
                    <p>{c.text}</p>
                  </div>
                  <button type="button" className="btn" onClick={() => openClaim(c.id)}>
                    Open
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {view === 'scoring' ? (
        <div className="panel scoring-panel">
          <h3>PoS waterfall</h3>
          <div className="waterfall">
            {MOCK_RESULT.pos.steps.map((s) => (
              <div key={s.label} className="waterfall-bar">
                <div>
                  <div>{s.label}</div>
                  <div className="waterfall-track">
                    <div
                      className="waterfall-fill"
                      style={{
                        width: `${(Math.abs(s.delta) / maxAbs) * 100}%`,
                        opacity: s.delta < 0 ? 0.45 : 1,
                      }}
                    />
                  </div>
                </div>
                <strong style={{ color: s.delta < 0 ? 'var(--dni)' : 'var(--accent-soft)' }}>
                  {s.delta === 0 ? '0pp' : `${s.delta > 0 ? '+' : ''}${(s.delta * 100).toFixed(0)}pp`}
                </strong>
              </div>
            ))}
          </div>

          <h3 style={{ marginTop: 8 }}>Kill rules</h3>
          {MOCK_RESULT.killRules.map((r) => (
            <div key={r.id} className="metric-row">
              <span>
                {r.id} · {r.label}
              </span>
              <strong style={{ color: r.status === 'armed' ? 'var(--conditional)' : 'var(--accent-soft)' }}>
                {r.status}
              </strong>
            </div>
          ))}

          <h3 style={{ marginTop: 8 }}>What would change the decision</h3>
          <ul className="summary-list">
            {MOCK_RESULT.whatChanges.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {view === 'details' ? (
        <div className="result-grid result-grid--details">
          <div className="panel">
            <h3>Claims</h3>
            <div className="claim-filters">
              {['all', 'source', 'inference', 'unknown'].map((f) => (
                <button
                  key={f}
                  type="button"
                  className="filter-pill"
                  data-active={filter === f ? '' : undefined}
                  onClick={() => setFilter(f)}
                >
                  {f}
                </button>
              ))}
            </div>
            <div className="claim-list">
              {filtered.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  className="claim-card"
                  data-active={c.id === activeId ? '' : undefined}
                  data-excluded={c.excluded ? '' : undefined}
                  onClick={() => setActiveId(c.id)}
                >
                  <div className="claim-meta">
                    <span className="claim-type" data-t={c.type}>
                      {c.type}
                    </span>
                    <span className="tag">{c.id}</span>
                    <span className="tag">{c.direction}</span>
                  </div>
                  <div style={{ fontSize: '0.9rem', lineHeight: 1.4 }}>{c.text}</div>
                </button>
              ))}
            </div>
          </div>

          <aside className="panel">
            <h3>Evidence</h3>
            {active ? (
              <>
                <div className="claim-meta">
                  <span className="claim-type" data-t={active.type}>
                    {active.type}
                  </span>
                  <span className="tag">{active.id}</span>
                </div>
                <p style={{ margin: 0, fontSize: '0.95rem' }}>{active.text}</p>
                {active.quote ? (
                  <blockquote className="evidence-quote">«{active.quote}»</blockquote>
                ) : (
                  <p className="muted" style={{ margin: 0, fontSize: '0.88rem' }}>
                    No direct quote. This is an inference or an unknown.
                  </p>
                )}
                <div className="metric-row">
                  <span>Source</span>
                  <strong>{active.source}</strong>
                </div>
                <div className="metric-row">
                  <span>Date</span>
                  <strong>{active.date || '—'}</strong>
                </div>
                <div className="toggle-row">
                  <span>What-if: exclude claim</span>
                  <button type="button" className="btn" onClick={() => toggleExcluded(active.id)}>
                    {active.excluded ? 'Include' : 'Exclude'}
                  </button>
                </div>
              </>
            ) : null}
          </aside>
        </div>
      ) : null}
    </section>
  );
}
