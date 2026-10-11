import { useEffect, useRef, useState, lazy, Suspense } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import FixedParticleLogo from '../components/FixedParticleLogo';
import PromptBar from '../components/PromptBar';
import SpecularFrame from '../components/SpecularFrame';
import CursorGrid from '../components/CursorGrid';
import ScrollVelocity from '../components/ScrollVelocity';
import SideRays from '../components/SideRays';
import AboutBand from '../components/AboutBand';
import { useLenis } from '../hooks/useLenis';
import { useSharedAnalysis } from '../hooks/analysisContext';
import { HERO_HEAD_SRC } from '../lib/config';
import { parseUnderwriteQuery } from '../lib/parseQuery';
import { DISEASES, EXAMPLES, MECHANISMS, toSearchTerm } from '../data/suggestions';
import './LandingPage.css';

gsap.registerPlugin(ScrollTrigger);

const DitherVeilScroll = lazy(() => import('../components/DitherVeil/DitherVeilScroll'));

export default function LandingPage() {
  const progressRef = useRef(0);
  const rootRef = useRef(null);
  const pinRef = useRef(null);
  const logoRef = useRef(null);
  const [reduced, setReduced] = useState(false);
  const [draft, setDraft] = useState('');
  const [promptError, setPromptError] = useState('');
  const analysis = useSharedAnalysis();
  const navigate = useNavigate();
  const { hash } = useLocation();

  useLenis(false);

  useEffect(() => {
    const place = () => {
      const id = hash.replace('#', '');
      const target = id ? document.getElementById(id) : null;
      if (target) target.scrollIntoView();
      else {
        progressRef.current = 0;
        window.scrollTo(0, 0);
      }
      ScrollTrigger.refresh();
    };
    place();

    const onPageShow = (e) => {
      if (!e.persisted) return;
      place();
    };
    window.addEventListener('pageshow', onPageShow);
    return () => window.removeEventListener('pageshow', onPageShow);
  }, [hash]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
    const apply = () => setReduced(mq.matches);
    apply();
    mq.addEventListener?.('change', apply);
    return () => mq.removeEventListener?.('change', apply);
  }, []);

  useEffect(() => {
    if (reduced || !pinRef.current) return undefined;

    const ctx = gsap.context(() => {
      ScrollTrigger.create({
        trigger: pinRef.current,
        start: 'top top',
        end: 'bottom top',
        scrub: true,
        onUpdate: (self) => {
          progressRef.current = self.progress;
        },
      });
    }, rootRef);

    return () => ctx.revert();
  }, [reduced]);

  const sendPrompt = async (text, meta) => {
    const parsed = parseUnderwriteQuery(text);
    if (!parsed.indication.trim()) {
      setPromptError('Enter an indication or disease.');
      return;
    }
    if (!parsed.mechanism.trim()) {
      setPromptError('Add a target after ·. For example: Alzheimer disease · BACE1 inhibitor.');
      return;
    }
    setPromptError('');
    const disease = toSearchTerm(parsed.indication, DISEASES);
    const target = toSearchTerm(parsed.mechanism, MECHANISMS);
    analysis.start({ disease, target });
    navigate('/report', {
      state: {
        focus: meta?.focus || 'full',
        mode: 'invest',
        query: `${disease} · ${target}`,
      },
    });
  };

  return (
    <div className="landing" ref={rootRef}>
      <FixedParticleLogo visible handoff={!reduced} anchorRef={logoRef} />

      <section className="hero-pin" ref={pinRef} aria-label="Hero">
        <div className="hero-stage">
          {reduced ? (
            <div className="hero-static">
              <img src={HERO_HEAD_SRC} alt="" className="hero-static__img" />
            </div>
          ) : (
            <Suspense fallback={<div className="hero-fallback" />}>
              <DitherVeilScroll
                src={HERO_HEAD_SRC}
                pattern="bayer"
                pixelSize={2}
                inkColor="#120f17"
                paperColor="#f4f1ea"
                rimColor="#c8d0d4"
                rim={0}
                revealRadius={0}
                softness={0}
                linger={0}
                fit="contain"
                palette="duotone"
                levels={2}
                contrast={1.25}
                brightness={0.02}
                reverse={false}
                wander={false}
                clickBurst={false}
                disableReveal
                progressRef={progressRef}
                targetRef={logoRef}
                wordmark="unobio"
                className="hero-veil"
              />
            </Suspense>
          )}
          {/* Above the opaque dither; screen-blend so rays light the black field. */}
          <div className="hero-ticker" aria-hidden="true">
            <ScrollVelocity
              texts={[
                'Unobio some medicines never reach patients because the right partner was never found',
                'Unobio some medicines never reach patients because the right partner was never found',
              ]}
              velocity={reduced ? 0 : 46}
              className="hero-velocity__text"
              numCopies={4}
              damping={50}
              stiffness={400}
            />
          </div>
          <div className="hero-rays" aria-hidden="true">
            <SideRays
              speed={2.5}
              rayColor1="#008a48"
              rayColor2="#96c8ff"
              intensity={3.2}
              spread={2.4}
              origin="top-left"
              tilt={0}
              saturation={1.5}
              blend={0.75}
              falloff={1.35}
              opacity={1}
            />
          </div>
        </div>
      </section>

      <main>
        <section id="underwrite" className="prompt-section" aria-label="Underwrite">
          {reduced ? null : (
            <CursorGrid
              className="prompt-section__grid"
              cellSize={45}
              color="#007065"
              radius={140}
              falloff="sharp"
              holdTime={500}
              fadeDuration={1300}
              lineWidth={1.2}
              maxOpacity={1}
              fillOpacity={0}
              gridOpacity={0}
              cellRadius={2}
              clickPulse
              pulseSpeed={600}
            />
          )}
          <div className="prompt-section__inner">
            <h2
              className={`prompt-section__title${draft.trim() || analysis.busy ? ' is-hidden' : ''}`}
              aria-hidden={Boolean(draft.trim() || analysis.busy)}
            >
              Make your Invest
            </h2>
            <SpecularFrame
              radius={12}
              lineColor="#c8c8c8"
              baseColor="#2a2a2a"
              intensity={1.05}
              shineSize={11}
              shineFade={38}
              thickness={1.1}
              autoAnimate
              followMouse
            >
              <PromptBar
                placeholder="Indication · mechanism / target · drug..."
                value={draft}
                onChange={(value) => {
                  setDraft(value);
                  if (promptError) setPromptError('');
                }}
                busy={analysis.busy}
                onSend={sendPrompt}
                onStop={analysis.stop}
                width={680}
                radius={12}
                background="rgba(0, 0, 0, 0.78)"
                color="#ffffff"
                menuBackground="#000000"
                sparkColor="#ffffff"
              />
            </SpecularFrame>
            {promptError ? <p className="prompt-section__error">{promptError}</p> : null}
            {!analysis.busy ? (
              <div className="prompt-section__examples">
                {EXAMPLES.map((example) => (
                  <button
                    key={example.label}
                    type="button"
                    className="prompt-section__chip"
                    onClick={() => {
                      setDraft(example.text);
                      setPromptError('');
                    }}
                  >
                    {example.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </section>

        <AboutBand />
      </main>
    </div>
  );
}
