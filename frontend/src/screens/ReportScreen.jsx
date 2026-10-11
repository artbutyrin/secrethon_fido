import { useMemo, useState } from 'react';
import { MOCK_RESULT } from '../data/mockResult';
import './screens.css';

function renderMarkdown(md, onCite) {
  const lines = md.split('\n');
  return lines.map((line, idx) => {
    if (line.startsWith('# ')) return <h1 key={idx}>{line.slice(2)}</h1>;
    if (line.startsWith('## ')) return <h2 key={idx}>{line.slice(3)}</h2>;
    if (!line.trim()) return <br key={idx} />;
    if (line.startsWith('- ')) {
      return (
        <li key={idx} style={{ marginLeft: 18 }}>
          {inline(line.slice(2), onCite)}
        </li>
      );
    }
    if (/^\d+\.\s/.test(line)) {
      return (
        <li key={idx} style={{ marginLeft: 18 }}>
          {inline(line.replace(/^\d+\.\s/, ''), onCite)}
        </li>
      );
    }
    return (
      <p key={idx} style={{ margin: '0.55rem 0' }}>
        {inline(line, onCite)}
      </p>
    );
  });
}

function inline(text, onCite) {
  const parts = text.split(/(\*\*[^*]+\*\*|\[C-\d+\])/g);
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    if (/^\[C-\d+\]$/.test(part)) {
      return (
        <button key={i} type="button" className="cite" onClick={() => onCite?.(part.slice(1, -1))}>
          {part}
        </button>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export default function ReportScreen({ onCite }) {
  const [format, setFormat] = useState('md');
  const [toast, setToast] = useState('');

  const body = useMemo(() => renderMarkdown(MOCK_RESULT.reportMd, onCite), [onCite]);

  const exportReport = () => {
    if (format === 'md') {
      const blob = new Blob([MOCK_RESULT.reportMd], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'unobio-memo.md';
      a.click();
      URL.revokeObjectURL(url);
      setToast('Exported MD');
    } else {
      setToast('PDF is not available. Use the Markdown export.');
    }
    setTimeout(() => setToast(''), 2200);
  };

  return (
    <section className="screen">
      <div className="report-toolbar">
        <div>
          <h2 className="screen-title">Memo</h2>
        </div>
        <div className="export-group">
          <select
            className="export-select"
            value={format}
            onChange={(e) => setFormat(e.target.value)}
            aria-label="Export format"
          >
            <option value="md">Markdown (.md)</option>
            <option value="pdf">PDF (.pdf)</option>
          </select>
          <button type="button" className="btn btn-primary" onClick={exportReport}>
            Export
          </button>
        </div>
      </div>
      {toast ? <p className="tag tag--forest">{toast}</p> : null}
      <article className="report-body">{body}</article>
    </section>
  );
}
