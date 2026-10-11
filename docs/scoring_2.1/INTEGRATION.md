# unobio_scoring 2.1 — як підключити

Це окрема версія скорингу для конвеєра unobio. Вона повністю замінює `scoring_engine/` і не потребує ні YAML, ні мережі, ні сторонніх бібліотек.

У цьому файлі описано все потрібне для підключення:
- що подати на вхід;
- що виходить;
- як рахується вердикт;
- як запустити економіку;
- як це вставити в бекенд `unobio-step82`.

---

## 1. Що в архіві

```
unobio_scoring/            сам пакет: його й копіюєте в проєкт
  engine.py                рушій: факти → скоркарта, правила, кластери → вердикт; ворота claims; evaluate()
  config_v11.py            перевірена конфігурація версії 1.1 як дані Python: 86 фактів, 8 пунктів, 51 правило…
  fixes.py                 виправлення з рев'ю поверх 1.1: 6 нових фактів, 4 нові правила, обмеження вердикту
  economics.py             економіка: пацієнти → пік продажів → rNPV, Монте-Карло, гроші до етапу, погляд інвестора
  forecast.py              прогноз для активів без продажів: драбина цін, частка за перевагою, «у що треба повірити»
  constants.py             усі числа економіки з позначкою походження
  needs.py                 які дані потрібні для кожного питання (закриті, KOL, CMC/IP…)
  report.py                картка на один екран і markdown-звіт
  sources/                 збирачі даних для економіки: Orphanet (пацієнти), CMS (ціни), build_market
  tests/                   41 тест, зокрема на реальних уривках Orphanet і CMS
  __main__.py              командний рядок
docs/
  FACTS.md                 УСІ 92 факти: тип, значення, звідки брати, де використовується, питання DD
  RULES.md                 скоркарта, усі 55 правил і 3 обмеження в читабельному вигляді, пороги
  facts_catalog.json       той самий каталог фактів у машинному вигляді (для форм у UI)
examples/
  *.claims.json            три реальні кейси (claims з вашого конвеєра) + ринок + раунд
  out/                     що з них виходить: картка (.card.txt), звіт (.md), повний вихід (.json)
  build_market_from_sources.py   як зібрати ринок з Orphanet + CMS
tools/gen_docs.py          перегенерувати docs/ після змін у правилах
INTEGRATION.md             цей файл
```

**Вимоги:**
- Python 3.10 або новіший, лише стандартна бібліотека.
- `pytest` — для тестів.
- PyYAML — лише якщо захочете завантажити зовнішній YAML для порівняння: `load_config(path)`.

**Перевірка після копіювання:**

```
python -m pytest unobio_scoring/tests -q          # 41 passed
python -m unobio_scoring examples/sod1_als.claims.json
```

---

## 2. Три способи викликати

```python
import unobio_scoring as U

cfg = U.load_config()                 # версія 2.1 = 1.1 + виправлення (кешуйте, це незмінний об'єкт)

# (а) у вас уже є факти
payload = U.evaluate(cfg, {"genetic_support": "mendelian", "moa_clinical_precedent": "approved_related",
                           "approved_therapies_count": 0, "phase": "ph2"})

# (б) у вас claims із джерелами (так працює бекенд): спершу ворота, потім оцінка
got = U.facts_from_claims(cfg, claims)            # facts, used, pending, rejected, conflicts
payload = U.evaluate(cfg, got["facts"], market=market, round_terms=round_terms)

# (в) показати людині
print(U.card(payload))                            # картка на один екран
md = U.markdown(payload, "ALS + SOD1")            # повний звіт
```

Командний рядок: `python -m unobio_scoring case.json [--md out.md] [--json out.json] [--draws 2000] [--v11]`.

Що можна покласти в `case.json`:
- `facts` або `claims`;
- необов'язково `phase`, `market`, `round_terms`, `license_terms`, `title`.

Ключі `market`, що починаються з `_`, ігноруються, тому в них можна писати коментарі про походження.

---

## 3. Вхідні дані

### 3.1 Факти

Факт — це пара `назва: значення` з закритого каталогу на 92 факти. Повна таблиця — у `docs/FACTS.md`. Там для кожного факту вказано:
- тип і допустимі значення;
- рівень: mechanism (хвороба + мішень) чи asset (сам препарат);
- звідки його бере конвеєр зараз;
- які правила він вмикає;
- яке питання для перевірки поставити, якщо його немає.

Правила:
- **Невідомий факт просто не передавайте.** Невідоме ніколи не рахується як мінус. Передати `None` — те саме, що не передати.
- **Типи суворі:**
  - `bool` — лише `True` або `False`;
  - `int` — ціле число в межах;
  - `enum` — рядок зі списку.

  Помилка в назві чи значенні дає `FactError`. Тихих пропусків немає.
- **Суперечливий набір теж дає `FactError` з поясненням.** Наприклад, «oncology = true» разом із «chronic_non_oncology = true».
- **Очевидні наслідки виводяться самі, явно передавати їх не треба:**
  - 0 схвалених препаратів → 0 схвалених з цим механізмом;
  - онкологія → загрозлива для життя хвороба.

  У виході вони позначені як `derived`.
- **6 нових фактів у 2.1:**
  - `approved_same_moa_same_modality_count`;
  - `moa_approved_any_indication`;
  - `acute_indication`;
  - `regulatory_exclusivity_years`;
  - `economics_negative`, `economics_weak`. Ці два рахує модуль економіки; від LLM вони не приймаються.
- **Модальність `protein`** тепер допустима.

**Що конвеєр збирає з відкритих даних (Open Targets, ClinicalTrials.gov):**

| Що | Факти |
|---|---|
| Генетика | `genetic_support` |
| Прецедент механізму | `moa_clinical_precedent` |
| Схвалені препарати | `approved_therapies_count`, `approved_same_moa_count` |
| Конкуренти в Phase 3 | `ph3_same_moa_count` |
| Тип хвороби | `oncology`, `rare_disease` |
| Модальність і досяжність мішені | `modality`, `modality_target_mismatch` |
| Безпека класу | `class_safety_signal`, `class_withdrawal`, `essential_gene` |
| LLM-мітки зупинених досліджень | `moa_failures_efficacy_ph23`, `moa_discontinued_safety_count`, `indication_enrollment_terminations_high` |

Решта фактів — про сам актив. Їх дає людина або дата-рум, а без них система ставить питання для перевірки.

### 3.2 Claims (твердження з джерелами) і ворота

Формат, який уже використовує бекенд:

```json
{"id": "clm_9", "fact": "moa_failures_efficacy_ph23", "value": 2, "origin": "llm",
 "evidence_type": "source", "verified": true, "confirmed": false,
 "quote": "terminated for futility", "doc_ids": ["sponsor:astrazeneca", "sponsor:eisai"],
 "sources": [{"id": "NCT02783573", "drugs": ["LANABECESTAT"], "quote": "futility"}],
 "lower_bound": false}
```

| Поле | Значення |
|---|---|
| `origin` | `user` (людина), `structured` (Open Targets, ChEMBL), `llm`. Пріоритет user > structured > llm |
| `evidence_type` | `source` — твердження з документа; `inference` — висновок моделі, фактом не стає |
| `verified` | Для LLM: цитату знайдено в документі. Без цього claim відкидається |
| `confirmed` | Людина підтвердила (через `POST /runs/{id}/evidence action=confirm`) |
| `quote` | Цитата. Заперечена цитата («not due to lack of efficacy») відкидається |
| `sources[].drugs` | Для лічильників від LLM: ворота **перераховують** різні препарати. Відкидають заперечені цитати, `verified: false` і `stopped_due_to_other_trial: true` |
| `lower_bound` | `true` — кількість неповна, лише нижня межа. Claim чекає на перевірку |

**Як працюють ворота** (`facts_from_claims`):
1. **Перевірка формату.** Назва факту не з каталогу або неправильне значення — claim відкидається.
2. **Що відкидається з LLM:**
   - висновок моделі (`inference`);
   - claim без знайденої цитати;
   - заперечена цитата;
   - твердження про відсутність (0 або `none`);
   - економічні факти.
3. **Структуроване джерело** може стверджувати відсутність лише тоді, коли воно повне. Бекенд так і робить.
4. **Пріоритет джерел.** Вищий пріоритет перемагає. Якщо на одному рівні значення різні, це `conflicts`, і факт лишається невідомим.
5. **Значення від LLM чекає на людину (`pending`), якщо в контексті всіх інших фактів воно:**
   - змінює вердикт, або
   - вмикає чи **вимикає** вбивче правило, сильний мінус або червоний пункт.

   Кілька документів з одного прогону LLM не вважаються незалежними, тож підтвердити може лише людина. Кожен запис у `pending` має `verdict_if_confirmed`.

**Що повертають ворота:**
- `facts` — факти для скорера;
- `used` — `{факт: [id claims]}`, для простежування;
- `pending` — `[{fact, value, claims, tier, reason, verdict_if_confirmed}]`;
- `rejected` — `[{claim, fact, reason}]`;
- `conflicts` — `[{fact, values, claims}]`.

### 3.3 Ринок (`market`) — для економіки

Обов'язкові поля — лише кількість пацієнтів і джерело ціни. Решта має значення за замовчуванням.

| Поле | За замовчуванням | Що це |
|---|---|---|
| `us_patients` | — (обов'язкове) | Людей із хворобою в США, які можуть лікуватися щороку |
| `eligible_share` | 1.0 | Частка тих, для кого препарат, наприклад носії SOD1 ≈ 2% ALS. **Найважливіше ручне поле** |
| `annual_net_price_usd` | Драбина цін (розділ 8а) | Чиста ціна на пацієнта на рік. Якщо задано — береться як є |
| `price_analogues` | — | `{"same_moa": [ціни], "same_indication": [ціни]}` з CMS — сходинки 1 і 2 драбини |
| `price_range` | — | `[низ, верх]` для введеної ціни |
| `us_patients_range` | — | `[низ, верх]` пацієнтів; задає ширину розкиду в Монте-Карло |
| `qaly_gain_per_year` | — | Виграш здоров'я на рік лікування; дає стелю ціни за цінністю ($150 тис. × виграш) |
| `segment` | З фактів | rare / oncology / chronic_biologic / chronic_small / acute: еталонна ціна, час до піку |
| `price_ceiling_usd` | — | Реалістична стеля ціни. Вмикає правило «нереальна ціна» |
| `diagnosis_rate`, `treatment_rate` | 1.0, 1.0 | Частка діагностованих і частка тих, хто лікується |
| `peak_share` | `class_share` × частка за порядком виходу × перевага × штраф за запізнення (розділ 8а) | Пікова частка ринку |
| `class_share` | 0.5 | Частка, яку бере клас механізму |
| `entry_position`, `n_entrants` | З фактів про схвалені препарати й Phase 3 | Котрим виходить препарат і скільки всього учасників |
| `compliance` | 0.7 | Частка оплаченого року (прихильність до лікування) |
| `years_to_peak` | За сегментом: rare 4, oncology 5, chronic 7, acute 4 | Років до піку продажів |
| `ex_us_multiplier` | 0.45 | Продажі поза США як частка від США |
| `medicare_share` | 0.30 | Частка Medicare. Знижка за переговорами 22% з 9-го (мала молекула) або 13-го року |
| `exclusivity_years_after_launch` | З патенту й регуляторної ексклюзивності | Років захисту від генериків після запуску |
| `discount_rate` | 0.10 | Ставка дисконтування |
| `cost_case` | `base` | `base` — витрати за Sertkaya; `worse` — за DiMasi (розраховується завжди окремо) |
| `phase_success` | BIO 2011–2020 | Свої ймовірності переходу між фазами |
| `assumed` | `[]` | **Список полів-припущень.** Якщо там пацієнти, `eligible_share` або ціна, економіка показується, але вердикт не змінює |

`round_terms`:

| Поле | Що це |
|---|---|
| `pre_money_m`, `investment_m` | Оцінка компанії до раунду і сума раунду. Дають розрахунок MOIC і IRR інвестора |
| `dilution_to_exit` | Розмиття частки до виходу, за замовчуванням 0.4 |
| `cash_m` | Гроші компанії. Дає факт `runway_short`: грошей не вистачає до наступного етапу |

`license_terms` — для розрахунку NPV ліцензійної угоди:
- `upfront_m`;
- `milestones_m` (наприклад `{"ph3": 50, "filed": 75, "approval": 150}`);
- `royalty_pct`.

### 3.4 Звідки брати ринок автоматично (`unobio_scoring.sources`)

Обидва джерела я перевірив 9 жовтня 2026: дані реально приходять.

**Пацієнти — Orphanet** (рідкісні хвороби, CC BY 4.0):
- Файл `en_product9_prev.xml` (16 МБ, оновлюється двічі на рік). Завантажте один раз: `orphanet.download(path)`. Є два адреси: orphadata.com і дзеркало на GitHub.
- OrphaCode — з крос-посилань хвороби в Open Targets (`disease.xrefs`, формат `Orphanet:803`): `orphanet.orphacode(xrefs)`.
- `orphanet.us_patients(entry)` вибирає так:
  1. поширеність у США;
  2. медіана підтверджених поширеностей в інших країнах;
  3. поширеність при народженні × народжуваність × 20 років. Цей варіант позначається як припущення.

  Повертає число, діапазон, основу розрахунку і PMID джерел.

**Ціни — CMS Medicare Spending by Drug** (публічне API, без ключа):
- `cms.fetch("Evolocumab")` → рядки Part D і Part B. Назви препаратів беруться зі списку схвалених у хворобі, який конвеєр уже отримує від Open Targets.
- `cms.annual_cost(rows)` → витрати на пацієнта за рік:
  - Part D — валові, тож віднімається 25% знижок виробника (це припущення);
  - Part B — на основі ASP (середня ціна продажу), тобто близько до чистої.
- `cms.price_analogues(costs)` → медіана, діапазон і стеля ціни.
- Обмеження:
  - перший рік продажів препарату може бути неповним;
  - препаратів, яких немає в Medicare, у цих даних немає.

**Збирання:**

```python
from unobio_scoring.sources import build_market, cms, orphanet
orpha = orphanet.load("en_product9_prev.xml")
market, provenance = build_market(facts, orphanet_entry=orpha.get(orphanet.orphacode(xrefs)),
                                  cms_costs=cms.annual_cost([r for g in generics for r in cms.fetch(g)]),
                                  overrides={"eligible_share": 0.02})
```

`build_market` кладе ціни CMS у `price_analogues` (`cms_costs_same_moa` — той самий механізм, `cms_costs` — та сама хвороба). Якщо пацієнтів за Orphanet менше за 200 тис., сегмент стає `rare`.

`provenance` для кожного поля показує, звідки воно: `S` — джерело, `A` — припущення, `user` — ввела людина. Також там є діапазон і посилання. Без кількості пацієнтів `build_market` повертає `None`, і тоді економіка не запускається. Повний приклад, що працює офлайн, — `examples/build_market_from_sources.py`.

**Поширені хвороби** (ожиріння, ішемічна хвороба серця): Orphanet їх не покриває. Варіанти:
- кількість пацієнтів вводить людина;
- LLM витягує її з CDC чи статті з цитатою, через ті самі ворота;
- або це припущення в `assumed`. Тоді економіка видна у звіті, але вердикт не змінює.

---

## 4. Вихід `evaluate()`

Звичайний словник, який можна зберегти в JSON. Повний приклад — `examples/out/sod1_als.json`.

| Ключ | Що всередині |
|---|---|
| `config` | `version` ("2.1"), `sha256`. Зберігайте поруч із вердиктом |
| `verdict` | `decision` (Invest / Conditional / Do Not Invest); `grounds` (kill, negatives, outweighed, insufficient_evidence, science_short, balanced, positive, capped); `grounds_text`; `reason`; `conditions` (що змінити для Invest); `caps` (обмеження, що спрацювали) |
| `score` | `pos`, `neg`, `diff`, `science_pos`, `greens`, `axes` (наука / комерція), `coverage` (скільки пунктів мають дані: усього, рівня механізму, рівня активу) |
| `scorecard` | 8 пунктів: `id`, `name`, `color` (G/Y/R/U), `points`, `level`, `axis`, `basis`, `facts` (що вирішило колір) |
| `rules` | Правила, що спрацювали: `id`, `name`, `tier`, `counted`, `absorbed_by`, `facts` |
| `facts` | `given`, `derived`, `derived_from` (з чого виведено) |
| `reference` | Довідкова ймовірність запуску (не впливає на вердикт): `evidence.range` (Minikel 2024), `stage.loa` (BIO 2021), `caveats` |
| `what_would_change` | Зміни одного факту, які змінюють вердикт: `fact`, `action` (set/hide), `from`, `to`, `verdict_to`, `direction` |
| `dd_questions` | До 10 питань: `question`, `facts`, `critical` (може змінити вердикт), `needs` (які дані потрібні: proprietary experimental data, patient-level clinical data, KOL interviews, regulatory documents, CMC / IP diligence, company financials, trial design documents, public data) |
| `economics` | `None` без ринку. Інакше:<br>• `drives_verdict` — чи впливає на вердикт;<br>• `base` — пік продажів, rNPV, ймовірність успіху, роки до запуску;<br>• `worse_cost_case`;<br>• `monte_carlo` — P10 / P50 / P90 і P(rNPV > 0);<br>• `break_even_price_usd`;<br>• `milestone` — див. нижче;<br>• `investor`, `license` — якщо передано умови;<br>• `plan` — фази;<br>• `assumptions` — усі вхідні;<br>• `facts` — які факти економіка поставила |
| `economics.forecast` | Прогноз без продажів:<br>• `segment`;<br>• `price` (значення, діапазон, сходинка, основа);<br>• `peak_share` (значення, клас переваги, як пораховано);<br>• `years_to_peak`, `sigma`;<br>• `tornado` — що найсильніше рухає rNPV;<br>• `break_even` — яке мінімальне значення кожного чинника дає rNPV = 0;<br>• `scenarios` — bear / base / bull як реальні точки P10 / P50 / P90 Монте-Карло;<br>• `required_peak_for_post_money_m` — який пік продажів виправдовує оцінку раунду |
| `economics.driver_questions` | Два питання про головні чинники економіки. Ставляться першими в `dd_questions` |
| `economics_note` | Чому економіка не рахувалась або не вплинула на вердикт |

Що є в `economics.milestone`:
- `capital_to_milestone_m` — діапазон Sertkaya–DiMasi;
- `years_to_milestone`;
- `p_milestone_success`;
- `capital_to_approval_m`;
- `expected_capital_to_approval_m` — з урахуванням зупинки після провалу;
- `financing_rounds_to_approval`;
- `rnpv_after_milestone_m` — вартість програми після етапу;
- `runway_short` — якщо дано `cash_m`.

Пункти скоркарти й правила мають `facts`. Бекенд додає до них `claim_ids` через `evidence.trace`. Так з'являється ланцюжок, який вимагає бриф: вердикт → пункт або правило → claim → джерело.

---

## 5. Як рахується вердикт

Повний перелік — у `docs/RULES.md`.

1. **Скоркарта з 8 пунктів:**
   - потреба;
   - генетика;
   - прецедент механізму;
   - історія показання;
   - ланцюжок трансляції;
   - клінічний ефект;
   - дизайн досліджень;
   - регуляторний шлях.

   Бали: зелений +1, сильний зелений +2, червоний −2.
2. **Правила.**
   - Вбивче правило дає Do Not Invest одразу.
   - Сильне дає −2, попередження −1.
   - У кожному кластері рахується лише найсильніше правило.
3. **Пороги:**
   - мінусів ≥ 4 → DNI;
   - нетто ≥ 2, наукових плюсів ≥ 2 і є доказ механізму → Invest;
   - нетто ≤ 0 → DNI;
   - між ними → Conditional або DNI. Без доказу механізму — DNI «через брак підтвердження».
4. **Обмеження до Conditional** (лише коли вийшов Invest):
   - `runway_short` — грошей не вистачає до наступного етапу;
   - `economics_negative` — P(rNPV > 0) < 10%;
   - me-too без доведеної переваги.

   Причину видно в `verdict.caps`, а `grounds = "capped"`.

**Що змінено порівняно з 1.1** (деталі — у `unobio_scoring/fixes.py`):
- **me-too:** сильний мінус + обмеження до Conditional. Вбивче лише тоді, коли перевагу перевірили й спростували. Рахується з урахуванням класу модальності.
- **Немає патенту:** вбивче лише при регуляторній ексклюзивності менше 5 років.
- **«Механізм спростовано»:** також тоді, коли механізм ніде не схвалений.
- **Ворота claims:** див. розділ 3.2.

**Перемикачі:**
- `load_config(fixes=False)` — рівно версія 1.1.
- `load_config(asset_data_for_invest=True)` — Invest лише за наявності даних про сам препарат. **За замовчуванням вимкнено**, бо інакше на відкритих даних Invest не буває ніколи.

---

## 6. Як вихід закриває звіт із брифу

| Розділ брифу | Звідки брати |
|---|---|
| Recommendation | `verdict.decision`, `grounds_text`, `reason`, `caps`, `conditions`; довідково `reference` |
| Scientific thesis | Пункти `human_genetics`, `clinical_precedent`, `indication_track_record` і їхні claims; правила механізму |
| Human translation thesis | Пункти `translation_chain`, `clinical_effect`. Якщо вони U (невідомо) — це «відсутні ланки» і питання з `needs = proprietary experimental data` |
| Clinical development plan | `economics.plan` (фази, тривалості, ймовірності, витрати); пункти `trial_design`, `regulatory_path` |
| Competitive landscape | Claims про схвалені препарати й Phase 3; правила me-too, late_entry, ph3_competitors |
| Commercial opportunity | `economics.base` (пік продажів), `monte_carlo`, `break_even_price_usd`, `assumptions` + `provenance` з `build_market` |
| Capital to next milestone | `economics.milestone`, `investor`, `license` |
| Key risks | `rules`, де `counted = true`; червоні пункти; `caps` |
| Critical unknowns | Пункти з кольором U, `pending`, `conflicts`, `economics_note` |
| 5–10 diligence questions | `dd_questions` (з `critical` і `needs`) |
| Sources | `facts` → `used` → claims → `sources` (робить бекенд) |

Розділи Commercial opportunity і Capital to next milestone краще писати кодом із `economics`, а не LLM. Тоді числа беруться лише з розрахунку, і їх видно з позначками [S] / [A] / [D].

---

## 7. Підключення до бекенду `unobio-step82`

**Крок 1. Скопіювати** теку `unobio_scoring/` у корінь репозиторію (поруч із `backend/`).

**Крок 2. Одна точка імпорту.** Створіть `backend/app/scorer.py`:

```python
import os
if os.environ.get("UNOBIO_SCORER", "v2") == "v1":
    from scoring_engine.scoring import FactError, check_facts, evaluate, fact_catalog, facts_from_claims, load_config
    from scoring_engine.scoring.engine import facts_in
else:
    from unobio_scoring import FactError, check_facts, evaluate, fact_catalog, facts_from_claims, facts_in, load_config
```

Потім у `api.py`, `evidence.py`, `pipeline.py` і тестах (`step1_score.py`, `test_step1.py`, `test_step2.py`, `test_step4.py`) замініть `from scoring_engine.scoring import ...` на `from backend.app.scorer import ...`. У `evidence.py` `facts_in` теж береться звідти.

**Крок 3. Ринок у запуск.** У `api.RunIn` додайте необов'язкові поля:
- `market: dict | None`;
- `round_terms: dict | None`.

Збережіть їх у run, як `phase`. Далі в `pipeline.score_claims`:

```python
def score_claims(claims, market=None, round_terms=None):
    got = facts_from_claims(CFG, claims)
    payload = evaluate(CFG, got["facts"], market=market, round_terms=round_terms)
    return {"used": got["used"], "rejected": got["rejected"], "pending": got["pending"],
            "conflicts": got["conflicts"], "result": trace(CFG, payload, got["used"])}
```

**Крок 4. Ринок автоматично.** У `pipeline.analyze` після збирання даних:
- OrphaCode: `orphanet.orphacode(norm["disease"]["xrefs"])`;
- назви схвалених препаратів: з `sources` claim `approved_therapies_count`. Для me-too беріть `approved_same_moa_count`;
- далі `cms.fetch` → `build_market`. Ручні поля з запиту передайте як `overrides`.

Орфанет завантажте один раз при старті, наприклад у `backend/data/orphanet/`. Відповіді CMS кешуйте так само, як Open Targets.

**Крок 5. Звіт.** У `backend/app/report.py` розділи `commercial_opportunity` і `capital_to_next_milestone` заповнюйте кодом (`kind: "scorer"`) з `payload["result"]["economics"]`, як у `unobio_scoring/report.py → markdown`. До питань у `diligence_questions` додайте текст із `q["needs"]`.

**Крок 6. Тести бекенду,** які зміняться, бо змінилася поведінка (усе навмисно):
- PCSK9: Do Not Invest → Conditional (me-too тепер сильний мінус);
- BACE1: лічильники від LLM тепер `pending`, поки їх не підтвердить людина. Після підтвердження → вбивче правило `mechanism_refuted`;
- «другий спонсор підтверджує» → тепер підтверджує лише людина;
- `/health`: версія "2.1";
- `/facts`: 92 факти.

Я вже прогнав це на вашому `unobio-step82`: після цих правок проходять 122 тести бекенду.

**Повернути старий рушій:** `UNOBIO_SCORER=v1`.

---

## 8. Економіка: що всередині і де межі

- **Пацієнти → продажі.** `us_patients × eligible_share × diagnosis × treatment × peak_share × compliance × ціна` дає пік продажів у США. Наростання — крива типу Robey до піку. Поза США — `ex_us_multiplier`. Після закінчення ексклюзивності лишається 10–35% продажів, залежно від модальності. Medicare: знижка з 9-го або 13-го року.
- **Розробка.** Фази від поточної до подання на схвалення. Ймовірності — BIO 2011–2020, з поправкою на генетику (Minikel 2024, логіт-шкала). Витрати: Sertkaya (база) і DiMasi (гірший варіант). Програма зупиняється після провалу, тому дерево рішень має відмову від продовження.
- **Гроші.** Податок 21% з урахуванням попередніх збитків. Собівартість — за модальністю, SG&A — 25%.
- **Невизначеність.** Монте-Карло на пацієнтах, ціні, частці й витратах: P10 / P50 / P90 і P(rNPV > 0). Генератор випадкових чисел детермінований (`seed`).
- **Вплив на вердикт.** Лише коли пацієнти й ціна не в `assumed`:
  - P(rNPV > 0) < 10% → сильний мінус + обмеження до Conditional;
  - P50 < 0 → попередження;
  - ціна беззбитковості вища за стелю → мінус;
  - брак грошей → обмеження.
- **Межі моделі:**
  - числа в `constants.py` з позначкою [recalled] звірте з першоджерелами;
  - економіка не перевірена на реальних результатах;
  - малі популяції дають дуже малий пік продажів. Для SOD1-ALS виходить ≈ $5 млн у США. Перевірте `eligible_share` і ціну.

---

## 8а. Прогноз для активів, які ще нічого не продають (`forecast.py`)

Уся економіка — це прогноз майбутнього: від поточної фази через ймовірності успіху до продажів після запуску.
CMS дає не продажі нашого активу, а ціни вже схвалених препаратів, які служать орієнтиром.

**1. Драбина ціни.** Береться перша доступна сходинка; кожна наступна менш точна і має ширший розкид у Монте-Карло.

| Сходинка | Звідки | Розкид σ |
|---|---|---|
| user | Ціну ввели (`annual_net_price_usd`) | 0.25 |
| same_moa | CMS: препарати з тим самим механізмом, у будь-якій хворобі | 0.25 |
| same_indication | CMS: препарати від цієї хвороби | 0.35 |
| reference | Еталон за сегментом [A] | 0.6 |

Еталонні ціни (P25 / P50 / P75 на рік, у доларах 2024):
- рідкісні: $102 300 / $220 200 / $442 300 — дані Rome 2008–2021, переведені в долари 2024;
- онкологія: $120 тис. / $200 тис. / $300 тис. [A];
- хронічні біологічні: $20 тис. / $40 тис. / $70 тис. [A];
- хронічні малі молекули: $3 тис. / $8 тис. / $20 тис. [A];
- гострі, за курс: $0,5 тис. / $3 тис. / $15 тис. [A].

Ціна з еталону — це припущення, тому вона не впливає на вердикт. Стеля за цінністю — $150 тис. × `qaly_gain_per_year`.

**2. Частка ринку з урахуванням переваги:**

`class_share × частка за порядком виходу × множник переваги × штраф за запізнення` (не більше 0,8).

Множники переваги:

| Клас | Множник | Коли |
|---|---|---|
| Перший у класі | 1.0 | |
| Кращий у класі | 1.6 | Перевага в ефективності чи безпеці доведена даними |
| Заявлена перевага | 1.2 | Перевага в ефективності чи безпеці заявлена, але не доведена |
| Зручність | 0.9 | |
| Ціна | 1.0 | Ціна × 0.85 |
| Без переваги | 0.6 | Або перевагу спростовано |
| Невідомо | 0.8 | |

Штраф за запізнення: −8% за кожен рік відставання від першого в класі понад 2 роки, але не нижче ×0.5. Усі множники — припущення [A], їх треба відкалібрувати.

**3. Час до піку за сегментом:**
- рідкісні — 4 роки;
- онкологія — 5;
- хронічні — 7;
- гострі — 4.

**4. «У що треба повірити»:**
- **Чутливість.** Кожен чинник окремо від P10 до P90: пацієнти, ціна, частка, ймовірність успіху (×0,7–1,3), витрати (×0,7–1,5), час до піку (±2 роки). Показується, хто найсильніше рухає rNPV і чи змінює він знак.
- **Беззбитковість.** Скільки потрібно пацієнтів, якої ціни, частки чи ймовірності схвалення, щоб rNPV = 0 (кожен чинник окремо, решта як є).
- **Оцінка раунду.** Який пік продажів у США виправдовує оцінку компанії після раунду.
- **Сценарії.** Реальні точки Монте-Карло на рівні P10 / P50 / P90 разом із множниками, які їх дали. Це не всі чинники в крайніх значеннях одночасно: такої комбінації не буває (знахідка F01 рев'ю).
- **Питання.** Два головні чинники автоматично стають першими питаннями для перевірки.

**Що далі (не зроблено):**
- калібрування на реальних запусках: прогноз «до запуску» проти фактичних витрат Medicare з CMS. Тоді σ і множники стануть виміряними, а не припущеннями;
- дерево виходів для інвестора: ліцензія, продаж, власний запуск;
- окрема модель для разових терапій (генна, клітинна). Зараз вони рахуються як річна ціна, і це їх спотворює.

## 9. Перевірка

- `python -m pytest unobio_scoring/tests -q`: 41 тест.
- **Сумісність з 1.1:**
  - з `fixes=False` пакет проходить 283 з 286 старих тестів `scoring_engine`. Три розбіжності навмисні: дві через хеш конфігурації, одна — підтвердження другим документом;
  - на 14 770 парах датасету Minikel 2024 вердикти й бали збіглися з 1.1 у 100% пар.
- **Точність на датасеті** (13 030 пар, лише факти рівня механізму):
  - Invest — 15,1% пар, із них дійшли до ринку 33,2% при базі 11,7%;
  - Invest проти решти: збалансована точність 65,8%, проста точність 83,2%;
  - AUC бала 0,747.

  Це результат на тих самих даних, на яких підбирали правила. На незайманій підвибірці AUC 0,551. Економіку й ворота на цьому датасеті перевірити неможливо, бо там немає таких фактів.

---

## 10. Типові помилки

| Повідомлення | Причина | Що робити |
|---|---|---|
| `FactError: Unknown fact 'x'` | Назви немає в каталозі | Подивіться `docs/FACTS.md` |
| `FactError: x: expected ...` | Неправильний тип чи значення | `True`, а не `"true"`; enum — зі списку |
| `FactError: Contradictory facts: ...` | Факти суперечать один одному | Бекенд віддає це як 422 |
| `economics_note: market.us_patients missing` | Немає кількості пацієнтів | Orphanet, ручне введення або `assumed` |
| `economics_note: ... not used in the verdict` | Пацієнти чи ціна — припущення | Дайте джерело або залиште так: у звіті економіка буде видна |
| `ConfigError` | Помилка в `fixes.py` чи власних правилах | Рушій навмисно падає голосно, без тихих пропусків |
