'use client';

import { useEffect, useRef } from 'react';
import { Renderer, Program, Mesh, Triangle, Texture, RenderTarget, Geometry } from 'ogl';

import { waitForWordmarkFont, wordmarkDots } from '../../lib/wordmarkDots';
import './DitherVeil.css';

const DEFAULT_SRC = 'https://images.unsplash.com/photo-1737071371043-761e02b1ef95?q=80&w=1400&auto=format&fit=crop';

const ORDERED = { bayer: 0, noise: 1, lines: 2 };

const KERNELS = {
 atkinson: [
 [1, 0, 1 / 8],
 [2, 0, 1 / 8],
 [-1, 1, 1 / 8],
 [0, 1, 1 / 8],
 [1, 1, 1 / 8],
 [0, 2, 1 / 8]
 ],
 floyd: [
 [1, 0, 7 / 16],
 [-1, 1, 3 / 16],
 [0, 1, 5 / 16],
 [1, 1, 1 / 16]
 ]
};

const MASK_SCALE = 0.5;
const MAX_BURSTS = 4;
const BURST_SECONDS = 1.2;
const HOLD = 1.6;
const INTRO_MS = 1100;

// Scroll timeline (progress 0..1): a particle departs at its delay (0..PARTICLE_DELAY) and
// lands PARTICLE_SPAN later. LANDED_AT must stay above PARTICLE_DELAY + PARTICLE_SPAN.
const PARTICLE_DELAY = 0.5;
const PARTICLE_SPAN = 0.42;
const LANDED_AT = 0.97;

const hexToRgb = hex => {
 let h = String(hex || '').replace('#', '');
 if (h.length === 3) h = h.replace(/./g, c => c + c);
 const n = parseInt(h.slice(0, 6), 16);
 return Number.isNaN(n) ? [0, 0, 0] : [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
};

const fitScale = (w, h, iw, ih, contain) => {
 const ratio = w / h / (iw / ih);
 if (contain) return ratio > 1 ? [ratio, 1] : [1, 1 / ratio];
 return ratio > 1 ? [1, 1 / ratio] : [ratio, 1];
};

const wanderAt = (t, w, h) => [
 w * (0.5 + 0.33 * Math.sin(t * 0.53) + 0.08 * Math.sin(t * 1.31 + 0.6)),
 h * (0.5 + 0.28 * Math.sin(t * 0.71 + 1.1) + 0.07 * Math.cos(t * 1.57))
];

const measureEdge = (context, image) => {
 const size = 32;
 context.canvas.width = size;
 context.canvas.height = size;
 context.drawImage(image, 0, 0, size, size);
 const data = context.getImageData(0, 0, size, size).data;
 const sum = [0, 0, 0];
 const squares = [0, 0, 0];
 let count = 0;
 for (let y = 0; y < size; y++) {
 for (let x = 0; x < size; x++) {
 if (x > 0 && y > 0 && x < size - 1 && y < size - 1) continue;
 for (let c = 0; c < 3; c++) {
 const v = data[(y * size + x) * 4 + c] / 255;
 sum[c] += v;
 squares[c] += v * v;
 }
 count++;
 }
 }
 const matte = [sum[0] / count, sum[1] / count, sum[2] / count];
 const spread =
 matte.reduce((total, mean, c) => total + Math.sqrt(Math.max(0, squares[c] / count - mean * mean)), 0) / 3;
 return { matte, plain: spread < 0.06 };
};

let blueNoise = null;

const getBlueNoise = () => {
 if (blueNoise) return blueNoise;
 const size = 64;
 const n = size * size;
 const wrap = size - 1;
 const taps = [];
 for (let dy = -6; dy <= 6; dy++) {
 for (let dx = -6; dx <= 6; dx++) taps.push(dx, dy, Math.exp(-(dx * dx + dy * dy) / 4.5));
 }
 const energy = new Float32Array(n);
 const on = new Uint8Array(n);
 const splat = (i, sign) => {
 const x = i % size;
 const y = (i - x) / size;
 for (let k = 0; k < taps.length; k += 3) {
 energy[((y + taps[k + 1]) & wrap) * size + ((x + taps[k]) & wrap)] += sign * taps[k + 2];
 }
 };
 const find = (state, highest) => {
 let best = 0;
 let value = highest ? -Infinity : Infinity;
 for (let i = 0; i < n; i++) {
 if (on[i] !== state) continue;
 if (highest ? energy[i] > value : energy[i] < value) {
 value = energy[i];
 best = i;
 }
 }
 return best;
 };
 let seed = 7;
 const random = () => {
 seed = (seed * 16807) % 2147483647;
 return seed / 2147483647;
 };
 const initial = Math.round(n * 0.1);
 for (let placed = 0; placed < initial; ) {
 const i = Math.floor(random() * n);
 if (on[i]) continue;
 on[i] = 1;
 splat(i, 1);
 placed++;
 }
 for (let guard = 0; guard < n; guard++) {
 const cluster = find(1, true);
 on[cluster] = 0;
 splat(cluster, -1);
 const gap = find(0, false);
 on[gap] = 1;
 splat(gap, 1);
 if (gap === cluster) break;
 }
 const seedOn = on.slice();
 const seedEnergy = energy.slice();
 const rank = new Uint16Array(n);
 for (let r = initial - 1; r >= 0; r--) {
 const cluster = find(1, true);
 on[cluster] = 0;
 splat(cluster, -1);
 rank[cluster] = r;
 }
 on.set(seedOn);
 energy.set(seedEnergy);
 for (let r = initial; r < n; r++) {
 const gap = find(0, false);
 on[gap] = 1;
 splat(gap, 1);
 rank[gap] = r;
 }
 const data = new Uint8Array(n * 4);
 for (let i = 0; i < n; i++) {
 const v = Math.floor((rank[i] / n) * 256);
 data[i * 4] = v;
 data[i * 4 + 1] = v;
 data[i * 4 + 2] = v;
 data[i * 4 + 3] = 255;
 }
 blueNoise = data;
 return data;
};

const diffuse = (pixels, cols, rows, kernel, levels, rgb, grade) => {
 const channels = rgb ? 3 : 1;
 const values = new Float32Array(cols * rows * channels);
 for (let i = 0; i < cols * rows; i++) {
 const r = pixels[i * 4] / 255;
 const g = pixels[i * 4 + 1] / 255;
 const b = pixels[i * 4 + 2] / 255;
 if (rgb) {
 values[i * 3] = grade(r);
 values[i * 3 + 1] = grade(g);
 values[i * 3 + 2] = grade(b);
 } else {
 values[i] = grade(0.2126 * r + 0.7152 * g + 0.0722 * b);
 }
 }
 const steps = levels - 1;
 const out = new Uint8Array(cols * rows * 4);
 for (let y = 0; y < rows; y++) {
 const dir = y & 1 ? -1 : 1;
 for (let i = 0; i < cols; i++) {
 const x = dir > 0 ? i : cols - 1 - i;
 const p = y * cols + x;
 for (let c = 0; c < channels; c++) {
 const old = values[p * channels + c];
 const q = Math.min(steps, Math.max(0, Math.round(old * steps))) / steps;
 const err = old - q;
 const byte = Math.round(q * 255);
 if (rgb) out[p * 4 + c] = byte;
 else out[p * 4] = out[p * 4 + 1] = out[p * 4 + 2] = byte;
 for (let k = 0; k < kernel.length; k++) {
 const nx = x + kernel[k][0] * dir;
 const ny = y + kernel[k][1];
 if (nx < 0 || nx >= cols || ny >= rows) continue;
 values[(ny * cols + nx) * channels + c] += err * kernel[k][2];
 }
 }
 out[p * 4 + 3] = 255;
 }
 }
 return out;
};

const bayerAt = (x, y) => {
 const px = x & 7;
 const py = y & 7;
 const v = px ^ py;
 const m = ((v & 1) << 5) | ((py & 1) << 4) | ((v & 2) << 2) | ((py & 2) << 1) | ((v & 4) >> 1) | ((py & 4) >> 2);
 return (m + 0.5) / 64;
};

const thresholdFor = pattern => {
 if (pattern === 'noise') {
 const noise = getBlueNoise();
 return (x, y) => (noise[((y & 63) * 64 + (x & 63)) * 4] + 0.5) / 256;
 }
 if (pattern === 'lines') {
 return (x, y) => {
 const f = (((x + y) % 6) + 0.5) / 6;
 return Math.min(1, Math.max(0, Math.abs(f * 2 - 1) + (bayerAt(x, y) - 0.5) * (2 / 6)));
 };
 }
 return bayerAt;
};

// CPU twin of the shader's ordered dither, so the static frame and the particles share one source.
const ordered = (pixels, cols, rows, levels, rgb, grade, threshold) => {
 const steps = Math.max(levels - 1, 1);
 const quantize = (v, t) => {
 const s = v * steps;
 const base = Math.floor(s);
 return Math.round((Math.min(base + (s - base >= t ? 1 : 0), steps) / steps) * 255);
 };
 const out = new Uint8Array(cols * rows * 4);
 for (let y = 0; y < rows; y++) {
 for (let x = 0; x < cols; x++) {
 const p = y * cols + x;
 const t = threshold(x, y);
 const r = pixels[p * 4] / 255;
 const g = pixels[p * 4 + 1] / 255;
 const b = pixels[p * 4 + 2] / 255;
 if (rgb) {
 out[p * 4] = quantize(grade(r), t);
 out[p * 4 + 1] = quantize(grade(g), t);
 out[p * 4 + 2] = quantize(grade(b), t);
 } else {
 out[p * 4] = out[p * 4 + 1] = out[p * 4 + 2] = quantize(grade(0.2126 * r + 0.7152 * g + 0.0722 * b), t);
 }
 out[p * 4 + 3] = 255;
 }
 }
 return out;
};

const smoothstep = (a, b, x) => {
 const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
 return t * t * (3 - 2 * t);
};

const seeded = seed => () => {
 seed = (seed * 16807) % 2147483647;
 return seed / 2147483647;
};

/**
 * Every lit head cell becomes a particle with a destination dot in the wordmark.
 * Sources and dots are both ordered left→right, so each letter is fed by its own slice of the
 * head and every dot receives at least one particle.
 */
const buildParticles = ({ levels, cols, rows, cell, canvasWidth, canvasHeight, cover, key, word }) => {
 const [cx, cy] = cover;
 const srcX = [];
 const srcY = [];
 const lvl = [];
 for (let y = 0; y < rows; y++) {
 const centerY = (y + 0.5) * cell;
 const v = (centerY / canvasHeight - 0.5) * cy + 0.5;
 if (v < 0 || v > 1) continue;
 for (let x = 0; x < cols; x++) {
 const centerX = (x + 0.5) * cell;
 const u = (centerX / canvasWidth - 0.5) * cx + 0.5;
 if (u < 0 || u > 1) continue;
 const p = (y * cols + x) * 4;
 const r = levels[p] / 255;
 const g = levels[p + 1] / 255;
 const b = levels[p + 2] / 255;
 const bright = Math.max(r, g, b);
 const silhouette = smoothstep(0.04, 0.14, bright);
 if (silhouette <= 0) continue;
 srcX.push(centerX);
 srcY.push(centerY);
 lvl.push(r, g, b, key ? 1 : silhouette);
 }
 }

 const sourceCount = srcX.length;
 const dotCount = word.dots.length / 2;
 if (!sourceCount || !dotCount) return null;

 const count = Math.max(sourceCount, dotCount);
 const random = seeded(1337);
 const origin = Array.from({ length: count }, (_, i) => (i < sourceCount ? i : Math.floor(random() * sourceCount)));

 let minX = Infinity;
 let maxX = -Infinity;
 let minY = Infinity;
 let maxY = -Infinity;
 let sumX = 0;
 let sumY = 0;
 for (let i = 0; i < sourceCount; i++) {
 minX = Math.min(minX, srcX[i]);
 maxX = Math.max(maxX, srcX[i]);
 minY = Math.min(minY, srcY[i]);
 maxY = Math.max(maxY, srcY[i]);
 sumX += srcX[i];
 sumY += srcY[i];
 }
 const spanX = Math.max(maxX - minX, 1);
 const spanY = Math.max(maxY - minY, 1);

 const sourceKey = new Float32Array(count);
 for (let i = 0; i < count; i++) {
 const s = origin[i];
 sourceKey[i] = (srcX[s] - minX) / spanX + ((srcY[s] - minY) / spanY) * 0.25 + random() * 0.12;
 }
 const sourceOrder = Uint32Array.from({ length: count }, (_, i) => i).sort((a, b) => sourceKey[a] - sourceKey[b]);

 let dotMinX = Infinity;
 let dotMaxX = -Infinity;
 for (let i = 0; i < dotCount; i++) {
 dotMinX = Math.min(dotMinX, word.dots[i * 2]);
 dotMaxX = Math.max(dotMaxX, word.dots[i * 2]);
 }
 const dotSpanX = Math.max(dotMaxX - dotMinX, 1);
 const dotKey = new Float32Array(dotCount);
 for (let i = 0; i < dotCount; i++) {
 dotKey[i] = (word.dots[i * 2] - dotMinX) / dotSpanX + (word.dots[i * 2 + 1] / word.height) * 0.02 + random() * 0.02;
 }
 const dotOrder = Uint32Array.from({ length: dotCount }, (_, i) => i).sort((a, b) => dotKey[a] - dotKey[b]);

 const reach = Math.hypot(maxX, maxY) - Math.hypot(minX, minY);
 const nearest = Math.hypot(minX, minY);
 const aSrc = new Float32Array(count * 2);
 const aDst = new Float32Array(count * 2);
 const aLevel = new Float32Array(count * 4);
 const aSeed = new Float32Array(count * 4);
 for (let rank = 0; rank < count; rank++) {
 const i = sourceOrder[rank];
 const s = origin[i];
 const d = dotOrder[Math.min(dotCount - 1, Math.floor((rank * dotCount) / count))];
 aSrc[rank * 2] = srcX[s];
 aSrc[rank * 2 + 1] = srcY[s];
 aDst[rank * 2] = word.dots[d * 2] + word.cell / 2;
 aDst[rank * 2 + 1] = word.dots[d * 2 + 1] + word.cell / 2;
 for (let c = 0; c < 4; c++) aLevel[rank * 4 + c] = lvl[s * 4 + c];
 // Cells nearest the top-left corner (where the name forms) break off first.
 const distance = Math.max(0, Math.hypot(srcX[s], srcY[s]) - nearest) / Math.max(reach, 1);
 aSeed[rank * 4] = PARTICLE_DELAY * (0.78 * Math.min(1, distance) + 0.22 * random());
 aSeed[rank * 4 + 1] = random();
 aSeed[rank * 4 + 2] = random();
 aSeed[rank * 4 + 3] = random();
 }

 return {
 attributes: {
 aSrc: { size: 2, data: aSrc },
 aDst: { size: 2, data: aDst },
 aLevel: { size: 4, data: aLevel },
 aSeed: { size: 4, data: aSeed }
 },
 center: [sumX / sourceCount, sumY / sourceCount],
 dotCell: word.cell
 };
};

const vertex = `#version 300 es
in vec2 position;
in vec2 uv;
out vec2 vUv;
void main() {
 vUv = uv;
 gl_Position = vec4(position, 0.0, 1.0);
}
`;

const maskFragment = `#version 300 es
precision highp float;

uniform sampler2D tPrev;
uniform vec2 uSize;
uniform vec2 uFrom;
uniform vec2 uTo;
uniform float uRadius;
uniform float uSoftness;
uniform float uStrength;
uniform float uFade;
uniform float uHold;

in vec2 vUv;
out vec4 fragColor;

float strokeDistance(vec2 p, vec2 a, vec2 b) {
 vec2 ab = b - a;
 float h = clamp(dot(p - a, ab) / max(dot(ab, ab), 0.0001), 0.0, 1.0);
 return length(p - a - ab * h);
}

void main() {
 vec2 p = vec2(vUv.x, 1.0 - vUv.y) * uSize;
 float trail = max(texture(tPrev, vUv).r - uFade, 0.0);
 float band = max(uRadius * uSoftness, 1.0) * uHold;
 float d = strokeDistance(p, uFrom, uTo);
 trail = max(trail, clamp((uRadius - d) / band, 0.0, 1.0) * uStrength);
 fragColor = vec4(trail, 0.0, 0.0, 1.0);
}
`;

const viewFragment = `#version 300 es
precision highp float;
precision highp int;

uniform sampler2D tImage;
uniform sampler2D tMask;
uniform sampler2D tNoise;
uniform sampler2D tDiffused;
uniform vec2 uResolution;
uniform vec2 uCover;
uniform float uLod;
uniform float uCell;
uniform int uPattern;
uniform int uPalette;
uniform float uLevels;
uniform vec3 uInk;
uniform vec3 uPaper;
uniform vec3 uRimColor;
uniform float uRim;
uniform float uContrast;
uniform float uBrightness;
uniform float uReverse;
uniform float uIntro;
uniform float uHold;
uniform vec3 uMatte;
uniform float uKey;
uniform vec2 uSize;
uniform vec4 uBursts[4];
uniform float uBurstWidth;
uniform float uHide;

in vec2 vUv;
out vec4 fragColor;

float bayer(vec2 cell) {
 ivec2 p = ivec2(mod(cell, 8.0));
 int v = p.x ^ p.y;
 int m = ((v & 1) << 5) | ((p.y & 1) << 4) | ((v & 2) << 2) | ((p.y & 2) << 1) | ((v & 4) >> 1) | ((p.y & 4) >> 2);
 return (float(m) + 0.5) / 64.0;
}

float blueNoise(vec2 cell) {
 return (texelFetch(tNoise, ivec2(mod(cell, 64.0)), 0).r * 255.0 + 0.5) / 256.0;
}

float engraving(vec2 cell) {
 float period = 6.0;
 float f = (mod(cell.x + cell.y, period) + 0.5) / period;
 return clamp(abs(f * 2.0 - 1.0) + (bayer(cell) - 0.5) * (2.0 / period), 0.0, 1.0);
}

vec2 imageUv(vec2 uv) {
 return (uv - 0.5) * uCover + 0.5;
}

float within(vec2 p) {
 vec2 s = step(vec2(0.0), p) * step(p, vec2(1.0));
 return s.x * s.y;
}

vec3 grade(vec3 c) {
 return pow(clamp((c - 0.5) * uContrast + 0.5 + uBrightness, 0.0, 1.0), vec3(1.6));
}

float shockwave(vec2 p) {
 float value = 0.0;
 for (int i = 0; i < 4; i++) {
 vec4 burst = uBursts[i];
 if (burst.w <= 0.0) continue;
 float offset = distance(p, burst.xy) - burst.z;
 float edge = offset > 0.0 ? offset / (uBurstWidth * 0.35) : -offset / uBurstWidth;
 value = max(value, clamp(1.0 - edge, 0.0, 1.0) * burst.w);
 }
 return value;
}

vec3 toned(vec3 c) {
 return uPalette == 1 ? grade(c) : grade(vec3(dot(c, vec3(0.2126, 0.7152, 0.0722))));
}

vec3 quantize(vec3 v, float t) {
 float steps = max(uLevels - 1.0, 1.0);
 vec3 s = v * steps;
 vec3 base = floor(s);
 return min(base + step(vec3(t), s - base), vec3(steps)) / steps;
}

void main() {
 vec2 px = vec2(gl_FragCoord.x, uResolution.y - gl_FragCoord.y);
 vec2 cell = floor(px / uCell);
 vec2 center = (cell + 0.5) * uCell;
 vec2 cellUv = vec2(center.x / uResolution.x, 1.0 - center.y / uResolution.y);

 vec2 sampleUv = imageUv(cellUv);
 float framed = within(sampleUv);
 vec3 level;
 if (uPattern == 3) {
 level = texelFetch(tDiffused, ivec2(cell), 0).rgb;
 } else {
 vec3 c = mix(uMatte, textureLod(tImage, sampleUv, uLod).rgb, framed);
 float t = uPattern == 1 ? blueNoise(cell) : (uPattern == 2 ? engraving(cell) : bayer(cell));
 level = quantize(toned(c), t);
 }

 // Kill sparse fringe noise — only keep cells that belong to the subject silhouette.
 float cellBright = max(level.r, max(level.g, level.b));
 float silhouette = smoothstep(0.04, 0.14, cellBright) * framed;
 vec3 color = mix(uInk, mix(uInk, uPaper, level), max(silhouette, uKey * framed));

 // Cursor reveal disabled — dither only (no silver flashlight under pointer).
 vec2 point = vec2(cellUv.x, 1.0 - cellUv.y) * uSize;
 float mask = max(clamp(texture(tMask, cellUv).r * uHold, 0.0, 1.0), shockwave(point));
 float shown = mix(mask, 1.0 - mask, uReverse);
 // Keep uniforms live so the program still links; weight is always 0.
 color = mix(color, uRimColor, 0.0 * shown);

 vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
 float spread = length((cellUv - 0.5) * aspect) / length(aspect * 0.5);
 float appear = step(spread * 0.72 + bayer(cell + vec2(3.0, 5.0)) * 0.28, uIntro * 1.001);
 color = mix(uInk, color, appear);

 // Once the scroll starts, every lit cell is redrawn by the particle pass instead.
 fragColor = vec4(mix(color, uInk, uHide), 1.0);
}
`;

// One point per lit head cell. At t = 0 it sits exactly on its cell (so the swap from the
// static frame is invisible), at t = 1 exactly on its wordmark dot.
const particleVertex = `#version 300 es
precision highp float;

in vec2 aSrc;
in vec2 aDst;
in vec4 aLevel;
in vec4 aSeed;

uniform vec2 uResolution;
uniform vec2 uLogo;
uniform vec2 uCenter;
uniform float uProgress;
uniform float uSpan;
uniform float uCell;
uniform float uDotCell;
uniform float uScale;
uniform vec3 uInk;
uniform vec3 uPaper;

out vec3 vColor;

void main() {
 float t = clamp((uProgress - aSeed.x) / uSpan, 0.0, 1.0);
 float e = t < 0.5 ? 4.0 * t * t * t : 1.0 - pow(-2.0 * t + 2.0, 3.0) * 0.5;

 vec2 dst = uLogo + aDst;
 vec2 away = aSrc - uCenter;
 away /= max(length(away), 1.0);
 float angle = aSeed.y * 6.2831853;
 vec2 scatter = away * 0.8 + vec2(cos(angle), sin(angle)) * 0.7;
 vec2 ctrl = aSrc + scatter * (90.0 + 260.0 * aSeed.z) * uScale + vec2(-60.0, -140.0) * uScale;

 float u = 1.0 - e;
 vec2 pos = u * u * aSrc + 2.0 * u * e * ctrl + e * e * dst;
 float flight = sin(3.14159265 * t);
 pos += vec2(sin(t * 11.0 + aSeed.w * 40.0), cos(t * 9.0 + aSeed.y * 30.0)) * 16.0 * uScale * flight;

 vec3 base = mix(uInk, mix(uInk, uPaper, aLevel.rgb), aLevel.w);
 vec3 lit = mix(base, uPaper, smoothstep(0.0, 0.25, t));
 vColor = mix(lit, uInk, flight * 0.45 * aSeed.z);

 gl_PointSize = mix(uCell, uDotCell, e);
 gl_Position = vec4(pos.x / uResolution.x * 2.0 - 1.0, 1.0 - pos.y / uResolution.y * 2.0, 0.0, 1.0);
}
`;

const particleFragment = `#version 300 es
precision highp float;

in vec3 vColor;
out vec4 fragColor;

void main() {
 fragColor = vec4(vColor, 1.0);
}
`;

const DitherVeilScroll = ({
 src = DEFAULT_SRC,
 fit = 'contain',
 pattern = 'floyd',
 pixelSize = 2,
 levels = 2,
 palette = 'duotone',
 inkColor = '#120f17',
 paperColor = '#f4f1ea',
 contrast = 1.15,
 brightness = 0,
 revealRadius = 200,
 softness = 0.6,
 linger = 1,
 rimColor = '#a78bfa',
 rim = 0,
 reverse = false,
 wander = false,
 clickBurst = true,
 disableReveal = false,
 progress = 0,
 progressRef = null,
 targetRef = null,
 wordmark = 'unobio',
 className = '',
 style
}) => {
 const containerRef = useRef(null);
 const settingsRef = useRef(null);
 const wakeRef = useRef(() => {});

 useEffect(() => {
 settingsRef.current = {
 fit,
 pattern,
 pixelSize,
 levels,
 palette,
 inkColor,
 paperColor,
 contrast,
 brightness,
 revealRadius,
 softness,
 linger,
 rimColor,
 rim,
 reverse,
 wander,
 clickBurst,
 disableReveal,
 progress,
 wordmark
 };
 wakeRef.current();
 });

 useEffect(() => {
 const container = containerRef.current;
 if (!container) return undefined;

 const reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
 const renderer = new Renderer({ dpr: Math.min(window.devicePixelRatio || 1, 2), alpha: false, antialias: false });
 const gl = renderer.gl;
 const canvas = gl.canvas;
 canvas.style.display = 'block';
 canvas.style.width = '100%';
 canvas.style.height = '100%';
 container.appendChild(canvas);

 const floatMask = renderer.isWebgl2 && !!renderer.getExtension('EXT_color_buffer_float');
 const geometry = new Triangle(gl);

 const dataTexture = () =>
 new Texture(gl, {
 image: new Uint8Array(4),
 width: 1,
 height: 1,
 generateMipmaps: false,
 flipY: false,
 minFilter: gl.NEAREST,
 magFilter: gl.NEAREST
 });
 const imageTexture = new Texture(gl, { minFilter: gl.LINEAR_MIPMAP_LINEAR, magFilter: gl.LINEAR });
 const noiseTexture = dataTexture();
 const diffusedTexture = dataTexture();

 const createMask = (w, h) =>
 new RenderTarget(gl, {
 width: w,
 height: h,
 depth: false,
 type: floatMask ? gl.HALF_FLOAT : gl.UNSIGNED_BYTE,
 internalFormat: floatMask ? gl.RGBA16F : gl.RGBA,
 minFilter: gl.LINEAR,
 magFilter: gl.LINEAR
 });
 const destroyMask = target => {
 gl.deleteFramebuffer(target.buffer);
 gl.deleteTexture(target.texture.texture);
 };
 let masks = [createMask(2, 2), createMask(2, 2)];

 const maskUniforms = {
 tPrev: { value: masks[0].texture },
 uSize: { value: [1, 1] },
 uFrom: { value: [0, 0] },
 uTo: { value: [0, 0] },
 uRadius: { value: 1 },
 uSoftness: { value: 0.5 },
 uStrength: { value: 0 },
 uFade: { value: 1 },
 uHold: { value: HOLD }
 };
 const viewUniforms = {
 tImage: { value: imageTexture },
 tMask: { value: masks[0].texture },
 tNoise: { value: noiseTexture },
 tDiffused: { value: diffusedTexture },
 uResolution: { value: [1, 1] },
 uCover: { value: [1, 1] },
 uLod: { value: 0 },
 uCell: { value: 3 },
 uPattern: { value: 0 },
 uPalette: { value: 0 },
 uLevels: { value: 2 },
 uInk: { value: [0, 0, 0] },
 uPaper: { value: [1, 1, 1] },
 uRimColor: { value: [1, 1, 1] },
 uRim: { value: 0 },
 uContrast: { value: 1 },
 uBrightness: { value: 0 },
 uReverse: { value: 0 },
 uIntro: { value: 0 },
 uHold: { value: HOLD },
 uMatte: { value: [0, 0, 0] },
 uKey: { value: 0 },
 uSize: { value: [1, 1] },
 uBursts: { value: Array.from({ length: MAX_BURSTS * 4 }, () => 0) },
 uBurstWidth: { value: 60 },
 uHide: { value: 0 }
 };
 const particleUniforms = {
 uResolution: viewUniforms.uResolution,
 uInk: viewUniforms.uInk,
 uPaper: viewUniforms.uPaper,
 uLogo: { value: [0, 0] },
 uCenter: { value: [0, 0] },
 uProgress: { value: 0 },
 uSpan: { value: PARTICLE_SPAN },
 uCell: { value: 2 },
 uDotCell: { value: 2 },
 uScale: { value: 1 }
 };
 const program = (fragment, uniforms) =>
 new Program(gl, { vertex, fragment, uniforms, depthTest: false, depthWrite: false });
 const maskMesh = new Mesh(gl, { geometry, program: program(maskFragment, maskUniforms) });
 const viewMesh = new Mesh(gl, { geometry, program: program(viewFragment, viewUniforms) });
 const particleProgram = new Program(gl, {
 vertex: particleVertex,
 fragment: particleFragment,
 uniforms: particleUniforms,
 depthTest: false,
 depthWrite: false
 });
 let particleMesh = null;
 let particleKey = '';
 let levelsData = null;
 let fontReady = false;
 let disposed = false;

 const sampler = document.createElement('canvas');
 const samplerContext = sampler.getContext('2d', { willReadFrequently: true });

 let image = null;
 let introStart = 0;
 let diffusedKey = '';
 let diffusionBlocked = false;
 let width = 1;
 let height = 1;
 let visible = true;
 let raf = 0;
 let last = performance.now();
 let trailUntil = 0;
 let presence = 0;
 let drift = 0;
 const pointer = { x: 0, y: 0, inside: false, fresh: true, placed: false };
 const brush = { x: 0, y: 0, px: 0, py: 0 };
 const bursts = [];

 const updateParticles = (cell, s) => {
 if (!levelsData || !fontReady) return;
 const label = s.wordmark || '';
 const key = [diffusedKey, label, viewUniforms.uKey.value].join('|');
 if (key === particleKey) return;
 particleKey = key;
 if (particleMesh) {
 particleMesh.geometry.remove();
 particleMesh = null;
 }
 if (!label) return;
 const built = buildParticles({
 ...levelsData,
 cell,
 canvasWidth: canvas.width,
 canvasHeight: canvas.height,
 cover: viewUniforms.uCover.value,
 key: viewUniforms.uKey.value > 0,
 word: wordmarkDots(label, renderer.dpr)
 });
 if (!built) return;
 particleMesh = new Mesh(gl, {
 geometry: new Geometry(gl, built.attributes),
 program: particleProgram,
 mode: gl.POINTS,
 frustumCulled: false
 });
 particleUniforms.uCenter.value = built.center;
 particleUniforms.uDotCell.value = built.dotCell;
 };

  const layout = () => {
 width = Math.max(1, container.clientWidth);
 height = Math.max(1, container.clientHeight);
 renderer.setSize(width, height);
 viewUniforms.uResolution.value = [canvas.width, canvas.height];
 maskUniforms.uSize.value = [width, height];
 viewUniforms.uSize.value = [width, height];
 const mw = Math.max(2, Math.round(width * MASK_SCALE));
 const mh = Math.max(2, Math.round(height * MASK_SCALE));
 if (mw !== masks[0].width || mh !== masks[0].height) {
 masks.forEach(destroyMask);
 masks = [createMask(mw, mh), createMask(mw, mh)];
 }
 if (!pointer.placed) {
 pointer.x = width / 2;
 pointer.y = height / 2;
 }
 };

 const updateDiffusion = (cell, s) => {
 if (!image || !samplerContext) return;
 const cols = Math.ceil(canvas.width / cell);
 const rows = Math.ceil(canvas.height / cell);
 const key = [
 s.pattern,
 s.levels,
 s.palette,
 s.contrast,
 s.brightness,
 s.fit,
 cols,
 rows,
 canvas.width,
 canvas.height
 ].join('|');
 if (key === diffusedKey) return;
 diffusedKey = key;
 const [cx, cy] = viewUniforms.uCover.value;
 const iw = image.naturalWidth;
 const ih = image.naturalHeight;
 sampler.width = cols;
 sampler.height = rows;
 samplerContext.imageSmoothingEnabled = true;
 samplerContext.imageSmoothingQuality = 'high';
 const [mr, mg, mb] = viewUniforms.uMatte.value;
 samplerContext.fillStyle = `rgb(${mr * 255}, ${mg * 255}, ${mb * 255})`;
 samplerContext.fillRect(0, 0, cols, rows);
 const sx = (0.5 - 0.5 * cx) * iw;
 const sy = (0.5 - 0.5 * cy) * ih;
 const sw = ((cols * cell) / canvas.width) * cx * iw;
 const sh = ((rows * cell) / canvas.height) * cy * ih;
 const x0 = Math.max(sx, 0);
 const y0 = Math.max(sy, 0);
 const x1 = Math.min(sx + sw, iw);
 const y1 = Math.min(sy + sh, ih);
 if (x1 > x0 && y1 > y0) {
 samplerContext.drawImage(
 image,
 x0,
 y0,
 x1 - x0,
 y1 - y0,
 ((x0 - sx) / sw) * cols,
 ((y0 - sy) / sh) * rows,
 ((x1 - x0) / sw) * cols,
 ((y1 - y0) / sh) * rows
 );
 }
 const grade = v => Math.pow(Math.min(1, Math.max(0, (v - 0.5) * s.contrast + 0.5 + s.brightness)), 1.6);
 const pixels = samplerContext.getImageData(0, 0, cols, rows).data;
 const rgb = s.palette === 'rgb';
 const levels = KERNELS[s.pattern]
 ? diffuse(pixels, cols, rows, KERNELS[s.pattern], s.levels, rgb, grade)
 : ordered(pixels, cols, rows, Math.max(2, Math.round(s.levels)), rgb, grade, thresholdFor(s.pattern));
 levelsData = { levels, cols, rows };
 diffusedTexture.image = levels;
 diffusedTexture.width = cols;
 diffusedTexture.height = rows;
 diffusedTexture.needsUpdate = true;
 };

 const frame = now => {
 raf = 0;
 const s = settingsRef.current;
 if (!s) return;
 const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
 last = now;

 const wanderOn = s.wander && !reducedMotion;
 let targetX = pointer.x;
 let targetY = pointer.y;
 if (!pointer.inside && wanderOn) {
 drift = Math.min(1, drift + dt / 1.2);
 const [wx, wy] = wanderAt(now / 1000, width, height);
 const k = drift * drift * (3 - 2 * drift);
 targetX += (wx - targetX) * k;
 targetY += (wy - targetY) * k;
 } else {
 drift = 0;
 }

 presence += ((pointer.inside || wanderOn ? 1 : 0) - presence) * (1 - Math.exp(-dt / 0.16));

 if (pointer.fresh) {
 brush.x = brush.px = targetX;
 brush.y = brush.py = targetY;
 pointer.fresh = false;
 } else {
 const follow = 1 - Math.exp(-dt / 0.035);
 brush.x += (targetX - brush.x) * follow;
 brush.y += (targetY - brush.y) * follow;
 }

 const burstData = viewUniforms.uBursts.value;
 burstData.fill(0);
 for (let i = bursts.length - 1; i >= 0; i--) {
 if ((now - bursts[i].start) / 1000 >= BURST_SECONDS) bursts.splice(i, 1);
 }
 bursts.forEach((b, i) => {
 const k = Math.max(0, (now - b.start) / 1000 / BURST_SECONDS);
 const reach =
 Math.hypot(Math.max(b.x, width - b.x), Math.max(b.y, height - b.y)) + viewUniforms.uBurstWidth.value;
 burstData[i * 4] = b.x;
 burstData[i * 4 + 1] = b.y;
 burstData[i * 4 + 2] = reach * Math.sin((k * Math.PI) / 2);
 burstData[i * 4 + 3] = 1 - k * k * k;
 });

 const revealOff = !!s.disableReveal || !(s.revealRadius > 0);
 if (!revealOff && presence > 0.002) trailUntil = now + s.linger * 1000 + 150;

 const minFade = floatMask ? 0 : 1.5 / 255;
 const fade = s.linger > 0 ? dt / s.linger : 1;
 maskUniforms.tPrev.value = masks[0].texture;
 maskUniforms.uFrom.value = [brush.px, brush.py];
 maskUniforms.uTo.value = [brush.x, brush.y];
 maskUniforms.uRadius.value = revealOff ? 0 : s.revealRadius * (0.45 + 0.55 * presence);
 maskUniforms.uSoftness.value = revealOff ? 0 : s.softness;
 maskUniforms.uStrength.value = revealOff ? 0 : presence;
 maskUniforms.uFade.value = revealOff ? 1 : Math.max(fade, minFade);
 viewUniforms.uBurstWidth.value = revealOff ? 0 : Math.max(60, s.revealRadius * 0.9);
 renderer.render({ scene: maskMesh, target: masks[1] });
 masks.reverse();
 brush.px = brush.x;
 brush.py = brush.y;

 const cell = Math.max(1, Math.round(s.pixelSize * renderer.dpr));
 if (image) {
 viewUniforms.uCover.value = fitScale(
 canvas.width,
 canvas.height,
 image.naturalWidth,
 image.naturalHeight,
 s.fit === 'contain'
 );
 }
 let patternIndex = KERNELS[s.pattern] ? 0 : ORDERED[s.pattern] ?? 0;
 if (image && !diffusionBlocked) {
 try {
 updateDiffusion(cell, s);
 updateParticles(cell, s);
 patternIndex = 3;
 } catch {
 diffusionBlocked = true;
 }
 }
 if (patternIndex === 1 && noiseTexture.width !== 64) {
 noiseTexture.image = getBlueNoise();
 noiseTexture.width = 64;
 noiseTexture.height = 64;
 noiseTexture.needsUpdate = true;
 }

 const texelsPerPixel = image ? (viewUniforms.uCover.value[0] * image.naturalWidth) / canvas.width : 1;
 viewUniforms.tMask.value = masks[0].texture;
 viewUniforms.uCell.value = cell;
 viewUniforms.uLod.value = Math.log2(Math.max(cell * texelsPerPixel, 1));
 viewUniforms.uPattern.value = patternIndex;
 viewUniforms.uPalette.value = s.palette === 'rgb' ? 1 : 0;
 viewUniforms.uLevels.value = Math.max(2, Math.round(s.levels));
 viewUniforms.uInk.value = hexToRgb(s.inkColor);
 viewUniforms.uPaper.value = hexToRgb(s.paperColor);
 viewUniforms.uRimColor.value = hexToRgb(s.rimColor);
 viewUniforms.uRim.value = Math.min(Math.max(s.rim, 0), 0.95);
 viewUniforms.uContrast.value = s.contrast;
 viewUniforms.uBrightness.value = s.brightness;
 viewUniforms.uReverse.value = s.reverse ? 1 : 0;
 const intro = image ? Math.min(1, (now - introStart) / INTRO_MS) : 0;
 viewUniforms.uIntro.value = 1 - Math.pow(1 - intro, 2);
 const liveProgress = progressRef && progressRef.current != null ? progressRef.current : s.progress ?? 0;
 const progress = Math.min(1, Math.max(0, liveProgress));
 const flying = !!particleMesh && intro >= 1 && progress > 0;
 const landed = flying && progress >= LANDED_AT;
 viewUniforms.uHide.value = flying ? 1 : 0;
 renderer.render({ scene: viewMesh });

 const target = targetRef?.current;
 if (flying && !landed) {
 const scale = canvas.width / width;
 const box = container.getBoundingClientRect();
 const logo = target ? target.getBoundingClientRect() : { left: 24, top: 17 };
 particleUniforms.uLogo.value = [
 Math.round((logo.left - box.left) * scale),
 Math.round((logo.top - box.top) * scale)
 ];
 particleUniforms.uProgress.value = progress;
 particleUniforms.uCell.value = cell;
 particleUniforms.uScale.value = canvas.height / 1000;
 renderer.render({ scene: particleMesh, clear: false });
 }
 // Same frame as the last particle pass, so the fixed logo replaces them without a flicker.
 target?.classList.toggle('is-landed', landed || (!particleMesh && progress >= LANDED_AT));

 // Keep RAF alive so scroll-driven progress updates every frame.
 if (visible) raf = requestAnimationFrame(frame);
 };

 const wake = () => {
 if (raf || !visible) return;
 last = performance.now();
 raf = requestAnimationFrame(frame);
 };
 wakeRef.current = wake;

 const img = new Image();
 img.crossOrigin = 'anonymous';
 img.decoding = 'async';
 img.onload = () => {
 image = img;
 imageTexture.image = img;
 try {
 if (samplerContext) {
 const edge = measureEdge(samplerContext, img);
 viewUniforms.uMatte.value = edge.matte;
 viewUniforms.uKey.value = edge.plain ? 1 : 0;
 }
 } catch {}
 introStart = performance.now();
 wake();
 };
 img.src = src;

 const locate = e => {
 const rect = container.getBoundingClientRect();
 pointer.x = e.clientX - rect.left;
 pointer.y = e.clientY - rect.top;
 pointer.placed = true;
 };
 const onMove = e => {
 locate(e);
 if (!pointer.inside) {
 pointer.inside = true;
 pointer.fresh = true;
 }
 wake();
 };
 const onLeave = () => {
 pointer.inside = false;
 wake();
 };
 const onDown = e => {
 onMove(e);
 if (!settingsRef.current?.clickBurst || (e.pointerType === 'mouse' && e.button !== 0)) return;
 bursts.push({ x: pointer.x, y: pointer.y, start: performance.now() });
 if (bursts.length > MAX_BURSTS) bursts.shift();
 };
 container.addEventListener('pointermove', onMove, { passive: true });
 container.addEventListener('pointerenter', onMove, { passive: true });
 container.addEventListener('pointerdown', onDown, { passive: true });
 container.addEventListener('pointerleave', onLeave, { passive: true });
 container.addEventListener('pointercancel', onLeave, { passive: true });

 const resizeObserver = new ResizeObserver(() => {
 layout();
 wake();
 });
 resizeObserver.observe(container);
 const intersectionObserver = new IntersectionObserver(([entry]) => {
 visible = entry.isIntersecting;
 wake();
 });
 intersectionObserver.observe(container);

 waitForWordmarkFont().then(() => {
 if (disposed) return;
 fontReady = true;
 particleKey = '';
 wake();
 });

 layout();
 wake();

 return () => {
 disposed = true;
 cancelAnimationFrame(raf);
 wakeRef.current = () => {};
 targetRef?.current?.classList.remove('is-landed');
 particleMesh?.geometry.remove();
 resizeObserver.disconnect();
 intersectionObserver.disconnect();
 img.onload = null;
 container.removeEventListener('pointermove', onMove);
 container.removeEventListener('pointerenter', onMove);
 container.removeEventListener('pointerdown', onDown);
 container.removeEventListener('pointerleave', onLeave);
 container.removeEventListener('pointercancel', onLeave);
 gl.getExtension('WEBGL_lose_context')?.loseContext();
 if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
 };
 }, [src]);

 return (
    <div
      ref={containerRef}
      className={`dither-veil${className ? ` ${className}` : ''}`}
      style={style}
    />
  );
};

export default DitherVeilScroll;
