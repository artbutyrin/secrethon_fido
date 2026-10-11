import { useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import GradientWaves from './GradientWaves';

const COLUMNS = [
  {
    title: 'Product',
    links: [
      { label: 'Underwrite', href: '/#underwrite' },
      { label: 'Request', to: '/request' },
      { label: 'Investment memo', href: '/#underwrite' },
    ],
  },
  {
    title: 'Method',
    links: [
      { label: 'Disease biology' },
      { label: 'Clinical evidence' },
      { label: 'rNPV verdict' },
    ],
  },
  {
    title: 'Team: FIdo',
    links: [
      { label: 'fido@ukma.edu.ua', href: 'mailto:fido@ukma.edu.ua' },
      { label: 'Kyiv' },
    ],
  },
];

function paintWordmark(canvas) {
  const cssW = canvas.clientWidth;
  const cssH = canvas.clientHeight;
  if (cssW < 8 || cssH < 8) return;

  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(cssW * dpr);
  canvas.height = Math.round(cssH * dpr);

  const mask = document.createElement('canvas');
  mask.width = canvas.width;
  mask.height = canvas.height;
  const maskCtx = mask.getContext('2d');
  maskCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  maskCtx.fillStyle = '#fff';
  maskCtx.textAlign = 'center';
  maskCtx.textBaseline = 'middle';
  let size = cssH * 0.86;
  const word = 'unobio';
  maskCtx.font = `700 ${size}px "Open Sans", system-ui, sans-serif`;
  while (maskCtx.measureText(word).width > cssW * 0.98 && size > 28) {
    size *= 0.96;
    maskCtx.font = `700 ${size}px "Open Sans", system-ui, sans-serif`;
  }
  maskCtx.fillText(word, cssW / 2, cssH * 0.58);
  const pixels = maskCtx.getImageData(0, 0, canvas.width, canvas.height).data;

  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);

  const gap = cssW < 720 ? 5 : 7;
  const tri = gap * 0.42;
  for (let y = gap * 0.6; y < cssH; y += gap) {
    const fade = Math.min(1, Math.max(0, (y / cssH - 0.08) / 0.55));
    if (fade <= 0.02) continue;
    ctx.fillStyle = `rgba(186, 178, 198, ${0.15 + fade * 0.62})`;
    for (let x = gap * 0.5; x < cssW; x += gap) {
      const px = Math.min(canvas.width - 1, Math.floor(x * dpr));
      const py = Math.min(canvas.height - 1, Math.floor(y * dpr));
      const alpha = pixels[(py * canvas.width + px) * 4 + 3];
      if (alpha > 40) continue;
      ctx.beginPath();
      ctx.moveTo(x, y - tri);
      ctx.lineTo(x + tri * 0.86, y + tri * 0.72);
      ctx.lineTo(x - tri * 0.86, y + tri * 0.72);
      ctx.closePath();
      ctx.fill();
    }
  }
}

export default function AboutBand() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    let frame = 0;
    const draw = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => paintWordmark(canvas));
    };

    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);

  return (
    <section id="next" className="about-band" aria-label="About">
      <GradientWaves
        className="about-band__waves"
        horizonColor="#032d2a"
        waveColor="#165880"
        crestColor="#FFFFFF"
        speed={0.35}
        amplitude={1.85}
        waveScale={0.55}
        waveRatio={0.6}
        swell={29.5}
        turbulence={26.5}
        tilt={1.25}
        zoom={1.15}
        height={5.4}
        fogDepth={15}
        detail="medium"
        brightness={1.1}
        opacity={1}
        mouseInteraction={false}
        parallaxStrength={0.5}
        grain
        grainIntensity={0.05}
      />
      <div className="about-band__top">
        <div className="about-band__brand">
          <p className="about-band__lockup">
            <svg className="about-band__mark" viewBox="0 0 24 24" aria-hidden="true">
              <path
                fill="currentColor"
                d="M11.2 2.2h1.6l.35 6.1 5.2-3.2 1.05 1.2-4.7 3.7 5.5 2.1-.55 1.5-5.7-1.6.7 6.05h-1.6l.7-6.05-5.7 1.6-.55-1.5 5.5-2.1-4.7-3.7 1.05-1.2 5.2 3.2.35-6.1Z"
              />
            </svg>
            <span>unobio</span>
          </p>
          <p className="about-band__tag">
            Investment underwriting for biotech.
            <br />
            Open evidence. A written verdict.
          </p>
        </div>

        <div className="about-band__team">
          <img className="about-band__qr" src="/qr.png" alt="Team FIdo QR code" width="184" height="184" />
        </div>

        <div className="about-band__cols">
          {COLUMNS.map((column) => (
            <div key={column.title}>
              <p className="about-band__col-title">{column.title}</p>
              <ul>
                {column.links.map((item) => (
                  <li key={item.label}>
                    {item.to ? (
                      <Link to={item.to}>{item.label}</Link>
                    ) : item.href ? (
                      <a href={item.href}>{item.label}</a>
                    ) : (
                      <span>{item.label}</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>

      <div className="about-band__word">
        <canvas ref={canvasRef} className="about-band__canvas" aria-hidden="true" />
      </div>

      <div className="about-band__bar">
        <span>© {new Date().getFullYear()} Unobio</span>
        <span>Moving Beyond the Molecule</span>
      </div>
    </section>
  );
}
