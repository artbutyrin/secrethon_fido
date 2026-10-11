import './screens.css';

const BENCH = [
  { key: 'PoS base · cardio', value: '12%', src: 'BIO clinical success rates (check)' },
  { key: 'Genetic uplift (MR)', value: '+6–10 pp', src: 'Open Targets genetic evidence tiers' },
  { key: 'No pivotal data', value: '−4–8 pp', src: 'internal kill/rebuttal rules' },
  { key: 'rNPV discount', value: '10–12%', src: 'industry comps' },
  { key: 'Cost / patient Ph3 CV', value: '$40–80k', src: 'benchmarks.yaml' },
];

export default function MethodologyScreen() {
  return (
    <section className="screen">
      <h2 className="screen-title">Methodology</h2>
      <p className="screen-lead">
        Every number comes from `benchmarks.yaml` and is visible to reviewers. The LLM reads and writes; code computes the verdict.
      </p>
      <div className="bench-list">
        {BENCH.map((b) => (
          <div key={b.key} className="bench-item">
            <div>
              <strong>{b.key}</strong>
              <div className="muted" style={{ fontSize: '0.82rem', marginTop: 4 }}>
                {b.src}
              </div>
            </div>
            <span className="tag tag--forest">{b.value}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
