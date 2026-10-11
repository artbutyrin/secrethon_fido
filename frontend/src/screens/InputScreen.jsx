import { useState } from 'react';
import PromptBar from '../components/PromptBar';
import SpecularFrame from '../components/SpecularFrame';
import { EXAMPLES } from '../data/suggestions';
import './screens.css';

export default function InputScreen({ onSubmit }) {
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const send = async (text, meta) => {
    setBusy(true);
    await new Promise((r) => setTimeout(r, 350));
    setBusy(false);
    onSubmit?.({ text, ...meta });
  };

  return (
    <section className="hero">
      <h1 className="hero-brand">
        uno<em>bio</em>
      </h1>

      <div className="hero-prompt">
        <SpecularFrame
          radius={12}
          lineColor="#dce3de"
          baseColor="#3f4742"
          intensity={1.2}
          shineSize={11}
          shineFade={38}
          thickness={1.15}
          autoAnimate
          followMouse
        >
          <PromptBar
            placeholder="ask"
            value={draft}
            onChange={setDraft}
            busy={busy}
            onSend={send}
            onStop={() => setBusy(false)}
            width={680}
            radius={12}
            background="rgba(3, 4, 3, 0.72)"
            color="#f2f4f2"
            menuBackground="#121512"
            sparkColor="#8fd4ad"
          />
        </SpecularFrame>
      </div>

      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            className="example-chip"
            onClick={() => setDraft(ex.text)}
          >
            {ex.label}
          </button>
        ))}
      </div>
    </section>
  );
}
