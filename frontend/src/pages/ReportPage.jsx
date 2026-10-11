import { useEffect } from 'react';
import { Link, Navigate, useLocation, useParams } from 'react-router-dom';
import AnalysisPanel from '../components/AnalysisPanel';
import ReportStage from '../components/ReportStage';
import { useSharedAnalysis } from '../hooks/analysisContext';
import './ReportPage.css';

export default function ReportPage() {
  const { runId } = useParams();
  const { state } = useLocation();
  const analysis = useSharedAnalysis();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, []);

  useEffect(() => {
    if (!runId) return undefined;
    if (analysis.runId === runId && analysis.phase !== 'idle') return undefined;
    analysis.open(runId);
    return undefined;
  }, [runId, analysis.runId, analysis.phase, analysis.open]);

  if (!runId && analysis.phase === 'idle' && !analysis.error) {
    return <Navigate to="/#underwrite" replace />;
  }

  const ready = analysis.phase === 'done';

  return (
    <div className={`report-page${ready ? ' report-page--stage' : ''}`}>
      <main className="report-main">
        <div className="report-inner">
          <div className="report-toolbar">
            <Link to={runId ? '/history' : '/#underwrite'} className="back-link">
              {runId ? '← History' : '← New request'}
            </Link>
            {analysis.busy ? (
              <button type="button" className="report-stop" onClick={analysis.stop}>
                Stop
              </button>
            ) : null}
          </div>
          {ready ? (
            <ReportStage
              run={analysis.run}
              bundle={analysis.bundle}
              report={analysis.report}
              reportPending={analysis.reportPending}
              onRefresh={analysis.refresh}
            />
          ) : (
            <>
              <p className="eyebrow">Investment committee</p>
              <h1 className="report-title">
                Investment <em>memo</em>
              </h1>
              {state?.query ? <p className="report-query">{state.query}</p> : null}
              <AnalysisPanel
                phase={analysis.phase}
                run={analysis.run}
                bundle={analysis.bundle}
                report={analysis.report}
                reportPending={analysis.reportPending}
                error={analysis.error}
                focus={state?.focus || 'full'}
                mode={state?.mode || 'invest'}
                onPick={analysis.pick}
              />
            </>
          )}
        </div>
      </main>
    </div>
  );
}
