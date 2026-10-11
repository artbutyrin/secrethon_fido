import fs from 'fs';

let src = fs.readFileSync('src/components/DitherVeil/DitherVeil.jsx', 'utf8');

src = src.replace('const DitherVeil = ({', 'const DitherVeilScroll = ({');
src = src.replace('export default DitherVeil;', 'export default DitherVeilScroll;');

src = src.replace(
  `clickBurst = true,
  className = '',
  style
}) => {`,
  `clickBurst = true,
  progress = 0,
  progressRef = null,
  wordmark = 'unobio',
  className = '',
  style
}) => {`,
);

src = src.replace(
  `clickBurst
    };`,
  `clickBurst,
      progress,
      wordmark
    };`,
);

src = src.replace(
  `uBurstWidth: { value: 60 }
  };`,
  `uBurstWidth: { value: 60 },
    uProgress: { value: 0 },
    tWordmark: { value: dataTexture() }
  };`,
);

src = src.replace(
  `uniform float uBurstWidth;

in vec2 vUv;`,
  `uniform float uBurstWidth;
uniform float uProgress;
uniform sampler2D tWordmark;

in vec2 vUv;`,
);

src = src.replace(
  `float appear = step(spread * 0.72 + bayer(cell + vec2(3.0, 5.0)) * 0.28, uIntro * 1.001);
  fragColor = vec4(mix(uInk, color, appear), 1.0);
}`,
  `float appear = step(spread * 0.72 + bayer(cell + vec2(3.0, 5.0)) * 0.28, uIntro * 1.001);
  color = mix(uInk, color, appear);

  float p = clamp(uProgress, 0.0, 1.0);
  float cellHash = bayer(cell + vec2(11.0, 3.0));
  float drop = smoothstep(p - 0.12, p + 0.05, cellHash);
  vec2 outDir = normalize(cellUv - 0.5 + 1e-4);
  float driftAmt = (1.0 - drop) * p * 0.08;
  vec2 markUv = clamp(vUv + outDir * driftAmt, 0.0, 1.0);
  vec3 markSample = texture(tWordmark, markUv).rgb;
  float markLuma = dot(markSample, vec3(0.2126, 0.7152, 0.0722));
  float markOn = step(0.2, markLuma);
  float markPhase = smoothstep(0.25, 0.95, p);
  vec3 markColor = mix(uInk, uRimColor, markOn);
  color = mix(mix(uPaper, uInk, 0.04), color, drop);
  color = mix(color, markColor, markPhase * markOn * (0.55 + 0.45 * (1.0 - drop)));
  fragColor = vec4(color, 1.0);
}`,
);

src = src.replace(
  'renderer.render({ scene: viewMesh });',
  `const liveProgress =
      progressRef && progressRef.current != null
        ? progressRef.current
        : settingsRef.current?.progress ?? 0;
    viewUniforms.uProgress.value = Math.min(1, Math.max(0, liveProgress));
    renderer.render({ scene: viewMesh });`,
);

src = src.replace(
  'const layout = () => {',
  `const paintWordmark = () => {
    const w = Math.max(2, canvas.width);
    const h = Math.max(2, canvas.height);
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#0B1F1E';
    ctx.fillRect(0, 0, w, h);
    ctx.fillStyle = '#14B8A6';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const label = settingsRef.current?.wordmark || 'unobio';
    const size = Math.min(w * 0.18, h * 0.16);
    ctx.font = '700 ' + size + 'px \"Instrument Serif\", \"Times New Roman\", serif';
    ctx.fillText(label, w / 2, h / 2);
    const tex = viewUniforms.tWordmark.value;
    tex.image = c;
    tex.width = w;
    tex.height = h;
    tex.needsUpdate = true;
  };

  const layout = () => {`,
);

src = src.replace(
  `if (!pointer.placed) {
      pointer.x = width / 2;
      pointer.y = height / 2;
    }
  };`,
  `if (!pointer.placed) {
      pointer.x = width / 2;
      pointer.y = height / 2;
    }
    paintWordmark();
  };`,
);

// Keep animation running while progress may change from scroll
src = src.replace(
  `const busy =
      pointer.inside || wanderOn || presence > 0.002 || bursts.length > 0 || now < trailUntil || (image && intro < 1);
    if (busy && visible) raf = requestAnimationFrame(frame);`,
  `const busy =
      pointer.inside ||
      wanderOn ||
      presence > 0.002 ||
      bursts.length > 0 ||
      now < trailUntil ||
      (image && intro < 1) ||
      true;
    if (busy && visible) raf = requestAnimationFrame(frame);`,
);

fs.writeFileSync('src/components/DitherVeil/DitherVeilScroll.jsx', src);
console.log('ok', src.length);
