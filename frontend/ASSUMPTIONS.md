# Frontend redesign — assumptions & production swaps

## Assumptions
- **Hero image**: placeholder at `public/images/head.jpg`. Swap for a licensed/owned head portrait; keep path via `HERO_HEAD_SRC` in `src/lib/config.js`.
- **Fonts**: Google Fonts — Instrument Serif (display), DM Sans (body), IBM Plex Mono (labels). Self-host for production if preferred.
- **Copy**: adapted from Unobio-style messaging + hackathon underwriting pipeline; not official legal copy.
- **Backend**: `runUnderwriting()` uses mock `MOCK_RESULT` unless `VITE_API_URL` is set (POST `{api}/underwrite`).
- **Old prototype screens** (`InputScreen`, `PromptBar`, dark theme) remain in `src/` but are no longer routed.

## Production checklist
1. Replace `head.jpg` and verify CORS/same-origin for WebGL textures.
2. Point `VITE_API_URL` at the real underwriting API; align payload/response with `runUnderwriting`.
3. Confirm Lighthouse ≥ 85 on desktop after real assets.
4. Legal/brand review of Unobio-adjacent copy before public launch.
