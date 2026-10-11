# unobio_scoring 2.7

Скоринг для unobio: перевірені правила версії 1.1 плюс виправлення з рев'ю, ворота claims, економіка (rNPV,
Монте-Карло, гроші до наступного етапу) і збирачі даних Orphanet / CMS. Лише стандартна бібліотека Python.

Як підключити, що подавати на вхід і що виходить — у `../docs/scoring_2.1/INTEGRATION.md` (changes since 2.1: `../docs/CHANGES_2.2.md`, `../docs/CHANGES_2.3.md`).
Усі факти — `../docs/scoring_2.1/FACTS.md`, усі правила — `../docs/scoring_2.1/RULES.md`.

```
python -m pytest unobio_scoring/tests -q
python -m unobio_scoring unobio_scoring_examples/sod1_als.claims.json --md report.md
```
