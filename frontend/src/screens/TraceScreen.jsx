import { MOCK_RESULT } from '../data/mockResult';
import './screens.css';

export default function TraceScreen() {
  const total = MOCK_RESULT.trace.reduce((s, t) => s + t.cost, 0);

  return (
    <section className="screen">
      <h2 className="screen-title">Run trace</h2>
      <p className="screen-lead">
        For reviewers: tokens, cost, cache hits, latency. This mock totals ${total.toFixed(2)}.
      </p>

      <div className="panel">
        <table className="trace-table">
          <thead>
            <tr>
              <th>Step</th>
              <th>Type</th>
              <th>Latency</th>
              <th>Cost</th>
              <th>Cache</th>
            </tr>
          </thead>
          <tbody>
            {MOCK_RESULT.trace.map((row) => (
              <tr key={`${row.step}-${row.ms}`}>
                <td>{row.step}</td>
                <td>{row.kind}</td>
                <td>{row.ms} ms</td>
                <td>${row.cost.toFixed(2)}</td>
                <td>{row.cache ? 'hit' : 'miss'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
