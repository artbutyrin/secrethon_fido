import { useState } from 'react';
import './screens.css';

export default function DiffScreen() {
  const [pmid, setPmid] = useState('');

  return (
    <section className="screen">
      <h2 className="screen-title">What-if / add evidence</h2>
      <p className="screen-lead">
        Three ways to flip the case: exclude a claim, paste a PMID/NCT/URL, or move in time.
        (`as_of`).
      </p>

      <div className="confirm-block" style={{ marginBottom: 16, maxWidth: 640 }}>
        <h3 style={{ marginTop: 0 }}>Insert evidence</h3>
        <input
          className="btn"
          style={{ width: '100%', marginBottom: 10 }}
          placeholder="PMID / NCT / URL / text"
          value={pmid}
          onChange={(e) => setPmid(e.target.value)}
        />
        <button type="button" className="btn btn-primary">
          Rescore + diff
        </button>
      </div>

      <div className="diff-grid">
        <div className="diff-card">
          <h4>Before</h4>
          <div className="verdict-badge" data-v="Conditional">
            Conditional
          </div>
          <p className="metric-row">
            <span>PoS</span>
            <strong>16%</strong>
          </p>
          <p className="metric-row">
            <span>rNPV P50</span>
            <strong>$420M</strong>
          </p>
          <p className="muted" style={{ fontSize: '0.85rem' }}>
            No CVOT · crowded class
          </p>
        </div>
        <div className="diff-card">
          <h4>After (mock: positive CVOT)</h4>
          <div className="verdict-badge" data-v="Invest">
            Invest
          </div>
          <p className="metric-row">
            <span>PoS</span>
            <strong style={{ color: 'var(--accent-soft)' }}>28% ↑</strong>
          </p>
          <p className="metric-row">
            <span>rNPV P50</span>
            <strong style={{ color: 'var(--accent-soft)' }}>$710M ↑</strong>
          </p>
          <p className="muted" style={{ fontSize: '0.85rem' }}>
            Condition lifted · K5 weakens
          </p>
        </div>
      </div>
    </section>
  );
}
