import { useEffect, useRef } from 'react';
import { WORDMARK_BOX, waitForWordmarkFont, wordmarkDots, wordmarkDpr } from '../lib/wordmarkDots';
import './FixedParticleLogo.css';

/**
 * Fixed dithered «unobio» — never scrolls away.
 * Always paints light dots; CSS mix-blend-mode:difference → white on dark hero,
 * black on light paper (screen 2). Never paints true black (invisible on dark).
 *
 * `handoff`: stays hidden until the hero particles toggle `is-landed` on `anchorRef`,
 * so the fixed logo takes over in the same frame the particles finish forming it.
 */
export default function FixedParticleLogo({ visible = false, handoff = false, anchorRef = null, label = 'unobio' }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let cancelled = false;

    const paint = async () => {
      await waitForWordmarkFont();
      if (cancelled || !canvasRef.current) return;

      const dpr = wordmarkDpr();
      const { width, height, cell, dots } = wordmarkDots(label, dpr);
      canvas.width = width;
      canvas.height = height;
      canvas.style.width = `${WORDMARK_BOX.width}px`;
      canvas.style.height = `${WORDMARK_BOX.height}px`;

      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = '#fff';
      for (let i = 0; i < dots.length; i += 2) ctx.fillRect(dots[i], dots[i + 1], cell, cell);
    };

    paint();
    window.addEventListener('resize', paint);
    return () => {
      cancelled = true;
      window.removeEventListener('resize', paint);
    };
  }, [label]);

  const classes = ['fixed-particle-logo', visible ? 'is-visible' : '', handoff ? 'is-handoff' : '']
    .filter(Boolean)
    .join(' ');

  return (
    <div ref={anchorRef} className={classes} aria-hidden={!visible}>
      <canvas ref={canvasRef} />
    </div>
  );
}
