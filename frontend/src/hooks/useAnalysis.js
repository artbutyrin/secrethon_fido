import { useCallback, useRef, useState } from 'react';
import { analyzePair, isAbort, loadSavedRun } from '../lib/api';

const EMPTY = {
  phase: 'idle',
  runId: null,
  run: null,
  bundle: null,
  report: null,
  reportPending: false,
  error: '',
  input: null,
};

export function useAnalysis() {
  const abortRef = useRef(null);
  const gen = useRef(0);
  const inputRef = useRef(null);
  const [state, setState] = useState(EMPTY);

  const start = async (input) => {
    gen.current += 1;
    const token = gen.current;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    inputRef.current = input;
    const alive = () => gen.current === token;

    setState({
      ...EMPTY,
      phase: 'queued',
      input,
    });

    const apply = (patch) => {
      if (!alive()) return;
      setState((current) => {
        const next = { ...current, error: '', input };
        for (const key of ['phase', 'runId', 'run', 'bundle', 'report', 'reportPending']) {
          if (patch[key] !== undefined) next[key] = patch[key];
        }
        return next;
      });
    };

    try {
      const out = await analyzePair(input, { signal: ac.signal, onUpdate: apply });
      if (!alive()) return null;
      setState((current) => ({
        ...current,
        phase: out.phase,
        runId: out.runId,
        run: out.run,
        bundle: out.bundle,
        report: out.report,
        reportPending: false,
        error: out.phase === 'error' ? out.run?.message || 'The analysis failed.' : '',
        input,
      }));
      return out;
    } catch (err) {
      if (!alive() || isAbort(err)) return null;
      const message = err?.message || 'The analysis failed.';
      setState((current) => ({
        ...current,
        phase: 'error',
        reportPending: false,
        error: message,
        input,
      }));
      return { phase: 'error', error: message };
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
    }
  };

  const stop = () => {
    gen.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setState((current) => ({
      ...current,
      phase: current.bundle ? 'done' : 'idle',
      reportPending: false,
      error: '',
    }));
  };

  const open = useCallback(async (runId) => {
    gen.current += 1;
    const token = gen.current;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setState({
      ...EMPTY,
      phase: 'running',
      runId,
      run: { id: runId, status: 'running' },
    });
    try {
      const out = await loadSavedRun(runId, { signal: ac.signal });
      if (gen.current !== token) return null;
      inputRef.current = {
        disease: out.run?.disease_input || out.run?.disease?.name || '',
        target: out.run?.target_input || out.run?.target?.symbol || '',
      };
      setState({
        ...EMPTY,
        phase: out.phase,
        runId: out.runId,
        run: out.run,
        bundle: out.bundle,
        report: out.report,
        error: out.phase === 'error' ? out.run?.message || 'The memo could not be opened.' : '',
      });
      return out;
    } catch (err) {
      if (gen.current !== token || isAbort(err)) return null;
      const message = err?.message || 'The memo could not be opened.';
      setState({
        ...EMPTY,
        phase: 'error',
        runId,
        error: message,
      });
      return { phase: 'error', error: message };
    } finally {
      if (abortRef.current === ac) abortRef.current = null;
    }
  }, []);

  const refresh = useCallback(async (runId) => {
    const out = await loadSavedRun(runId, { reportTimeoutMs: 60000 });
    setState((current) => {
      if (current.runId !== runId || current.phase !== 'done') return current;
      return {
        ...current,
        run: out.run || current.run,
        bundle: out.bundle || current.bundle,
        report: out.report || current.report,
        reportPending: !out.report,
        error: '',
      };
    });
    return out;
  }, []);

  const pick = (ids) => {
    const prev = inputRef.current;
    if (!prev) return null;
    return start({
      ...prev,
      diseaseId: ids.diseaseId || null,
      targetId: ids.targetId || null,
    });
  };

  return {
    ...state,
    busy: state.phase === 'queued' || state.phase === 'running',
    start,
    stop,
    pick,
    open,
    refresh,
  };
}
