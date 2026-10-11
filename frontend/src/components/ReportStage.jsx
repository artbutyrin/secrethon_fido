import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import LatticeLoader from './LatticeLoader';
import PromptBar from './PromptBar';
import { downloadReportMarkdown, memoFilename, proposeEdit, submitEvidence } from '../lib/api';

const SECTION_ORDER = [
  'recommendation',
  'scientific_thesis',
  'human_translation_thesis',
  'clinical_development_plan',
  'competitive_landscape',
  'commercial_opportunity',
  'capital_to_next_milestone',
  'key_risks',
  'critical_unknowns',
  'diligence_questions',
  'sources',
];

const URL_RE = /https?:\/\/[^\s)]+/i;

function showValue(value) {
  if (value == null) return 'unknown';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value);
}

function factKey(item) {
  return `${item.fact}|${showValue(item.to)}|${item.verdict_to || ''}`;
}

function evidenceFromText(text, fallbackStatement) {
  const trimmed = text.trim();
  const match = trimmed.match(URL_RE);
  if (match) {
    const sourceUrl = match[0].replace(/[.,;]+$/, '');
    const statement = trimmed.replace(match[0], ' ').replace(/\s+/g, ' ').trim() || fallbackStatement;
    return { statement, source_url: sourceUrl };
  }
  return { statement: trimmed || fallbackStatement, source_text: trimmed };
}

function sourceLabel(source) {
  return source.name || source.url || source.text || source.id || 'Source';
}

function orderSections(sections) {
  const rank = new Map(SECTION_ORDER.map((id, index) => [id, index]));
  return [...sections].sort((a, b) => (rank.get(a.id) ?? 99) - (rank.get(b.id) ?? 99));
}

function leadOf(text) {
  const raw = String(text || '').replace(/\s+/g, ' ').trim();
  const clean = raw.replace(/\b(e\.g|i\.e|vs)\./gi, '$1\u0001');
  const restore = (value) => value.replace(/\u0001/g, '.');
  const first = clean.match(/^(.{12,220}?[.!?])(?:\s+|$)/);
  if (!first) {
    if (clean.length <= 220) return { lead: restore(clean), rest: '' };
    return { lead: `${restore(clean.slice(0, 217)).trim()}…`, rest: restore(clean.slice(217)).trim() };
  }
  let lead = first[1];
  let rest = clean.slice(first[0].length).trim();
  if (lead.length < 48 && rest) {
    const second = rest.match(/^(.{12,160}?[.!?])(?:\s+|$)/);
    if (second) {
      lead = `${lead} ${second[1]}`;
      rest = rest.slice(second[0].length).trim();
    }
  }
  return { lead: restore(lead), rest: restore(rest) };
}

function compactParagraphs(section) {
  const paragraphs = section.paragraphs || [];
  if (section.id === 'diligence_questions') return paragraphs.slice(0, 8);
  if (section.id === 'sources') return [];
  const sourced = paragraphs.filter((paragraph) => paragraph.claim_ids?.length);
  const pool = sourced.length ? sourced : paragraphs;
  const picked = [];
  const seen = new Set();
  for (const paragraph of pool) {
    const novel = (paragraph.claim_ids || []).some((id) => !seen.has(id));
    if (!picked.length || novel) {
      picked.push(paragraph);
      for (const id of paragraph.claim_ids || []) seen.add(id);
    }
    if (picked.length >= 2) break;
  }
  return picked;
}

function passageText(section) {
  return compactParagraphs(section)
    .map((paragraph) => String(paragraph.text || '').trim())
    .filter(Boolean)
    .join('\n\n');
}

function cloneSections(sections) {
  return JSON.parse(JSON.stringify(sections));
}

function replaceParagraphAt(sections, sectionId, index, text) {
  return sections.map((section) => {
    if (section.id !== sectionId) return section;
    return {
      ...section,
      paragraphs: (section.paragraphs || []).map((paragraph, i) => (
        i === index ? { ...paragraph, text } : paragraph
      )),
    };
  });
}

function replacePassage(sections, sectionId, before, after) {
  let done = false;
  return sections.map((section) => {
    if (done || section.id !== sectionId) return section;
    return {
      ...section,
      paragraphs: (section.paragraphs || []).map((paragraph) => {
        if (done || !String(paragraph.text || '').includes(before)) return paragraph;
        done = true;
        return { ...paragraph, text: paragraph.text.replace(before, after) };
      }),
    };
  });
}

export default function ReportStage({ run, bundle, report, reportPending, onRefresh }) {
  const [selection, setSelection] = useState(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState('');
  const [shift, setShift] = useState(null);
  const [preview, setPreview] = useState(false);
  const [marking, setMarking] = useState(false);
  const [hand, setHand] = useState(null);
  const [openCites, setOpenCites] = useState(() => new Set());
  const [edited, setEdited] = useState(null);
  const [thread, setThread] = useState([]);
  const [chatOpen, setChatOpen] = useState(false);
  const [focusChat, setFocusChat] = useState('');
  const railRef = useRef(null);
  const stageRef = useRef(null);
  const dockRef = useRef(null);
  const flight = useRef(null);
  const skipSave = useRef(true);
  const seenTurns = useRef(0);

  const payload = bundle?.result?.result || {};
  const verdict = payload.verdict || run?.verdict || {};
  const decision = verdict.decision || 'Pending';
  const rules = Array.isArray(payload.rules) ? payload.rules : [];
  const kills = rules.filter((rule) => rule.tier === 'kill');
  const changes = (Array.isArray(payload.what_would_change) ? payload.what_would_change : []).filter(
    (item) => item?.action === 'set' && item.fact && item.to != null,
  );
  const claims = bundle?.claims ?? [];
  const claimById = useMemo(() => {
    const map = new Map();
    for (const claim of claims) map.set(claim.id, claim);
    return map;
  }, [claims]);

  const sourceSections = useMemo(
    () => orderSections(Array.isArray(report?.sections) ? report.sections : []),
    [report],
  );
  const sections = edited || sourceSections;

  useEffect(() => {
    if (!run?.id) return;
    skipSave.current = true;
    setChatOpen(false);
    setFocusChat('');
    try {
      const saved = JSON.parse(localStorage.getItem(`unobio-chats:${run.id}`) || 'null');
      setThread(Array.isArray(saved?.thread) ? saved.thread : []);
      setEdited(Array.isArray(saved?.edited) ? saved.edited : null);
    } catch {
      setThread([]);
      setEdited(null);
    }
  }, [run?.id]);

  useEffect(() => {
    if (!run?.id) return;
    if (skipSave.current) {
      skipSave.current = false;
      return;
    }
    try {
      localStorage.setItem(`unobio-chats:${run.id}`, JSON.stringify({ thread, edited }));
    } catch {
      // The browser refused the write. The chat still works for this visit.
    }
  }, [run?.id, thread, edited]);

  useEffect(() => {
    if (thread.length > seenTurns.current && chatOpen && !focusChat) {
      const node = railRef.current;
      if (node) node.scrollTop = node.scrollHeight;
    }
    seenTurns.current = thread.length;
  }, [thread, chatOpen, focusChat]);

  useEffect(() => {
    if (!focusChat || !chatOpen) return;
    document.getElementById(`revise-${focusChat}`)?.scrollIntoView({ block: 'nearest' });
  }, [focusChat, chatOpen, thread]);

  const numbers = useMemo(() => {
    const map = new Map();
    let next = 1;
    const take = (id) => {
      if (!id || map.has(id)) return;
      map.set(id, next);
      next += 1;
    };
    for (const section of sections) {
      for (const paragraph of section.paragraphs || []) {
        for (const id of paragraph.claim_ids || []) take(id);
      }
    }
    for (const claim of claims) {
      if (claim.status === 'pending') take(claim.id);
    }
    return map;
  }, [sections, claims]);

  const cited = useMemo(() => {
    const ids = new Set();
    for (const section of sections) {
      if (section.id === 'sources') continue;
      for (const paragraph of section.paragraphs || []) {
        for (const id of paragraph.claim_ids || []) ids.add(id);
      }
    }
    return ids;
  }, [sections]);
  const uncitedPending = claims.filter((claim) => claim.status === 'pending' && !cited.has(claim.id));

  const openClaim = selection?.type === 'claim' ? claimById.get(selection.id) : null;
  const openFact = selection?.type === 'fact' ? selection.item : null;
  const pendingOpen = openClaim?.status === 'pending';
  const pair = [run?.disease?.name || run?.disease_input, run?.target?.symbol || run?.target_input]
    .filter(Boolean)
    .join(' · ');

  const guidance = notice
    || (pendingOpen
      ? 'Sending confirms this claim. The verdict updates after you send.'
      : openFact
        ? 'Add a source for this condition. A URL in the text is stored as the link; otherwise the text is the source.'
        : '');

  const placeholder = pendingOpen
    ? 'Confirm this claim'
    : openFact
      ? 'Paste a source URL or the source text'
      : 'Edit the report';

  const suggestions = useMemo(() => {
    const rows = [];
    if (pendingOpen && openClaim) {
      rows.push({
        key: `confirm-${openClaim.id}`,
        name: `Confirm [${numbers.get(openClaim.id) || '?'}]`,
        description: 'Keeps the claim. The verdict updates after you send.',
        action: 'confirm',
      });
    }
    for (const item of changes.slice(0, 3)) {
      const name = String(item.label || item.fact).split('. ')[0];
      rows.push({
        key: factKey(item),
        name,
        description: `Would move the verdict to ${item.verdict_to}.`,
        action: 'fact',
        item,
      });
    }
    if (!rows.length) {
      rows.push({
        key: 'edit-hint',
        name: 'Edit the report',
        description: 'Ask for a wording change. Approve applies it on this page.',
        action: 'hint',
      });
    }
    return rows;
  }, [pendingOpen, openClaim, changes, numbers]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key !== 'Escape') return;
      if (preview) {
        setPreview(false);
        setMarking(false);
        setHand(null);
        return;
      }
      setOpenCites(new Set());
      setSelection(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [preview]);

  const toggleCite = (id) => {
    setNotice('');
    setOpenCites((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    if (claimById.get(id)?.status === 'pending') setSelection({ type: 'claim', id });
  };

  const applyChange = async (data) => {
    const decisionChange = data?.change?.decision;
    setShift(decisionChange?.changed ? { from: decisionChange.from, to: decisionChange.to } : null);
    setDraft('');
    setNotice('');
    if (onRefresh && run?.id) await onRefresh(run.id);
  };

  const onSend = async (text) => {
    if (busy || !run?.id) return;
    if (pendingOpen && openClaim) {
      setBusy(true);
      setNotice('');
      try {
        const data = await submitEvidence(run.id, { action: 'confirm', claim_id: openClaim.id });
        await applyChange(data);
      } catch (err) {
        setNotice(err?.message || 'Could not confirm this claim.');
      } finally {
        setBusy(false);
      }
      return;
    }
    if (openFact) {
      const body = evidenceFromText(text, openFact.label || openFact.fact);
      if (!body.source_url && !body.source_text) {
        setNotice('Add a source URL or paste the source text.');
        return;
      }
      setBusy(true);
      setNotice('');
      try {
        const data = await submitEvidence(run.id, {
          action: 'add',
          fact: openFact.fact,
          value: openFact.to,
          statement: body.statement,
          ...(body.source_url ? { source_url: body.source_url } : { source_text: body.source_text }),
        });
        await applyChange(data);
      } catch (err) {
        setNotice(err?.message || 'Could not add this evidence.');
      } finally {
        setBusy(false);
      }
      return;
    }
    startRevision(text);
  };

  const onSuggestion = (row) => {
    setNotice('');
    if (row.action === 'confirm') {
      onSend('');
      return;
    }
    if (row.action === 'fact' && row.item) {
      setSelection({ type: 'fact', key: factKey(row.item), item: row.item });
      setDraft('');
      return;
    }
    setNotice('');
  };

  const closePreview = () => {
    setPreview(false);
    setMarking(false);
    setHand(null);
  };

  const beginHandEdit = (key) => {
    const splitAt = key.lastIndexOf(':');
    const sectionId = key.slice(0, splitAt);
    const index = Number(key.slice(splitAt + 1));
    const section = sections.find((item) => item.id === sectionId);
    const text = String(section?.paragraphs?.[index]?.text || '');
    if (!text.trim()) return;
    setHand({ key, sectionId, index, value: text });
  };

  const saveHand = () => {
    if (!hand) return;
    const nextText = hand.value.trim();
    const current = String(sections.find((item) => item.id === hand.sectionId)?.paragraphs?.[hand.index]?.text || '');
    if (nextText && nextText !== current.trim()) {
      setEdited(replaceParagraphAt(sections, hand.sectionId, hand.index, nextText));
    }
    setHand(null);
  };

  const startRevision = async (instruction, focusSections) => {
    const text = instruction.trim();
    if (!text || !run?.id || busy) return;
    const payloadSections = focusSections?.length
      ? focusSections
      : sections
        .filter((section) => section.id !== 'sources')
        .map((section) => ({
          id: section.id,
          title: section.title || section.id,
          text: passageText(section).slice(0, 4000),
        }))
        .filter((section) => section.text);
    const id = `rev-${Date.now()}`;
    if (!chatOpen) armDockFlight();
    setChatOpen(true);
    setFocusChat('');
    setThread((current) => [
      ...current,
      {
        id,
        instruction: text,
        status: payloadSections.length ? 'working' : 'error',
        snapshot: cloneSections(sections),
        note: payloadSections.length ? '' : 'There is no memo text to edit.',
      },
    ]);
    setDraft('');
    setNotice('');
    if (!payloadSections.length) return;
    setBusy(true);
    try {
      const data = await proposeEdit(run.id, { instruction: text, sections: payloadSections });
      const pending = Boolean(data?.before && data?.after);
      setThread((current) => current.map((row) => (
        row.id === id
          ? {
            ...row,
            status: pending ? 'pending' : 'question',
            section_id: data.section_id,
            section_title: data.section_title,
            before: data.before,
            after: data.after,
            note: data.note || '',
          }
          : row
      )));
    } catch (err) {
      setThread((current) => current.map((row) => (
        row.id === id
          ? { ...row, status: 'error', note: err?.message || 'Could not draft this edit.' }
          : row
      )));
    } finally {
      setBusy(false);
    }
  };

  const approveRevision = (row) => {
    if (!row.before || !row.after || !row.section_id) return;
    const next = replacePassage(sections, row.section_id, row.before, row.after);
    const changed = next.some((section, index) => section !== sections[index]);
    if (!changed) {
      setThread((current) => current.map((item) => (
        item.id === row.id ? { ...item, note: 'That passage is no longer in the memo.' } : item
      )));
      return;
    }
    setEdited(next);
    setThread((current) => current.map((item) => (
      item.id === row.id ? { ...item, status: 'approved' } : item
    )));
    document.getElementById(`wiki-${row.section_id}`)?.scrollIntoView({ block: 'start' });
  };

  const cancelRevision = (id) => {
    setThread((current) => current.map((item) => (
      item.id === id ? { ...item, status: 'cancelled' } : item
    )));
  };

  const restoreRevision = (row) => {
    if (!row.snapshot) return;
    setEdited(cloneSections(row.snapshot));
    setThread((current) => current.map((item) => (
      item.id === row.id && item.status === 'approved' ? { ...item, status: 'pending' } : item
    )));
  };

  const onExport = async () => {
    if (!run?.id || exporting) return;
    setExporting(true);
    setNotice('');
    try {
      await downloadReportMarkdown(run.id, { filename: memoFilename(run) });
    } catch (err) {
      setNotice(err?.message || 'Could not export the memo.');
    } finally {
      setExporting(false);
    }
  };

  const reading = sections.filter((section) => section.id !== 'sources');
  const citedIds = [];
  const seenCite = new Set();
  for (const section of reading) {
    for (const paragraph of compactParagraphs(section)) {
      for (const id of paragraph.claim_ids || []) {
        if (seenCite.has(id) || !numbers.has(id)) continue;
        seenCite.add(id);
        citedIds.push(id);
      }
    }
  }

  const split = chatOpen && thread.length > 0;
  const openChat = (id) => {
    if (!chatOpen) armDockFlight();
    setChatOpen(true);
    setFocusChat(id);
  };
  const closeChat = () => {
    if (!chatOpen) return;
    armDockFlight();
    setChatOpen(false);
    setFocusChat('');
  };

  const placeDock = () => {
    const dock = dockRef.current;
    const col = stageRef.current?.querySelector('.revise-col');
    if (!dock || !col) return;
    const rect = col.getBoundingClientRect();
    dock.style.right = 'auto';
    dock.style.left = `${rect.left}px`;
    dock.style.width = `${rect.width}px`;
  };

  const armDockFlight = () => {
    const bar = dockRef.current?.querySelector('.prompt-bar');
    if (!bar) return;
    flight.current = bar.getBoundingClientRect();
  };

  useLayoutEffect(() => {
    const dock = dockRef.current;
    if (!dock) return undefined;
    const bar = dock.querySelector('.prompt-bar');
    const first = flight.current;
    if (split) placeDock();
    else {
      dock.style.left = '';
      dock.style.width = '';
      dock.style.right = '';
    }
    if (!bar || !first) return undefined;
    const last = bar.getBoundingClientRect();
    const dx = first.left - last.left;
    const dy = first.top - last.top;
    const shrink = Math.abs(first.width - last.width) > 1;
    if (Math.hypot(dx, dy) < 2 && !shrink) {
      flight.current = null;
      return undefined;
    }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      flight.current = null;
      return undefined;
    }
    bar.style.transition = 'none';
    bar.style.transform = `translate(${dx}px, ${dy}px)`;
    bar.style.width = `${first.width}px`;
    bar.getBoundingClientRect();
    bar.style.transition = 'transform 640ms cubic-bezier(0.22, 1, 0.36, 1), width 640ms cubic-bezier(0.22, 1, 0.36, 1)';
    bar.style.transform = 'translate(0px, 0px)';
    bar.style.width = `${last.width}px`;
    const done = (event) => {
      if (event && event.propertyName && event.propertyName !== 'transform') return;
      bar.style.transition = '';
      bar.style.transform = '';
      bar.style.width = '';
      bar.removeEventListener('transitionend', done);
      window.clearTimeout(timer);
      flight.current = null;
    };
    bar.addEventListener('transitionend', done);
    const timer = window.setTimeout(done, 900);
    return () => {
      window.clearTimeout(timer);
      bar.removeEventListener('transitionend', done);
      bar.style.transition = '';
      bar.style.transform = '';
      bar.style.width = '';
    };
  }, [split]);

  useEffect(() => {
    if (!split) return undefined;
    const place = () => placeDock();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [split]);

  return (
    <div className={split ? 'report-stage is-split' : 'report-stage'} ref={stageRef}>
      {split ? (
        <div className="revise-col">
          <button type="button" className="back-link revise-back" onClick={closeChat}>
            Report →
          </button>
          <ReviseRail
            railRef={railRef}
            thread={thread}
            onApprove={approveRevision}
            onCancel={cancelRevision}
            onRestore={restoreRevision}
          />
        </div>
      ) : null}
      <article className="wiki" aria-label="Investment memo">
        <header className="wiki-top">
          <p className="wiki-kicker">{pair || 'Investment memo'}</p>
          {split ? null : (
            <div className="doc-actions">
              <button type="button" className="doc-preview" onClick={() => setPreview(true)} disabled={!sections.length}>
                Preview
              </button>
              <button
                type="button"
                className="report-export"
                onClick={onExport}
                disabled={exporting || !run?.id || !sections.length}
              >
                {exporting ? 'Exporting…' : 'Export'}
              </button>
            </div>
          )}
        </header>

        <div className="wiki-frame">
          <div className="wiki-rail">
            <nav className="wiki-toc" aria-label="Contents">
              <p>Contents</p>
              <ol>
                {reading.map((section) => (
                  <li key={section.id}>
                    <a href={`#wiki-${section.id}`}>{section.title || section.id}</a>
                  </li>
                ))}
                <li>
                  <a href="#wiki-references">References</a>
                </li>
              </ol>
            </nav>
            {thread.length ? (
              <nav className="wiki-chats" aria-label="Chats">
                <p>Chats</p>
                <ol>
                  {thread.map((row) => (
                    <li key={row.id}>
                      <button type="button" onClick={() => openChat(row.id)}>
                        {row.instruction}
                      </button>
                    </li>
                  ))}
                </ol>
              </nav>
            ) : null}
          </div>

          <div className="wiki-main">
            <div className={split || reportPending ? 'wiki-title-row' : undefined}>
              <h1 className="wiki-title" data-v={decision}>
                {decision}
              </h1>
              {reportPending && !split ? (
                <LatticeLoader
                  className="wiki-think"
                  status="working"
                  label="Thinking"
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
              ) : null}
              {split ? (
                <div className="doc-actions">
                  <button type="button" className="doc-preview" onClick={() => setPreview(true)} disabled={!sections.length}>
                    Preview
                  </button>
                  <button
                    type="button"
                    className="report-export"
                    onClick={onExport}
                    disabled={exporting || !run?.id || !sections.length}
                  >
                    {exporting ? 'Exporting…' : 'Export'}
                  </button>
                </div>
              ) : null}
            </div>
            {shift ? (
              <p className="report-shift">
                {shift.from} → {shift.to}
              </p>
            ) : null}
            {reading.length ? (
              <>
                {reading.map((section) => (
                  <WikiSection
                    key={section.id}
                    section={section}
                    claimById={claimById}
                    numbers={numbers}
                    openCites={openCites}
                    onToggle={toggleCite}
                    uncitedPending={section.id === 'recommendation' ? uncitedPending : []}
                  />
                ))}
                <section className="wiki-section" id="wiki-references">
                  <h2>References</h2>
                  <ol className="wiki-refs">
                    {citedIds.map((id) => (
                      <li key={id} value={numbers.get(id)}>
                        <CiteFold
                          id={id}
                          claim={claimById.get(id)}
                          open={openCites.has(id)}
                          onToggle={toggleCite}
                          number={numbers.get(id)}
                        />
                      </li>
                    ))}
                  </ol>
                </section>
              </>
            ) : reportPending ? null : (
              <p className="doc-gap">
                Report gap. The memo has no sections yet.
              </p>
            )}
          </div>

          {split ? null : <aside className="wiki-box">
            <p className="wiki-box-title">Underwriting</p>
            <dl>
              <div>
                <dt>Decision</dt>
                <dd>{decision}</dd>
              </div>
              <div>
                <dt>Grounds</dt>
                <dd>{verdict.grounds_text || 'Not stated in the memo.'}</dd>
              </div>
              <div>
                <dt>Kill rule</dt>
                <dd>{kills.length ? kills.map((rule) => rule.name).join('; ') : 'None fired'}</dd>
              </div>
            </dl>
          </aside>}
        </div>
      </article>

      {preview ? (
        <div className="doc-modal" role="dialog" aria-modal="true" aria-label="Report preview" onClick={closePreview}>
          <div className="doc-sheet" onClick={(event) => event.stopPropagation()}>
            <div className="doc-sheet-bar">
              <button
                type="button"
                className="doc-preview"
                aria-pressed={marking}
                onClick={() => {
                  setMarking((on) => !on);
                  setHand(null);
                }}
              >
                Edit
              </button>
              <button type="button" className="doc-preview" onClick={closePreview}>
                Close
              </button>
              <button type="button" className="report-export" onClick={onExport} disabled={exporting || !run?.id}>
                {exporting ? 'Exporting…' : 'Export'}
              </button>
            </div>
            {marking ? <p className="doc-mark-hint">Click a passage and rewrite it.</p> : null}
            <p className="report-pair">{pair}</p>
            <h1 className="report-decision" data-v={decision}>
              {decision}
            </h1>
            {sections.map((section) => (
              <section key={`preview-${section.id}`} className="doc-preview-section">
                <h2>{section.title || section.id}</h2>
                <SectionBody
                  section={section}
                  numbers={numbers}
                  marking={marking}
                  hand={hand}
                  onEdit={beginHandEdit}
                  onHandChange={(value) => setHand((current) => (current ? { ...current, value } : current))}
                  onHandSave={saveHand}
                  onHandCancel={() => setHand(null)}
                  onCite={(id) => {
                    closePreview();
                    setOpenCites((current) => {
                      const next = new Set(current);
                      next.add(id);
                      return next;
                    });
                  }}
                />
              </section>
            ))}
          </div>
        </div>
      ) : null}

      <div className="report-dock" ref={dockRef}>
        {guidance ? (
          <p className="report-hint" role="status">
            {guidance}
          </p>
        ) : null}
        <PromptBar
          plain
          allowEmpty={pendingOpen}
          busy={busy}
          value={draft}
          onChange={setDraft}
          onSend={onSend}
          placeholder={placeholder}
          width={split ? 640 : 880}
          suggestions={suggestions}
          onSuggestion={onSuggestion}
        />
      </div>
    </div>
  );
}

function RewindMark() {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true">
      <path
        d="M3.2 8.2a4.6 4.6 0 1 0 1.15-3.15"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <path d="M3 2.7v3.2h3.2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ReviseRail({ railRef, thread, onApprove, onCancel, onRestore }) {
  const [askId, setAskId] = useState(null);

  useEffect(() => {
    if (!askId) return undefined;
    const close = (event) => {
      if (event.key === 'Escape') setAskId(null);
    };
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [askId]);

  return (
    <div className="revise-rail" ref={railRef} aria-label="Edit history">
      {thread.map((row) => {
        const asking = askId === row.id;
        return (
          <article className="revise-card" id={`revise-${row.id}`} key={row.id}>
            <p className="revise-user">{row.instruction}</p>
            {row.status === 'working' ? <p className="revise-status">Drafting the edit…</p> : null}
            {row.note && row.status !== 'working' ? <p className="revise-note">{row.note}</p> : null}
            {row.before ? (
              <div className="revise-diff">
                {row.section_title ? <p className="revise-kicker">{row.section_title}</p> : null}
                <p className="revise-before">{row.before}</p>
                {row.after ? <p className="revise-after">{row.after}</p> : null}
              </div>
            ) : null}
            <div className="revise-actions">
              {row.status === 'pending' ? (
                <>
                  <button type="button" className="revise-approve" onClick={() => onApprove(row)}>
                    Approve
                  </button>
                  <button type="button" className="revise-cancel" onClick={() => onCancel(row.id)}>
                    Cancel
                  </button>
                </>
              ) : null}
              {row.status === 'approved' ? <span className="revise-flag">Applied</span> : null}
              {row.status === 'cancelled' ? <span className="revise-flag">Cancelled</span> : null}
              <div className="revise-rewind-wrap">
                {asking ? (
                  <div className="revise-pop" role="dialog" aria-label="Revert this edit">
                    <p>Revert this edit?</p>
                    <div className="revise-pop-actions">
                      <button
                        type="button"
                        className="revise-approve"
                        onClick={() => {
                          onRestore(row);
                          setAskId(null);
                        }}
                      >
                        Revert
                      </button>
                      <button type="button" className="revise-cancel" onClick={() => setAskId(null)}>
                        Keep
                      </button>
                    </div>
                  </div>
                ) : null}
                <button
                  type="button"
                  className={asking ? 'revise-rewind is-ask' : 'revise-rewind'}
                  aria-label="Restore the memo to this point"
                  aria-expanded={asking}
                  title="Restore the memo to this point"
                  onClick={() => setAskId(asking ? null : row.id)}
                >
                  <RewindMark />
                </button>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

function WikiSection({ section, claimById, numbers, openCites, onToggle, uncitedPending }) {
  const paragraphs = compactParagraphs(section);
  return (
    <section className="wiki-section" id={`wiki-${section.id}`}>
      <h2>{section.title || section.id}</h2>
      {paragraphs.length ? (
        paragraphs.map((paragraph, index) => {
          const parts = section.id === 'diligence_questions' ? { lead: paragraph.text, rest: '' } : leadOf(paragraph.text);
          const ids = paragraph.claim_ids || [];
          return (
            <div key={`${section.id}-${index}`} className="wiki-passage">
              <p>
                {paragraph.kind === 'inference' ? <span className="wiki-note">Model inference. </span> : null}
                {parts.lead}
                {ids.map((id) => (
                  <CiteMark key={id} id={id} number={numbers.get(id)} open={openCites.has(id)} onToggle={onToggle} />
                ))}
              </p>
              {ids.map((id) => (
                <CitePanel
                  key={`${id}-panel`}
                  claim={claimById.get(id)}
                  rest={parts.rest}
                  open={openCites.has(id)}
                />
              ))}
            </div>
          );
        })
      ) : (
        <p className="doc-gap">Report gap. This section has no text in the saved memo.</p>
      )}
      {uncitedPending.map((claim) => (
        <div key={claim.id} className="wiki-passage">
          <p>
            <span className="wiki-note">Pending. </span>
            {leadOf(claim.statement).lead}
            <CiteMark id={claim.id} number={numbers.get(claim.id)} open={openCites.has(claim.id)} onToggle={onToggle} />
          </p>
          <CitePanel claim={claim} rest={leadOf(claim.statement).rest} open={openCites.has(claim.id)} />
        </div>
      ))}
    </section>
  );
}

function SectionBody({ section, numbers, onCite, marking, hand, onEdit, onHandChange, onHandSave, onHandCancel }) {
  const paragraphs = section.paragraphs || [];
  if (!paragraphs.length) {
    return <p className="doc-gap">Report gap. This section has no text in the saved memo.</p>;
  }
  return paragraphs.map((paragraph, index) => {
    const key = `${section.id}:${index}`;
    const editing = hand?.key === key;
    return (
      <p
        key={key}
        className={marking && !editing ? 'doc-p doc-p--mark' : 'doc-p'}
        data-kind={paragraph.kind}
        onClick={marking && !editing ? () => onEdit(key) : undefined}
      >
        {paragraph.kind === 'inference' ? <span className="doc-infer">Model inference. </span> : null}
        {editing ? (
          <span className="doc-hand" onClick={(event) => event.stopPropagation()}>
            <textarea
              value={hand.value}
              aria-label="Rewrite this passage"
              onChange={(event) => onHandChange(event.target.value)}
            />
            <span className="doc-hand-actions">
              <button type="button" className="revise-approve" onClick={onHandSave}>Save</button>
              <button type="button" className="revise-cancel" onClick={onHandCancel}>Cancel</button>
            </span>
          </span>
        ) : (
          <span>{paragraph.text}</span>
        )}
        {(paragraph.claim_ids || []).map((id) =>
          numbers.get(id) ? (
            <button
              key={id}
              type="button"
              className="doc-cite"
              onClick={(event) => {
                event.stopPropagation();
                onCite(id);
              }}
            >
              [{numbers.get(id)}]
            </button>
          ) : null,
        )}
      </p>
    );
  });
}

function CiteMark({ id, number, open, onToggle }) {
  if (!number) return null;
  return (
    <button
      type="button"
      className="wiki-cite"
      aria-expanded={open}
      aria-label={`Source ${number}`}
      onClick={() => onToggle(id)}
    >
      <Caret open={open} />[{number}]
    </button>
  );
}

function Caret({ open }) {
  return <span className="wiki-caret" data-open={open ? '' : undefined} aria-hidden="true" />;
}

function CiteFold({ id, claim, open, onToggle, number }) {
  const label = claim?.statement || claim?.id || id;
  return (
    <div>
      <button type="button" className="wiki-cite wiki-cite--row" aria-expanded={open} onClick={() => onToggle(id)}>
        <Caret open={open} />
        <span className="wiki-ref-no">[{number}]</span>
        <span>{label}</span>
      </button>
      <CitePanel claim={claim} open={open} />
      <span className="wiki-ref-no">[{number}]</span>
    </div>
  );
}

function CitePanel({ claim, rest, open }) {
  const quote = claim?.quote && claim.quote !== rest ? claim.quote : '';
  return (
    <div className="wiki-fold" data-open={open ? '' : undefined}>
      <div className="wiki-fold-clip">
        <div className="wiki-fold-body">
          {rest ? <p>{rest}</p> : null}
          {quote ? <p className="wiki-quote">{quote}</p> : null}
          {claim ? <ClaimLinks claim={claim} /> : null}
          {claim?.status === 'pending' ? <p className="wiki-note">Pending confirmation</p> : null}
          {claim?.id ? <p className="doc-claim-id">{claim.id}</p> : null}
        </div>
      </div>
    </div>
  );
}

function ClaimLinks({ claim }) {
  const sources = Array.isArray(claim.sources) ? claim.sources : [];
  if (!sources.length) return <p className="doc-gap">No linked source on this claim.</p>;
  return (
    <ul className="report-links">
      {sources.map((source, index) => (
        <li key={`${source.url || source.id || 'source'}-${index}`}>
          {source.url ? (
            <a href={source.url} target="_blank" rel="noreferrer">
              {sourceLabel(source)}
            </a>
          ) : (
            <span>{source.text || sourceLabel(source)}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

