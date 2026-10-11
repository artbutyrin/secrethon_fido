# Hero → «unobio» (particle wordmark)

Every lit dither cell of the head is a real particle (`gl.POINTS`). On scroll each one flies
along its own arc into one dot of the wordmark, so the name is built only from head particles.
When they have landed, the fixed `FixedParticleLogo` takes over in the same frame (identical
pixels) and stays for the rest of the page.

## Where to edit

### 1. Timing
**File:** `src/components/DitherVeil/DitherVeilScroll.jsx` (top constants)

| Knob | Effect |
|------|--------|
| `PARTICLE_DELAY` | Spread of departure times (0..this). Cells nearest the top-left leave first |
| `PARTICLE_SPAN` | Flight duration of one particle, in scroll progress |
| `LANDED_AT` | Handoff to the fixed logo. Keep above `PARTICLE_DELAY + PARTICLE_SPAN` |

### 2. Flight shape
**Same file → `particleVertex`**: `ctrl` (how far particles burst out before curving to the name),
the `16.0 * uScale` wobble, and the ease `e`.

### 3. Particle → letter mapping
**Same file → `buildParticles()`**: sources and wordmark dots are both sorted left→right
(`sourceKey`, `dotKey`). Raise the `random() * 0.12` jitter for a more chaotic swarm.

### 4. Size / position of «unobio»
**File:** `src/lib/wordmarkDots.js` (`WORDMARK_BOX`, font size) — shared by the particles and
the fixed logo. Position: `src/components/FixedParticleLogo.css` (`top`, `left`); the particles
read the logo position from the DOM every frame.

### 5. Scroll distance of the whole effect
**File:** `src/pages/LandingPage.css` → `--hero-run`. Larger = slower, more visible flight.
