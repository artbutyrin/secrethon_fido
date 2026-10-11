import { useEffect, useMemo, useState } from 'react';
import LatticeLoader from '../components/LatticeLoader';
import './screens.css';

const STEPS = [
  { id: 'normalize', label: 'Normalize entities' },
  { id: 'fetch', label: 'Fetch open evidence' },
  { id: 'extract', label: 'Extract claims' },
  { id: 'contradict', label: 'Devil’s advocate' },
  { id: 'score', label: 'Score PoS / rNPV' },
  { id: 'report', label: 'Write memo' },
];

export default function ProgressScreen({ query, onDone }) {
  const [tick, setTick] = useState(0);
  const [status, setStatus] = useState('working');

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 900);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (tick < STEPS.length) return undefined;
    setStatus('done');
    const t = setTimeout(() => onDone?.(), 900);
    return () => clearTimeout(t);
  }, [tick, onDone]);

  const counters = useMemo(() => {
    const docs = Math.min(143, 18 + tick * 22);
    const claims = Math.min(61, 4 + tick * 10);
    const contra = Math.min(12, Math.max(0, tick - 2) * 3);
    return { docs, claims, contra };
  }, [tick]);

  return (
    <section className="screen progress-screen">
      <LatticeLoader
        status={status}
        label="Researching"
        doneLabel="Ready in"
        pattern="arrow"
        grid={3}
        shape="round"
        color="#c5cbc7"
        doneColor="#3d8f64"
        glow
        glowColor="#b8f0d0"
        cellSize={7}
        gap={3}
        fontSize={16}
        step={110}
        idleOpacity={0.22}
        showTimer
      />

      <p className="progress-query">{query || 'Lepodisiran · Lp(a) siRNA'}</p>

      <div className="pipeline">
        {STEPS.map((step, i) => {
          const st = i < tick ? 'done' : i === tick ? 'active' : 'pending';
          return (
            <div key={step.id} className="pipeline-row" data-status={st}>
              <span className="pipeline-dot" />
              <span>{step.label}</span>
              <span className="muted">{st === 'done' ? '✓' : st === 'active' ? '…' : ''}</span>
            </div>
          );
        })}
      </div>

      <div className="counters">
        <span>
          documents <strong>{counters.docs}</strong>
        </span>
        <span>
          claims <strong>{counters.claims}</strong>
        </span>
        <span>
          contradictory <strong>{counters.contra}</strong>
        </span>
      </div>
    </section>
  );
}
