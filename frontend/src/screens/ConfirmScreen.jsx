import { useState } from 'react';
import { CONFIRM_ENTITIES } from '../data/mockResult';
import './screens.css';

export default function ConfirmScreen({ onConfirm, onBack }) {
  const [diseaseId, setDiseaseId] = useState(CONFIRM_ENTITIES.disease.resolved.id);
  const [targets, setTargets] = useState(CONFIRM_ENTITIES.targets);

  const toggleTarget = (id) => {
    setTargets((list) => list.map((t) => (t.id === id ? { ...t, on: !t.on } : t)));
  };

  return (
    <section className="screen">
      <h2 className="screen-title">Confirm entities</h2>

      <div className="confirm-grid">
        <div className="confirm-block">
          <h3>Indication</h3>
          <button
            type="button"
            className="candidate"
            data-on={diseaseId === CONFIRM_ENTITIES.disease.resolved.id ? '' : undefined}
            onClick={() => setDiseaseId(CONFIRM_ENTITIES.disease.resolved.id)}
          >
            <span className="tag tag--forest">best</span>
            <span>
              <strong>{CONFIRM_ENTITIES.disease.resolved.name}</strong>
              <br />
              <span className="muted">
                {CONFIRM_ENTITIES.disease.resolved.id} · score{' '}
                {CONFIRM_ENTITIES.disease.resolved.score}
              </span>
            </span>
          </button>
          {CONFIRM_ENTITIES.disease.candidates.map((c) => (
            <button
              key={c.id}
              type="button"
              className="candidate"
              data-on={diseaseId === c.id ? '' : undefined}
              onClick={() => setDiseaseId(c.id)}
            >
              <span className="tag">alt</span>
              <span>
                <strong>{c.name}</strong>
                <br />
                <span className="muted">
                  {c.id} · score {c.score}
                </span>
              </span>
            </button>
          ))}
        </div>

        <div className="confirm-block">
          <h3>Targets / roles</h3>
          <div className="role-chips">
            {targets.map((t) => (
              <button
                key={t.id}
                type="button"
                className="role-chip"
                data-on={t.on ? '' : undefined}
                onClick={() => toggleTarget(t.id)}
              >
                {t.name} · {t.role}
              </button>
            ))}
          </div>
          <p className="muted" style={{ marginTop: 12, fontSize: '0.85rem' }}>
            Click to turn a target off (for example, delivery TfR1 is not the primary target).
          </p>
        </div>

        <div className="confirm-block">
          <h3>Drug</h3>
          <p style={{ margin: 0 }}>
            <strong>{CONFIRM_ENTITIES.drug.name}</strong>
          </p>
          <p className="muted" style={{ margin: '8px 0 0', fontSize: '0.88rem' }}>
            aliases: {CONFIRM_ENTITIES.drug.aliases.join(', ')}
            <br />
            sponsor: {CONFIRM_ENTITIES.drug.sponsor}
          </p>
        </div>
      </div>

      <div className="confirm-actions">
        <button type="button" className="btn btn-ghost" onClick={onBack}>
          Back
        </button>
        <button type="button" className="btn btn-primary" onClick={onConfirm}>
          Run analysis
        </button>
      </div>
    </section>
  );
}
