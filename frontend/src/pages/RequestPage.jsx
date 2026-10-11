import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import SiteFooter from '../components/SiteFooter';
import { useSharedAnalysis } from '../hooks/analysisContext';
import { DISEASES, MECHANISMS, toSearchTerm } from '../data/suggestions';
import './RequestPage.css';

const INITIAL = {
  indication: '',
  mechanism: '',
  modality: '',
  stage: '',
  preclinical: '',
  biomarkers: '',
  route: '',
};

export default function RequestPage() {
  const navigate = useNavigate();
  const analysis = useSharedAnalysis();
  const [form, setForm] = useState(INITIAL);
  const [openMore, setOpenMore] = useState(false);
  const [error, setError] = useState('');

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const onSubmit = (e) => {
    e.preventDefault();
    if (!form.indication.trim() || !form.mechanism.trim()) {
      setError('Indication and Mechanism / Target are required.');
      return;
    }
    setError('');
    const disease = toSearchTerm(form.indication.trim(), DISEASES);
    const target = toSearchTerm(form.mechanism.trim(), MECHANISMS);
    analysis.start({
      disease,
      target,
      phase: form.stage,
      route: form.route,
    });
    navigate('/report', {
      state: { focus: 'full', mode: 'invest', query: `${disease} · ${target}` },
    });
  };

  return (
    <div className="request-page">
      <main className="request-main">
        <div className="request-inner">
          <Link to="/" className="back-link">
            ← Back to home
          </Link>
          <p className="eyebrow">Investment committee · Request</p>
          <h1 className="request-title">
            Request <em>underwriting</em>
          </h1>
          <p className="request-lede">
            Provide indication and mechanism. Optional context sharpens translation and commercial
            scoring.
          </p>

          <form className="request-form" onSubmit={onSubmit} noValidate>
              <label className="field">
                <span>
                  Indication <abbr title="required">*</abbr>
                </span>
                <input
                  required
                  value={form.indication}
                  onChange={set('indication')}
                  placeholder="e.g. Cardiovascular risk / elevated Lp(a)"
                  autoComplete="off"
                />
              </label>

              <label className="field">
                <span>
                  Mechanism / Target <abbr title="required">*</abbr>
                </span>
                <input
                  required
                  value={form.mechanism}
                  onChange={set('mechanism')}
                  placeholder="e.g. siRNA against LPA (Lp(a))"
                  autoComplete="off"
                />
              </label>

              <button
                type="button"
                className="more-toggle"
                aria-expanded={openMore}
                onClick={() => setOpenMore((v) => !v)}
              >
                {openMore ? 'Hide context −' : 'More context +'}
              </button>

              {openMore ? (
                <div className="more-fields">
                  <label className="field">
                    <span>Modality</span>
                    <input value={form.modality} onChange={set('modality')} placeholder="siRNA, mAb, small molecule…" />
                  </label>
                  <label className="field">
                    <span>Development stage</span>
                    <input value={form.stage} onChange={set('stage')} placeholder="Preclinical, Ph1, Ph2…" />
                  </label>
                  <label className="field">
                    <span>Preclinical results</span>
                    <textarea
                      rows={3}
                      value={form.preclinical}
                      onChange={set('preclinical')}
                      placeholder="Key efficacy / tox signals"
                    />
                  </label>
                  <label className="field">
                    <span>Biomarkers</span>
                    <input value={form.biomarkers} onChange={set('biomarkers')} placeholder="PD / response markers" />
                  </label>
                  <label className="field">
                    <span>Route of administration</span>
                    <input value={form.route} onChange={set('route')} placeholder="IV, SC, oral…" />
                  </label>
                </div>
              ) : null}

              {error ? (
                <p className="form-error" role="alert">
                  {error}
                </p>
              ) : null}

              <button type="submit" className="btn-teal">
                Run underwriting →
              </button>
            </form>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
