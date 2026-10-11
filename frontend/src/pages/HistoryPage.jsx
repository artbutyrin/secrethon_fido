import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { deleteAllRuns, deleteRun, listRuns, renameRun } from '../lib/api';
import './HistoryPage.css';

function chatTitle(run) {
  if (run?.title) return run.title;
  const pair = [run?.disease_input, run?.target_input].filter(Boolean).join(' · ');
  return pair || run?.id || 'Memo';
}

function formatWhen(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function HistoryPage() {
  const [runs, setRuns] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState('');
  const [confirm, setConfirm] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const skipRename = useRef(false);
  const renaming = useRef(false);

  const load = async () => {
    setError('');
    try {
      const next = await listRuns(100);
      setRuns(next);
      setSelected((current) => {
        const ids = new Set(next.map((run) => run.id));
        return new Set([...current].filter((id) => ids.has(id)));
      });
    } catch (err) {
      setError(err?.message || 'Could not load history.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const allSelected = runs.length > 0 && selected.size === runs.length;
  const selectedCount = selected.size;
  const confirmCount = useMemo(() => {
    if (confirm === 'all') return runs.length;
    if (confirm === 'selected') return selectedCount;
    return confirm ? 1 : 0;
  }, [confirm, runs.length, selectedCount]);

  const toggle = (id) => {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(runs.map((run) => run.id)));
  };

  const startRename = (run) => {
    setEditingId(run.id);
    setDraft(chatTitle(run));
    setConfirm(null);
  };

  const saveRename = async (run, raw) => {
    if (skipRename.current) {
      skipRename.current = false;
      return;
    }
    if (renaming.current) return;
    const title = String(raw ?? draft).trim();
    const current = run.title || chatTitle(run);
    setEditingId(null);
    if (!title || title === current) return;
    renaming.current = true;
    setBusy(true);
    try {
      await renameRun(run.id, title);
      setRuns((items) => items.map((item) => (item.id === run.id ? { ...item, title } : item)));
    } catch (err) {
      setError(err?.message || 'Could not rename this memo.');
    } finally {
      renaming.current = false;
      setBusy(false);
    }
  };

  const removeIds = async (ids) => {
    setBusy(true);
    setError('');
    try {
      if (confirm === 'all') await deleteAllRuns();
      else await Promise.all(ids.map((id) => deleteRun(id)));
      setConfirm(null);
      setSelected(new Set());
      setEditingId(null);
      await load();
    } catch (err) {
      setError(err?.message || 'Could not delete the selected memos.');
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = () => {
    if (confirm === 'all') removeIds(runs.map((run) => run.id));
    else if (confirm === 'selected') removeIds([...selected]);
    else if (confirm) removeIds([confirm]);
  };

  return (
    <div className="history-page">
      <main className="history-main">
        <div className="history-inner">
          <Link to="/" className="back-link">
            ← Home
          </Link>
          <p className="eyebrow">Saved memos</p>
          <div className="history-head">
            <h1 className="history-title">
              History
            </h1>
            <div className="history-actions">
              <button
                type="button"
                className="history-btn"
                disabled={!selectedCount || busy}
                onClick={() => setConfirm('selected')}
              >
                Delete selected
              </button>
              <button
                type="button"
                className="history-btn history-btn--danger"
                disabled={!runs.length || busy}
                onClick={() => setConfirm('all')}
              >
                Delete all
              </button>
            </div>
          </div>
          <p className="history-lede">
            Every finished analysis is stored on the server. Open a memo, rename it, or remove the ones you no longer need.
          </p>

          {error ? <p className="history-error">{error}</p> : null}

          {confirm ? (
            <div className="history-confirm" role="alertdialog" aria-label="Confirm delete">
              <p>
                Delete {confirmCount} {confirmCount === 1 ? 'memo' : 'memos'}? This cannot be undone.
              </p>
              <div>
                <button type="button" className="history-btn" onClick={() => setConfirm(null)} disabled={busy}>
                  Cancel
                </button>
                <button type="button" className="history-btn history-btn--danger" onClick={confirmDelete} disabled={busy}>
                  {busy ? 'Deleting…' : 'Delete'}
                </button>
              </div>
            </div>
          ) : null}

          {loading ? <p className="history-empty">Loading history…</p> : null}

          {!loading && !runs.length ? (
            <p className="history-empty">
              No memos yet. Start one from <Link to="/#underwrite">Invest</Link>.
            </p>
          ) : null}

          {runs.length ? (
            <div className="history-list">
              <label className="history-selectall">
                <input type="checkbox" checked={allSelected} onChange={toggleAll} />
                <span>Select all</span>
              </label>
              <ul>
                {runs.map((run) => {
                  const title = chatTitle(run);
                  const editing = editingId === run.id;
                  return (
                    <li key={run.id} className="history-row" data-selected={selected.has(run.id) || undefined}>
                      <label className="history-check">
                        <input
                          type="checkbox"
                          checked={selected.has(run.id)}
                          onChange={() => toggle(run.id)}
                          aria-label={`Select ${title}`}
                        />
                      </label>
                      <div className="history-body">
                        {editing ? (
                          <input
                            className="history-rename"
                            value={draft}
                            autoFocus
                            maxLength={160}
                            aria-label="Memo name"
                            onChange={(event) => setDraft(event.target.value)}
                            onBlur={(event) => saveRename(run, event.currentTarget.value)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter') {
                                event.preventDefault();
                                saveRename(run, event.currentTarget.value);
                              }
                              if (event.key === 'Escape') {
                                skipRename.current = true;
                                setEditingId(null);
                              }
                            }}
                          />
                        ) : (
                          <Link className="history-link" to={`/report/${run.id}`}>
                            {title}
                          </Link>
                        )}
                        <p className="history-meta">
                          <span>{formatWhen(run.created_at)}</span>
                          {run.decision ? <span data-v={run.decision}>{run.decision}</span> : null}
                          <span>{run.status}</span>
                        </p>
                      </div>
                      <div className="history-row-actions">
                        <button type="button" className="history-btn" onClick={() => startRename(run)} disabled={busy}>
                          Rename
                        </button>
                        <button
                          type="button"
                          className="history-btn history-btn--danger"
                          onClick={() => setConfirm(run.id)}
                          disabled={busy}
                        >
                          Delete
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
