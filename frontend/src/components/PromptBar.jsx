'use client';

import { isValidElement, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { animate, useMotionValue, useMotionValueEvent, useReducedMotion } from 'motion/react';
import { HugeiconsIcon } from '@hugeicons/react';
import {
  ArrowDown01Icon,
  DnaIcon,
  HelpCircleIcon,
  PlusSignIcon,
  SparklesIcon,
  Tick02Icon,
  TradeUpIcon,
} from '@hugeicons/core-free-icons';
import { DISEASES, MECHANISMS, findAutocomplete } from '../data/suggestions';
import './PromptBar.css';

const ARROW_UP = [12, 4.5, 18.5, 11, 14.25, 11, 14.25, 19.5, 9.75, 19.5, 9.75, 11, 5.5, 11];
const SQUARE = [12, 6, 18, 6, 18, 12, 18, 18, 6, 18, 6, 12, 6, 6];
const EASE_IN_OUT = [0.77, 0, 0.175, 1];
const LINE = 22;
const EDGE = 11;

const DEFAULT_MODES = [
  {
    key: 'disease',
    name: 'Disease / biology',
    description: 'Indication, target, mechanism',
    icon: DnaIcon,
  },
  {
    key: 'invest',
    name: 'Investment committee',
    description: 'PoS, rNPV, verdict, DD',
    icon: TradeUpIcon,
  },
];

const DEFAULT_FOCUSES = [
  { key: 'full', name: 'Full IC', tag: 'All' },
  { key: 'science', name: 'Science', tag: 'Science' },
  { key: 'clinical', name: 'Clinical', tag: 'Clinic' },
  { key: 'commercial', name: 'Commercial', tag: 'Market' },
];

const DEFAULT_QUALITIES = ['Brief', 'Standard', 'Full', 'Memo', 'Board'];

const mix = (a, b, t) => a + (b - a) * t;
const pathAt = (a, b, t) => {
  let d = '';
  for (let i = 0; i < a.length; i += 2) {
    d += `${i ? 'L' : 'M'}${mix(a[i], b[i], t).toFixed(2)} ${mix(a[i + 1], b[i + 1], t).toFixed(2)}`;
  }
  return `${d}Z`;
};

const renderIcon = (icon, size) =>
  isValidElement(icon) ? icon : <HugeiconsIcon icon={icon} size={size} strokeWidth={1.8} />;

function SendGlyph({ busy, morphDuration, squash, tilt }) {
  const reduce = useReducedMotion();
  const svgRef = useRef(null);
  const pathRef = useRef(null);
  const dir = useRef(busy ? 1 : -1);
  const t = useMotionValue(busy ? 1 : 0);

  useEffect(() => {
    const target = busy ? 1 : 0;
    dir.current = busy ? 1 : -1;
    if (t.get() === target) return undefined;
    const controls = animate(
      t,
      target,
      reduce ? { duration: 0 } : { duration: morphDuration / 1000, ease: EASE_IN_OUT },
    );
    return () => controls.stop();
  }, [busy, morphDuration, reduce, t]);

  useMotionValueEvent(t, 'change', (v) => {
    pathRef.current?.setAttribute('d', pathAt(ARROW_UP, SQUARE, v));
    const goo = reduce ? 0 : Math.sin(v * Math.PI);
    const sx = 1 - squash * goo;
    if (svgRef.current) {
      svgRef.current.style.transform = goo
        ? `rotate(${dir.current * tilt * goo}deg) scale(${sx}, ${1 / sx})`
        : '';
    }
  });

  return (
    <svg
      ref={svgRef}
      className="prompt-bar__glyph"
      viewBox="0 0 24 24"
      aria-hidden="true"
      fill="currentColor"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinejoin="round"
    >
      <path ref={pathRef} d={pathAt(ARROW_UP, SQUARE, t.get())} />
    </svg>
  );
}

export default function PromptBar({
  placeholder = 'ask',
  modes = DEFAULT_MODES,
  focuses = DEFAULT_FOCUSES,
  qualities = DEFAULT_QUALITIES,
  defaultFocus = 'full',
  defaultQuality = 'Full',
  busy = false,
  onSend,
  onStop,
  value,
  onChange,
  background = '#050605',
  color = '#f2f4f2',
  menuBackground = '#151815',
  sparkColor = '#8fd4ad',
  sparkBoost = 1,
  width = 640,
  radius = 12,
  maxRows = 5,
  morphDuration = 240,
  squash = 0.12,
  tilt = 8,
  pressScale = 0.96,
  className = '',
  plain = false,
  allowEmpty = false,
  suggestions = [],
  onSuggestion,
}) {
  const reduce = useReducedMotion();
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const glowRef = useRef(null);
  const sparkRef = useRef(null);
  const typing = useRef({ energy: 0, strokes: 0 });
  const boost = useRef(sparkBoost);
  boost.current = sparkBoost;
  const rowRefs = useRef([]);
  const lastOpen = useRef(null);
  const latest = useRef({});
  latest.current = { onSend, onStop };

  const [innerDraft, setInnerDraft] = useState('');
  const draft = value ?? innerDraft;
  const setDraft = (next) => {
    const resolved = typeof next === 'function' ? next(draft) : next;
    if (value === undefined) setInnerDraft(resolved);
    onChange?.(resolved);
  };

  const [modeKey, setModeKey] = useState(modes[0]?.key ?? 'invest');
  const [focusKey, setFocusKey] = useState(defaultFocus);
  const [plusOpen, setPlusOpen] = useState(false);
  const [focusOpen, setFocusOpen] = useState(false);
  const [effortOpen, setEffortOpen] = useState(false);
  const [effortIndex, setEffortIndex] = useState(() => {
    const i = qualities.indexOf(defaultQuality);
    return i >= 0 ? i : Math.max(0, Math.floor((qualities.length - 1) / 2));
  });
  const [active, setActive] = useState(0);
  const [pressed, setPressed] = useState(false);

  const focus = focuses.find((m) => m.key === focusKey) ?? focuses[0];
  const mode = modes.find((m) => m.key === modeKey) ?? modes[0];
  const autocomplete = useMemo(() => {
    if (plain) return null;
    const diseaseHit = findAutocomplete(draft, DISEASES);
    if (diseaseHit) return diseaseHit;
    return findAutocomplete(draft, MECHANISMS);
  }, [draft, plain]);

  const open = plain
    ? plusOpen && suggestions.length
      ? 'suggestions'
      : null
    : plusOpen
      ? 'at'
      : focusOpen
        ? 'focus'
        : effortOpen
          ? 'effort'
          : null;
  const list = useMemo(() => {
    if (open === 'suggestions') return suggestions;
    if (open === 'at') return modes;
    if (open === 'focus') return focuses;
    return [];
  }, [open, modes, focuses, suggestions]);
  const cursor = Math.min(active, Math.max(0, list.length - 1));
  const canSend = allowEmpty || draft.trim().length > 0;
  const armed = busy || canSend;
  const level = qualities[effortIndex] ?? '';
  const maxed = qualities.length > 1 && effortIndex === qualities.length - 1;

  const focusInput = () => inputRef.current?.focus({ preventScroll: true });
  const closeMenus = useCallback(() => {
    setPlusOpen(false);
    setFocusOpen(false);
    setEffortOpen(false);
  }, []);

  const acceptGhost = () => {
    if (!autocomplete) return false;
    setDraft(autocomplete.full);
    return true;
  };

  useLayoutEffect(() => {
    const glow = glowRef.current;
    if (!glow || !open || open === 'effort') return;
    const row = rowRefs.current[cursor];
    if (!row) {
      glow.style.opacity = '0';
      return;
    }
    const fresh = lastOpen.current !== open;
    lastOpen.current = open;
    if (fresh) glow.style.transition = 'none';
    glow.style.top = `${row.offsetTop}px`;
    glow.style.height = `${row.offsetHeight}px`;
    glow.style.opacity = '1';
    if (fresh) {
      void glow.offsetHeight;
      glow.style.transition = '';
    }
  }, [open, cursor, list]);

  useEffect(() => {
    if (!open) lastOpen.current = null;
  }, [open]);

  useEffect(() => {
    if (!plusOpen && !focusOpen && !effortOpen) return undefined;
    const onDown = (e) => {
      if (!rootRef.current?.contains(e.target)) closeMenus();
    };
    document.addEventListener('pointerdown', onDown);
    return () => document.removeEventListener('pointerdown', onDown);
  }, [plusOpen, focusOpen, effortOpen, closeMenus]);

  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = '0px';
    const max = LINE * maxRows;
    el.style.height = `${Math.min(el.scrollHeight, max)}px`;
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden';
  }, [draft, maxRows]);

  useEffect(() => {
    const canvas = sparkRef.current;
    if (!maxed || reduce || !canvas) return undefined;
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;
    typing.current.strokes = 0;
    let raf = 0;
    let last = performance.now();
    let w = 0;
    let h = 0;
    let due = 0;
    let speed = 1;
    let pulse = 0;
    const parts = [];
    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      w = rect.width;
      h = rect.height;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    const spawn = (burst) => {
      parts.push({
        x: Math.random() * w,
        y: burst ? h * (0.2 + Math.random() * 0.8) : h + 3,
        r: 0.9 + Math.random() * 1.1,
        vy: -(7 + Math.random() * 9),
        sway: (Math.random() - 0.5) * 10,
        phase: Math.random() * Math.PI * 2,
        life: burst ? Math.random() * 1.2 : 0,
        span: 2.4 + Math.random() * 2.4,
      });
    };
    const tick = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const typed = typing.current;
      const gain = boost.current;
      typed.energy *= Math.exp(-dt / 0.8);
      pulse *= Math.exp(-dt / 0.16);
      if (typed.strokes > 0) {
        typed.strokes = 0;
        if (gain > 0) pulse = 1;
      }
      const energy = typed.energy * gain;
      speed += (1 + energy * 6 - speed) * (1 - Math.exp(-dt / 0.15));
      due += dt;
      while (due > 0.14) {
        due -= 0.14;
        if (parts.length < 30) spawn(false);
      }
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = sparkColor;
      ctx.shadowColor = sparkColor;
      ctx.shadowBlur = 6 + energy * 10 + pulse * 6;
      for (let i = parts.length - 1; i >= 0; i -= 1) {
        const p = parts[i];
        p.life += dt;
        if (p.life > p.span) {
          parts.splice(i, 1);
          continue;
        }
        const k = p.life / p.span;
        const twinkle = 0.7 + 0.3 * Math.sin((now / 160) * (1 + energy) + p.phase);
        p.y += p.vy * dt * speed;
        if (p.y < -4) {
          p.y = h + 3;
          p.x = Math.random() * w;
        }
        const edge = Math.min(1, Math.max(0, p.y / 14), Math.max(0, (h - p.y) / 14));
        ctx.globalAlpha = Math.min(1, Math.sin(k * Math.PI) * (0.9 + energy * 0.25) * twinkle) * edge;
        ctx.beginPath();
        ctx.arc(
          p.x + Math.sin((now / 900) * (1 + energy * 0.8) + p.phase) * p.sway,
          p.y,
          p.r * twinkle * (1 + energy * 0.35),
          0,
          Math.PI * 2,
        );
        ctx.fill();
      }
      raf = requestAnimationFrame(tick);
    };
    resize();
    for (let i = 0; i < 26; i += 1) spawn(true);
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      ctx.clearRect(0, 0, w, h);
    };
  }, [maxed, reduce, sparkColor]);

  const setEffort = (i) => {
    const next = Math.max(0, Math.min(qualities.length - 1, i));
    if (next === effortIndex) return;
    setEffortIndex(next);
  };
  const effortFromPointer = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const k = (e.clientX - rect.left - EDGE) / Math.max(1, rect.width - 2 * EDGE);
    setEffort(Math.round(k * (qualities.length - 1)));
  };
  const onEffortKey = (e) => {
    const step =
      e.key === 'ArrowRight' || e.key === 'ArrowUp'
        ? 1
        : e.key === 'ArrowLeft' || e.key === 'ArrowDown'
          ? -1
          : 0;
    if (step) {
      e.preventDefault();
      setEffort(effortIndex + step);
    } else if (e.key === 'Home') {
      e.preventDefault();
      setEffort(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      setEffort(qualities.length - 1);
    } else if (e.key === 'Escape') {
      setEffortOpen(false);
      focusInput();
    }
  };
  const stepAt = (i) => `calc(${EDGE}px + (100% - ${EDGE * 2}px) * ${i / Math.max(1, qualities.length - 1)})`;
  const fillAt = (i) => (i === qualities.length - 1 ? '100%' : `calc(${stepAt(i)} + 7px)`);

  const pick = (row) => {
    if (open === 'suggestions') {
      setPlusOpen(false);
      onSuggestion?.(row);
      focusInput();
      return;
    }
    if (open === 'focus') {
      setFocusKey(row.key);
      setFocusOpen(false);
      focusInput();
      return;
    }
    if (open === 'at') {
      setModeKey(row.key);
      setPlusOpen(false);
      focusInput();
    }
  };

  const send = () => {
    if (!canSend || busy) return;
    latest.current.onSend?.(draft.trim(), {
      mode: mode?.key,
      focus: focus?.key,
      quality: level,
    });
    closeMenus();
    focusInput();
  };

  const onKeyDown = (e) => {
    if (open && list.length) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        setActive((cursor + (e.key === 'ArrowDown' ? 1 : list.length - 1)) % list.length);
        return;
      }
      if ((e.key === 'Enter' && !e.shiftKey) || e.key === 'Tab') {
        e.preventDefault();
        pick(list[cursor]);
        return;
      }
    }
    if (e.key === 'Tab' && autocomplete) {
      e.preventDefault();
      acceptGhost();
      return;
    }
    if (e.key === 'Escape') {
      if (open) {
        e.preventDefault();
        closeMenus();
      }
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (autocomplete) {
        acceptGhost();
        return;
      }
      send();
    }
  };

  const down = (e) => {
    if (e.button !== 0 || !armed) return;
    setPressed(true);
  };
  const up = () => setPressed(false);

  return (
    <div
      ref={rootRef}
      className={`prompt-bar${className ? ` ${className}` : ''}`}
      data-busy={busy ? '' : undefined}
      data-max={maxed ? '' : undefined}
      style={{
        '--pb-bg': background,
        '--pb-ink': color,
        '--pb-menu': menuBackground,
        '--pb-w': `${width}px`,
        '--pb-radius': `${radius}px`,
        '--pb-spark': sparkColor,
        '--pb-press': pressScale,
      }}
    >
      {open ? (
        <div
          className="prompt-bar__menu"
          role={open === 'effort' ? 'dialog' : 'listbox'}
          aria-label={
            open === 'suggestions' ? 'Suggested revisions' : open === 'at' ? 'Mode' : open === 'focus' ? 'Focus' : 'Report quality'
          }
          data-kind={open === 'focus' ? 'focus' : open}
        >
          {open === 'effort' ? (
            <>
              <div className="prompt-bar__effort-head">
                <span className="prompt-bar__effort-title">MD depth</span>
                <span className="prompt-bar__effort-level">{level}</span>
                <span
                  className="prompt-bar__effort-help"
                  title="Brief → short memo. Board → full IC pack with citations"
                >
                  <HugeiconsIcon icon={HelpCircleIcon} size={14} strokeWidth={1.8} />
                </span>
              </div>
              <div className="prompt-bar__effort-ends">
                <span>Shorter</span>
                <span>Deeper MD</span>
              </div>
              <div
                className="prompt-bar__effort-track"
                role="slider"
                tabIndex={0}
                aria-label="Report quality"
                aria-valuemin={0}
                aria-valuemax={qualities.length - 1}
                aria-valuenow={effortIndex}
                aria-valuetext={level}
                style={{ '--pb-effort-x': stepAt(effortIndex), '--pb-effort-fill': fillAt(effortIndex) }}
                onPointerDown={(e) => {
                  if (e.button !== 0) return;
                  try {
                    e.currentTarget.setPointerCapture(e.pointerId);
                  } catch {
                    /* ignore */
                  }
                  e.currentTarget.focus({ preventScroll: true });
                  effortFromPointer(e);
                }}
                onPointerMove={(e) => {
                  if (e.buttons & 1) effortFromPointer(e);
                }}
                onKeyDown={onEffortKey}
              >
                <span className="prompt-bar__effort-fill" />
                {qualities.map((label, i) => (
                  <i key={label} className="prompt-bar__effort-dot" style={{ left: stepAt(i) }} />
                ))}
                <span className="prompt-bar__effort-thumb" />
              </div>
            </>
          ) : (
            <>
              <span ref={glowRef} className="prompt-bar__glow" aria-hidden="true" />
              {list.map((row, i) => (
                <button
                  key={row.key}
                  ref={(el) => {
                    rowRefs.current[i] = el;
                  }}
                  type="button"
                  role="option"
                  aria-selected={i === cursor}
                  className="prompt-bar__row"
                  onMouseDown={(e) => e.preventDefault()}
                  onPointerEnter={() => setActive(i)}
                  onClick={() => pick(row)}
                >
                  {open === 'at' ? <span className="prompt-bar__row-icon">{renderIcon(row.icon, 15)}</span> : null}
                  <span className="prompt-bar__row-name">{row.name}</span>
                  {row.description ? <span className="prompt-bar__row-desc">{row.description}</span> : null}
                  {open === 'focus' ? (
                    <>
                      <span className="prompt-bar__row-tag">{row.tag}</span>
                      <span className="prompt-bar__row-check" data-on={row.key === focus?.key ? '' : undefined}>
                        <HugeiconsIcon icon={Tick02Icon} size={13} strokeWidth={2.5} />
                      </span>
                    </>
                  ) : null}
                  {open === 'at' && row.key === mode?.key ? (
                    <span className="prompt-bar__row-check" data-on="">
                      <HugeiconsIcon icon={Tick02Icon} size={13} strokeWidth={2.5} />
                    </span>
                  ) : null}
                </button>
              ))}
            </>
          )}
        </div>
      ) : null}

      <div
        className="prompt-bar__field"
        role="presentation"
        data-max={maxed ? '' : undefined}
        onPointerDown={(e) => {
          if (e.target === e.currentTarget || e.target === inputRef.current) closeMenus();
        }}
        onClick={focusInput}
      >
        <canvas ref={sparkRef} className="prompt-bar__sparks" aria-hidden="true" />

        <div className="prompt-bar__input-wrap">
          {autocomplete ? (
            <div className="prompt-bar__ghost" aria-hidden="true">
              {/* Transparent typed prefix reserves exact width; hint sits flush after it (IDE-style). */}
              <span className="prompt-bar__ghost-typed">{draft}</span>
              <span className="prompt-bar__ghost-rest">{autocomplete.ghost}</span>
            </div>
          ) : null}
          <textarea
            ref={inputRef}
            className="prompt-bar__input"
            rows={1}
            value={draft}
            placeholder={placeholder}
            aria-label="Research prompt"
            aria-autocomplete="inline"
            spellCheck={false}
            onChange={(e) => {
              setDraft(e.target.value);
              typing.current.energy = Math.min(1.6, typing.current.energy + 0.22);
              typing.current.strokes = Math.min(4, typing.current.strokes + 1);
              closeMenus();
              setActive(0);
            }}
            onKeyDown={onKeyDown}
          />
        </div>

        <div className="prompt-bar__bar">
          {plain ? null : (
          <button
            type="button"
            className="prompt-bar__tool"
            aria-label="Choose a mode: disease or investment"
            aria-expanded={plusOpen}
            data-on={plusOpen ? '' : undefined}
            onMouseDown={(e) => e.preventDefault()}
            onClick={(e) => {
              e.stopPropagation();
              setFocusOpen(false);
              setEffortOpen(false);
              setActive(0);
              setPlusOpen((v) => !v);
            }}
          >
            <HugeiconsIcon icon={PlusSignIcon} size={16} strokeWidth={2} />
          </button>
          )}

          {!plain && focuses.length > 0 ? (
            <button
              type="button"
              className="prompt-bar__pick"
              aria-label="Focus of research"
              aria-expanded={focusOpen}
              data-on={focusOpen ? '' : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onClick={(e) => {
                e.stopPropagation();
                setPlusOpen(false);
                setEffortOpen(false);
                setActive(Math.max(0, focuses.findIndex((f) => f.key === focus?.key)));
                setFocusOpen((v) => !v);
              }}
            >
              <span>{focus?.name}</span>
              <HugeiconsIcon icon={ArrowDown01Icon} size={12} strokeWidth={2.4} />
            </button>
          ) : null}

          {!plain && qualities.length > 0 ? (
            <button
              type="button"
              className="prompt-bar__pick"
              aria-label="MD report quality"
              aria-expanded={effortOpen}
              data-on={effortOpen ? '' : undefined}
              data-max={maxed ? '' : undefined}
              onMouseDown={(e) => e.preventDefault()}
              onClick={(e) => {
                e.stopPropagation();
                setPlusOpen(false);
                setFocusOpen(false);
                setEffortOpen((v) => !v);
              }}
            >
              <HugeiconsIcon icon={SparklesIcon} size={13} strokeWidth={2} />
              <span>{level}</span>
            </button>
          ) : null}

          <span className="prompt-bar__spacer" />

          <button
            type="button"
            className="prompt-bar__send"
            disabled={!armed}
            aria-label={busy ? 'Stop' : plain ? 'Send revision' : 'Run research'}
            data-armed={armed ? '' : undefined}
            data-pressed={pressed ? '' : undefined}
            onMouseDown={(e) => e.preventDefault()}
            onPointerDown={down}
            onPointerUp={up}
            onPointerCancel={up}
            onPointerLeave={up}
            onClick={() => {
              if (busy) latest.current.onStop?.();
              else send();
            }}
          >
            <SendGlyph busy={busy} morphDuration={morphDuration} squash={squash} tilt={tilt} />
          </button>
        </div>
      </div>
    </div>
  );
}
