export const DISEASES = [
  { name: 'obesity', aliases: ['obes'] },
  { name: 'Alzheimer disease', aliases: ['alzheimer', 'alzheim'] },
  { name: 'familial hypercholesterolemia', aliases: ['hypercholest', 'fh'] },
  { name: 'type 2 diabetes mellitus', aliases: ['diabetes', 't2d'] },
  { name: 'hypertension', aliases: ['hypertens'] },
  { name: 'non-alcoholic steatohepatitis', aliases: ['mash', 'nash'] },
  { name: 'hidradenitis suppurativa', aliases: ['hidrad'] },
  { name: 'multiple sclerosis', aliases: ['sclerosis'] },
  { name: 'ulcerative colitis', aliases: ['colitis'] },
  { name: 'Crohn disease', aliases: ['crohn'] },
  { name: 'asthma', aliases: ['asthm'] },
  { name: 'hereditary angioedema', aliases: ['angioedema', 'hae'] },
  { name: 'non-small cell lung carcinoma', aliases: ['nsclc', 'lung cancer'] },
  { name: 'Angelman syndrome', aliases: ['angelman', 'ube3a'] },
];

export const MECHANISMS = [
  { name: 'GLP-1 receptor agonist', aliases: ['glp', 'retatrutide'] },
  { name: 'BACE1 inhibitor', aliases: ['bace'] },
  { name: 'anti-PCSK9 antibody', aliases: ['pcsk'] },
  { name: 'LPA siRNA', aliases: ['lpa', 'lp(a)', 'lepodisiran'] },
  { name: 'IL17A inhibitor', aliases: ['il-17', 'il17', 'sonelokimab'] },
  { name: 'KRAS G12C inhibitor', aliases: ['kras', 'g12c'] },
];

export const EXAMPLES = [
  { label: 'PCSK9 + FH', text: 'familial hypercholesterolemia · anti-PCSK9 antibody' },
  { label: 'BACE1 + Alzheimer', text: 'Alzheimer disease · BACE1 inhibitor' },
  { label: 'Lepodisiran', text: 'cardiovascular disease · LPA siRNA · Lepodisiran' },
  { label: 'Sonelokimab + HS', text: 'hidradenitis suppurativa · IL17A inhibitor · Sonelokimab' },
];

function currentFragment(draft) {
  const raw = String(draft || '');
  const idx = Math.max(raw.lastIndexOf('·'), raw.lastIndexOf('|'), raw.lastIndexOf(';'));
  if (idx < 0) return { prefix: '', fragment: raw };
  return { prefix: raw.slice(0, idx + 1), fragment: raw.slice(idx + 1) };
}

/** Ghost completion for the fragment currently being typed. */
export function findAutocomplete(draft, catalog) {
  const { prefix, fragment } = currentFragment(draft);
  const leading = fragment.match(/^\s*/)?.[0] ?? '';
  const token = fragment.trim().toLowerCase();
  if (token.length < 2) return null;
  const hit = catalog.find((item) => item.name.toLowerCase().startsWith(token) && item.name.toLowerCase() !== token);
  if (!hit) return null;
  return {
    full: `${prefix}${leading}${hit.name}`,
    ghost: hit.name.slice(token.length),
  };
}

/** Exact catalog labels are sent as written. Unknown text is passed through. */
export function toSearchTerm(text, catalog) {
  const raw = String(text || '').trim();
  if (!raw) return '';
  const lower = raw.toLowerCase();
  const hit = catalog.find((item) => item.name.toLowerCase() === lower);
  return hit ? hit.name : raw;
}
