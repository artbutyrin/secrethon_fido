export const MOCK_RESULT = {
  query: 'cardiovascular risk · LPA (Lp(a)) siRNA · Lepodisiran',
  verdict: 'Conditional',
  confidence: 0.72,
  conditions: [
    'A positive CVOT (MACE) is required to lift the condition',
    'Differentiation vs pelacarsen / olpasiran on dosing regimen',
  ],
  whatChanges: [
    'Positive CVOT readout → move toward Invest',
    'Neutral / negative CVOT → Do Not Invest',
    'Weaker convenience differentiation → pressure on rNPV',
  ],
  pos: {
    base: 0.12,
    steps: [
      { label: 'TA base (CV)', delta: 0 },
      { label: 'Genetic support (MR)', delta: 0.08 },
      { label: 'Target engagement', delta: 0.05 },
      { label: 'No CVOT yet', delta: -0.06 },
      { label: 'Crowded class risk', delta: -0.03 },
    ],
    final: 0.16,
  },
  rnpv: { p10: 180, p50: 420, p90: 890, unit: '$M' },
  capital: { toMilestone: '$180–240M', runwayNote: 'Sponsor: Lilly — corporate balance sheet' },
  killRules: [
    { id: 'K5', label: 'Weak differentiation vs SoC/class', status: 'armed' },
    { id: 'K1', label: 'Failed pivotal efficacy', status: 'rebutted' },
  ],
  claims: [
    {
      id: 'C-01',
      text: 'Lp(a) has strong Mendelian randomization support as a causal cardiovascular risk factor.',
      type: 'source',
      direction: 'for',
      stage: 'science',
      source: 'Open Targets / GWAS',
      date: '2024',
      quote: '…genetic evidence supports Lp(a) as a causal risk factor…',
    },
    {
      id: 'C-02',
      text: 'Lepodisiran shows deep Lp(a) reduction in early studies.',
      type: 'source',
      direction: 'for',
      stage: 'clinical',
      source: 'ClinicalTrials.gov / publications',
      date: '2025',
      quote: '…mean Lp(a) reduction exceeded 90% at higher doses…',
    },
    {
      id: 'C-03',
      text: 'There is no completed CVOT for Lepodisiran, so the commercial case stays conditional.',
      type: 'inference',
      direction: 'against',
      stage: 'commercial',
      source: 'derived_from C-02 + class comps',
      date: '2026',
      quote: null,
    },
    {
      id: 'C-04',
      text: 'CMC / IP exclusivity need proprietary data.',
      type: 'unknown',
      direction: 'neutral',
      stage: 'diligence',
      source: 'gap',
      date: null,
      quote: null,
    },
    {
      id: 'C-05',
      text: 'The anti-Lp(a) class is crowded (pelacarsen, olpasiran, zerlasiran).',
      type: 'source',
      direction: 'against',
      stage: 'competition',
      source: 'Tavily / pipeline news',
      date: '2025',
      quote: '…multiple late-stage siRNA and ASO programs…',
      excluded: false,
    },
  ],
  reportMd: `# Investment memo — Lepodisiran (Lp(a) siRNA)

## Verdict
**Conditional** (confidence 0.72). The mechanism is genetically validated, but without a CVOT the verdict stays conditional. [C-01][C-03]

## Scientific thesis
Lp(a) is a causal cardiovascular risk factor by Mendelian randomization. [C-01]

## Translation
Deep biomarker reduction is shown; the link to MACE is unknown until a CVOT. [C-02][C-03]

## Competitive landscape
The class is crowded: pelacarsen, olpasiran, and others. Differentiation is dosing frequency and depth of reduction. [C-05]

## Capital to next milestone
About $180–240M to the CVOT readout (a range). The sponsor balance sheet lowers runway risk.

## Critical unknowns
- CVOT outcome [C-03]
- CMC / exclusivity [C-04]

## Top DD questions
1. What is the CVOT design and statistical power?
2. Is there head-to-head or cross-trial differentiation vs olpasiran?
3. What IP wall remains after competitor LOE?
`,
  steps: [
    { id: 'normalize', label: 'Normalize entities', status: 'done' },
    { id: 'fetch', label: 'Fetch evidence', status: 'done' },
    { id: 'extract', label: 'Extract claims', status: 'done' },
    { id: 'contradict', label: 'Devil’s advocate', status: 'done' },
    { id: 'score', label: 'Score PoS / rNPV', status: 'done' },
    { id: 'report', label: 'Write memo', status: 'done' },
  ],
  trace: [
    { step: 'opentargets', kind: 'api', cost: 0, ms: 420, cache: true },
    { step: 'ctgov', kind: 'api', cost: 0, ms: 610, cache: true },
    { step: 'extract', kind: 'llm', cost: 0.42, ms: 18000, cache: false },
    { step: 'report', kind: 'llm', cost: 0.31, ms: 9000, cache: false },
  ],
};

export const CONFIRM_ENTITIES = {
  disease: {
    resolved: { name: 'Cardiovascular disease risk (Lp(a))', id: 'EFO_0000319', score: 0.91 },
    candidates: [
      { name: 'Hyperlipidemia', id: 'EFO_0003774', score: 0.62 },
      { name: 'Coronary artery disease', id: 'EFO_0001645', score: 0.58 },
    ],
  },
  targets: [
    { name: 'LPA', id: 'ENSG00000198670', role: 'primary', on: true },
  ],
  drug: {
    name: 'Lepodisiran',
    aliases: ['LY3819469'],
    sponsor: 'Eli Lilly',
  },
};
