import { useMemo, useState } from 'react';
import { downloadReportMarkdown, memoFilename } from '../lib/api';
import LatticeLoader from './LatticeLoader';
import './AnalysisPanel.css';

const EMPTY_CLAIMS = [];

const STATUS = {
  queued: 'Queued. The analysis has not started yet.',
  running: 'Collecting evidence and scoring the verdict.',
  ambiguous: 'Several Open Targets matches. Pick the exact entity.',
  not_found: 'Open Targets did not find this disease or target.',
  error: 'The analysis stopped with an error.',
};

const DISEASE_IDS = [
  'scientific_thesis',
  'human_translation_thesis',
  'clinical_development_plan',
  'competitive_landscape',
];

const INVEST_IDS = [
  'recommendation',
  'commercial_opportunity',
  'capital_to_next_milestone',
  'key_risks',
  'critical_unknowns',
  'diligence_questions',
];

const FOCUS_IDS = {
  science: ['scientific_thesis', 'human_translation_thesis', 'critical_unknowns'],
  clinical: ['clinical_development_plan', 'human_translation_thesis', 'key_risks'],
  commercial: [
    'competitive_landscape',
    'commercial_opportunity',
    'capital_to_next_milestone',
    'recommendation',
  ],
};

function fmtM(value) {
  if (value == null || Number.isNaN(Number(value))) return null;
  const n = Number(value);
  const sign = n < 0 ? '−' : '';
  return `${sign}$${Math.abs(n).toFixed(0)}M`;
}

function needsPick(entity) {
  return Boolean(entity && entity.status !== 'resolved' && entity.candidates?.length);
}

function visibleIds(ids, focus) {
  const allow = FOCUS_IDS[focus];
  if (!allow) return ids;
  return ids.filter((id) => allow.includes(id));
}

function sourceLine(source) {
  if (!source || typeof source !== 'object') return String(source ?? '');
  const label = [source.kind, source.id].filter(Boolean).join(' · ');
  return { label: label || 'source', url: source.url || '' };
}

export default function AnalysisPanel({
  phase = 'idle',
  run = null,
  bundle = null,
  report = null,
  reportPending = false,
  error = '',
  focus = 'full',
  mode = 'disease',
  onPick,
}) {
  const [diseaseId, setDiseaseId] = useState('');
  const [targetId, setTargetId] = useState('');
  const [activeId, setActiveId] = useState(null);
  const [selectionKey, setSelectionKey] = useState('');
  const [memoState, setMemoState] = useState('idle');

  const runKey = run?.id || '';
  const resolvedDiseaseId = run?.disease?.status === 'resolved' ? run.disease.id : '';
  const resolvedTargetId = run?.target?.status === 'resolved' ? run.target.id : '';
  const nextSelectionKey = `${runKey}|${resolvedDiseaseId}|${resolvedTargetId}`;
  if (selectionKey !== nextSelectionKey) {
    setSelectionKey(nextSelectionKey);
    setDiseaseId(resolvedDiseaseId);
    setTargetId(resolvedTargetId);
    setActiveId(null);
  }

  const saveMemo = async () => {
    if (!run?.id) return;
    setMemoState('saving');
    try {
      await downloadReportMarkdown(run.id, { filename: memoFilename(run) });
      setMemoState('saved');
    } catch {
      setMemoState('error');
    }
  };

  const claims = bundle?.claims ?? EMPTY_CLAIMS;
  const claimById = useMemo(() => {
    const map = new Map();
    for (const claim of claims) map.set(claim.id, claim);
    return map;
  }, [claims]);

  const sections = useMemo(() => {
    const map = new Map();
    for (const section of report?.sections || []) map.set(section.id, section);
    return map;
  }, [report]);

  if (phase === 'idle' && !error) {
    return (
      <div className="analysis analysis--idle">
        <p className="analysis-kicker">§ 02 / Analysis</p>
        <h2 className="analysis-idle-title">The analysis will appear here</h2>
        <p className="analysis-idle-copy">
          Send a disease · target pair. This section shows the disease biology and whether to invest.
        </p>
      </div>
    );
  }

  if (phase === 'queued' || phase === 'running') {
    return (
      <div className="analysis" role="status" aria-live="polite">
        <p className="analysis-kicker">§ 02 / Analysis</p>
        <LatticeLoader
          className="analysis-loader"
          status="working"
          label={phase === 'queued' ? 'Queued' : 'Thinking'}
          doneLabel="Done in"
          errorLabel="Failed after"
          pattern="orbit"
          grid={3}
          shape="square"
          doneColor="#22c55e"
          errorColor="#ef4444"
          cellSize={6}
          gap={2}
          fontSize={14}
          step={90}
          idleOpacity={0.15}
          glow={false}
          showTimer
          color="currentColor"
        />
        <p className="analysis-idle-copy">{STATUS[phase]}</p>
      </div>
    );
  }

  if (phase === 'error' || (phase === 'not_found' && !needsPick(run?.disease) && !needsPick(run?.target))) {
    return (
      <div className="analysis" role="alert">
        <p className="analysis-kicker">§ 02 / Analysis</p>
        <h2 className="analysis-idle-title">{phase === 'not_found' ? 'Not found' : 'Error'}</h2>
        <p className="analysis-idle-copy">{error || run?.message || STATUS[phase] || STATUS.error}</p>
        <EntityNotes run={run} />
      </div>
    );
  }

  if (phase === 'ambiguous' || phase === 'not_found') {
    return (
      <Picker
        run={run}
        diseaseId={diseaseId}
        targetId={targetId}
        setDiseaseId={setDiseaseId}
        setTargetId={setTargetId}
        onPick={onPick}
      />
    );
  }

  const payload = bundle?.result?.result || {};
  const verdict = payload.verdict || run?.verdict || {};
  const decision = verdict.decision || run?.verdict?.decision || '';
  const score = payload.score || {};
  const coverage = score.coverage || run?.verdict?.coverage;
  const scorecard = payload.scorecard || run?.verdict?.scorecard || [];
  const changes = Array.isArray(payload.what_would_change) ? payload.what_would_change.slice(0, 6) : [];
  const pending = bundle?.result?.pending || run?.verdict?.pending || [];
  const econWrap = bundle?.economics;
  const econ = econWrap?.economics || payload.economics;
  const econNote = econWrap?.economics_note || payload.economics_note;
  const active = activeId ? claimById.get(activeId) : null;
  const diseaseSections = visibleIds(DISEASE_IDS, focus)
    .map((id) => sections.get(id))
    .filter(Boolean);
  const investSections = visibleIds(INVEST_IDS, focus)
    .map((id) => sections.get(id))
    .filter(Boolean);
  const sources = focus === 'full' ? sections.get('sources') : null;

  return (
    <div className="analysis">
      <div className="analysis-head">
        <p className="analysis-kicker">§ 02 / Analysis</p>
        <button
          type="button"
          className="analysis-download"
          onClick={saveMemo}
          disabled={memoState === 'saving' || !run?.id || !report?.sections?.length}
        >
          {memoState === 'saving' ? 'Saving .md…' : memoState === 'saved' ? 'Download .md again' : 'Download .md'}
        </button>
      </div>
      <p className="analysis-query">
        {[run?.disease?.name || run?.disease_input, run?.target?.symbol || run?.target_input]
          .filter(Boolean)
          .join(' · ')}
      </p>

      <div className="analysis-grid" data-mode={mode === 'invest' ? 'invest' : 'disease'}>
        <section className="analysis-card analysis-disease" aria-label="Disease analysis">
          <h2>Disease analysis</h2>
          <DiseaseCard run={run} />
          {diseaseSections.length ? (
            diseaseSections.map((section) => (
              <SectionBlock key={section.id} section={section} onClaim={setActiveId} />
            ))
          ) : (
            <ClaimsFallback claims={claims} onClaim={setActiveId} pending={reportPending} />
          )}
        </section>

        <section className="analysis-card analysis-invest" aria-label="Investment verdict">
          <h2>Should you invest</h2>
          <div className="analysis-verdict" data-v={decision || 'unknown'}>
            <span className="analysis-kicker">Verdict</span>
            <strong>{decision || 'Pending'}</strong>
            {verdict.grounds_text || verdict.reason ? (
              <p>{verdict.grounds_text || verdict.reason}</p>
            ) : null}
          </div>

          <div className="analysis-metrics">
            <Metric label="Pluses" value={score.pos ?? run?.verdict?.pluses} />
            <Metric label="Minuses" value={score.neg ?? run?.verdict?.minuses} />
            <Metric
              label="Coverage"
              value={
                coverage
                  ? `${coverage.items_known ?? 0}/${coverage.items_total ?? 0}`
                  : null
              }
            />
            <Metric label="rNPV P50" value={fmtM(econ?.monte_carlo?.p50_m)} />
          </div>

          {econ?.monte_carlo ? (
            <p className="analysis-range">
              P10–P90 {fmtM(econ.monte_carlo.p10_m)} – {fmtM(econ.monte_carlo.p90_m)}
              {econ.base?.rnpv_m != null ? ` · base ${fmtM(econ.base.rnpv_m)}` : ''}
            </p>
          ) : (
            <p className="analysis-note">
              {econNote || 'Economics were not run: no sourced patient count or price.'}
            </p>
          )}

          {Array.isArray(verdict.conditions) && verdict.conditions.length ? (
            <>
              <h3>Conditions</h3>
              <ul className="analysis-list">
                {verdict.conditions.map((item) => (
                  <li key={String(item)}>{typeof item === 'string' ? item : item.text || item.question}</li>
                ))}
              </ul>
            </>
          ) : null}

          {scorecard.length ? (
            <>
              <h3>Scorecard</h3>
              <ul className="analysis-scorecard">
                {scorecard.map((item) => (
                  <li key={item.id} data-color={item.color || 'U'}>
                    <span className="analysis-swatch" aria-hidden="true" />
                    <span>{item.name}</span>
                    <span className="analysis-color">{item.color || 'U'}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {changes.length ? (
            <>
              <h3>What would change the decision</h3>
              <ul className="analysis-list">
                {changes.map((item) => (
                  <li key={`${item.fact}-${item.to}`}>
                    {item.fact}: {String(item.from)} → {String(item.to)} ({item.verdict_to})
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {pending.length ? (
            <p className="analysis-note">
              {pending.length} model claims are waiting for a human confirmation and do not change the verdict yet.
            </p>
          ) : null}

          {reportPending ? <p className="analysis-note">The memo is still being written.</p> : null}
          {memoState === 'saved' ? <p className="analysis-note">Saved {memoFilename(run)}.</p> : null}
          {memoState === 'error' ? <p className="analysis-note">Could not save the Markdown file yet.</p> : null}

          {investSections.map((section) => (
            <SectionBlock key={section.id} section={section} onClaim={setActiveId} />
          ))}
        </section>
      </div>

      {sources ? <SectionBlock section={sources} onClaim={setActiveId} /> : null}

      {active ? <ClaimCard claim={active} onClose={() => setActiveId(null)} /> : null}

      {run?.message ? (
        <details className="analysis-details">
          <summary>Source notes</summary>
          <p>{run.message}</p>
        </details>
      ) : null}
    </div>
  );
}

function DiseaseCard({ run }) {
  const disease = run?.disease;
  const target = run?.target;
  const areas = (disease?.therapeutic_areas || []).map((area) => area.name).filter(Boolean);
  return (
    <div className="analysis-identity">
      <p className="analysis-name">{disease?.name || run?.disease_input || 'Disease'}</p>
      {disease?.description ? <p className="analysis-desc">{disease.description}</p> : null}
      {areas.length ? <p className="analysis-meta">Therapeutic areas: {areas.join(', ')}</p> : null}
      <p className="analysis-meta">
        Target: {target?.symbol || run?.target_input || '—'}
        {target?.name ? ` · ${target.name}` : ''}
        {target?.action ? ` · ${target.action}` : ''}
      </p>
    </div>
  );
}

function EntityNotes({ run }) {
  const notes = [run?.disease?.message, run?.target?.message].filter(Boolean);
  if (!notes.length) return null;
  return (
    <ul className="analysis-list">
      {notes.map((note) => (
        <li key={note}>{note}</li>
      ))}
    </ul>
  );
}

function Picker({ run, diseaseId, targetId, setDiseaseId, setTargetId, onPick }) {
  const diseaseOpen = needsPick(run?.disease);
  const targetOpen = needsPick(run?.target);
  const ready = (!diseaseOpen || diseaseId) && (!targetOpen || targetId);

  const confirm = () => {
    if (!ready || !onPick) return;
    onPick({
      diseaseId: diseaseId || (run?.disease?.status === 'resolved' ? run.disease.id : null),
      targetId: targetId || (run?.target?.status === 'resolved' ? run.target.id : null),
    });
  };

  return (
    <div className="analysis">
      <p className="analysis-kicker">§ 02 / Confirm</p>
      <h2 className="analysis-idle-title">Confirm the entity</h2>
      <p className="analysis-idle-copy">{run?.message || STATUS.ambiguous}</p>
      <div className="analysis-pick-grid">
        {diseaseOpen ? (
          <CandidateColumn
            title="Disease"
            candidates={run.disease.candidates}
            selected={diseaseId}
            onSelect={setDiseaseId}
          />
        ) : null}
        {targetOpen ? (
          <CandidateColumn
            title="Target"
            candidates={run.target.candidates}
            selected={targetId}
            onSelect={setTargetId}
          />
        ) : null}
      </div>
      <EntityNotes run={run} />
      <button type="button" className="analysis-confirm" disabled={!ready || !onPick} onClick={confirm}>
        Continue analysis
      </button>
    </div>
  );
}

function CandidateColumn({ title, candidates, selected, onSelect }) {
  return (
    <div>
      <h3>{title}</h3>
      <ul className="analysis-candidates">
        {candidates.map((candidate) => (
          <li key={candidate.id}>
            <button
              type="button"
              className="analysis-candidate"
              aria-pressed={selected === candidate.id}
              onClick={() => onSelect(candidate.id)}
            >
              <strong>{candidate.name || candidate.id}</strong>
              <span>
                {candidate.id}
                {candidate.score != null ? ` · ${Number(candidate.score).toFixed(2)}` : ''}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SectionBlock({ section, onClaim }) {
  if (!section?.paragraphs?.length) return null;
  return (
    <div className="analysis-block">
      <h3>{section.title}</h3>
      {section.paragraphs.map((paragraph, index) => (
        <p key={`${section.id}-${index}`} className="analysis-p" data-kind={paragraph.kind}>
          {paragraph.kind === 'inference' ? <span className="analysis-kind">Model inference</span> : null}
          <span>{paragraph.text}</span>
          {paragraph.claim_ids?.length ? (
            <span className="analysis-cites">
              {paragraph.claim_ids.map((id) => (
                <button key={id} type="button" className="analysis-cite" onClick={() => onClaim(id)}>
                  {id}
                </button>
              ))}
            </span>
          ) : null}
        </p>
      ))}
    </div>
  );
}

function ClaimsFallback({ claims, onClaim, pending }) {
  const rows = claims.slice(0, 8);
  if (!rows.length) {
    return <p className="analysis-note">{pending ? 'The memo is still being written.' : 'No claims yet.'}</p>;
  }
  return (
    <div className="analysis-block">
      <h3>Claims</h3>
      <ul className="analysis-list">
        {rows.map((claim) => (
          <li key={claim.id}>
            <button type="button" className="analysis-cite" onClick={() => onClaim(claim.id)}>
              {claim.id}
            </button>{' '}
            {claim.statement}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ClaimCard({ claim, onClose }) {
  const sources = Array.isArray(claim.sources) ? claim.sources.map(sourceLine) : [];
  return (
    <aside className="analysis-claim" aria-label="Claim">
      <div className="analysis-claim-head">
        <span className="analysis-kicker">{claim.status || 'claim'}</span>
        <button type="button" className="analysis-close" onClick={onClose}>
          Close
        </button>
      </div>
      <p className="analysis-claim-id">{claim.id}</p>
      <p>{claim.statement}</p>
      <dl className="analysis-dl">
        <div>
          <dt>Fact</dt>
          <dd>{claim.fact}</dd>
        </div>
        <div>
          <dt>Value</dt>
          <dd>{String(claim.value)}</dd>
        </div>
        <div>
          <dt>Origin</dt>
          <dd>{claim.origin || '—'}</dd>
        </div>
        <div>
          <dt>Status</dt>
          <dd>{claim.status || '—'}</dd>
        </div>
      </dl>
      {claim.quote ? <blockquote>{claim.quote}</blockquote> : <p className="analysis-note">No direct quote.</p>}
      {sources.length ? (
        <ul className="analysis-list">
          {sources.map((source) => (
            <li key={`${source.label}-${source.url}`}>
              {source.url ? (
                <a href={source.url} target="_blank" rel="noreferrer">
                  {source.label}
                </a>
              ) : (
                source.label
              )}
            </li>
          ))}
        </ul>
      ) : null}
    </aside>
  );
}

function Metric({ label, value }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value == null || value === '' ? '—' : value}</strong>
    </div>
  );
}
