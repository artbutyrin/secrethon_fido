# Alzheimer disease + BACE1: Do Not Invest

Run `run_27fadc1864`, verdict version 1, generated 2026-10-10T13:33:33+00:00. LLM: keyword.

## Recommendation

INCOMPLETE RUN: some sources failed (uniprot: failed (SourceError: uniprot: offline and no cached response for https:; pubmed: failed (SourceError: pubmed: offline and no cached response for https://; aact: failed (SourceError: ctgov: offline and no cached response for https://cli). The verdict below rests on the data that arrived; rerun before relying on it.

Recommendation: Do Not Invest. Grounds: a kill rule fired. Scorer: a kill rule fired. Pluses 0, minuses 4; data for 4 of 8 scorecard items.

Question answered: is the thesis investable (target + mechanism + indication). Invest here means the thesis is worth backing; it does not price a round and does not need data on a specific asset. Give round terms (pre-money, investment, cash) to ask about a round.

Reference only, not part of the verdict: 6%–8% of historical target–disease pairs with similar mechanism evidence ('No genetics, precedent or strong indication track record') reached launch, counting from Phase I (Minikel et al. 2024).


## Scientific thesis

Input: direction of action is inhibit. [clm_27fadc1864_1]

No qualifying genetic evidence links BACE1 to Alzheimer disease (0 evidence rows read), although the disease has genetic evidence for other targets (e.g. APP, PSEN1, PSEN2). [clm_27fadc1864_3]

No drug with the same mechanism (BACE1 inhibit) is approved for any disease (4 drugs on BACE1 checked). [clm_27fadc1864_5]

BACE1 is not a common essential gene. [clm_27fadc1864_8]

2 drugs with the same mechanism (BACE1 inhibit) stopped Phase 2/3 trials in Alzheimer disease for lack of efficacy: Elenbecestat (NCT02956486: "no evidence of potential efficacy"); Lanabecestat (NCT02245737: "primary endpoint"). [Confirmed automatically: 2 independent sources, quotes found by code and checked a second time.] [clm_27fadc1864_11]


## Human translation thesis

Link 1, Molecular effect (target perturbation changes the disease phenotype): asset: unknown; target: unknown; to settle: Is there a response in a relevant animal model, and who reproduced it?.

Link 2, Human exposure at the site of action: asset: unknown; class: unknown; to settle: Is effective exposure reachable safely in humans, and does the drug reach the right tissue?.

Link 3, Target engagement in humans: asset: unknown; class: unknown; to settle: Has target engagement been shown in relevant human tissue?.

Link 4, Biological response (pharmacodynamic biomarker) in humans: asset: unknown; class: unknown; to settle: Does a pharmacodynamic biomarker change in humans, and does it predict clinical benefit?.

Link 5, Patient benefit: asset: unknown; class: not shown for 2 drug(s) that failed for efficacy; to settle: What are the results of the asset's own trials in this indication: were primary endpoints met, were there failures?. [clm_27fadc1864_11]


## Clinical development plan

Alzheimer disease is not in the oncology therapeutic area. [clm_27fadc1864_2]

32 other target(s) have a known Phase 3 outcome in Alzheimer disease: 3 with an approved drug, 29 without. [clm_27fadc1864_9]

3 of 32 other targets with a known Phase 3 outcome in Alzheimer disease reached approval (9%). [clm_27fadc1864_10]


## Competitive landscape

0 drugs with the same mechanism (BACE1 inhibit) are approved for Alzheimer disease. [clm_27fadc1864_4]

0 drugs with the same mechanism have an active Phase 3 trial in Alzheimer disease. [clm_27fadc1864_6]

7 drugs are approved for Alzheimer disease: Aducanumab, Donanemab, Donepezil, Galantamine, Lecanemab, Memantine, Rivastigmine. [clm_27fadc1864_7]


## Commercial opportunity

Economics not run: no market inputs. The verdict rests on the scientific and clinical evidence alone; a market cannot lower or confirm it.

Orphanet epidemiology file not found (backend/data/orphanet/en_product9_prev.xml): no sourced patient count. Download it with `python -m backend.app.market --download` or enter market.us_patients.

CMS prices not read: cms: offline and no cached response for https://data.cms.gov/data-api/v1/dataset/7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b/data {'filter[Gnrc_Name]': 'Aducanumab', 'size': 50}

Alzheimer disease is not in the oncology therapeutic area. [clm_27fadc1864_2]

7 drugs are approved for Alzheimer disease: Aducanumab, Donanemab, Donepezil, Galantamine, Lecanemab, Memantine, Rivastigmine. [clm_27fadc1864_7]


## Capital to next milestone

Value after the milestone, rNPV and the round view need a patient count (Orphanet or market.us_patients).


## Key risks

Rule fired, kill rule: Mechanism refuted. [clm_27fadc1864_5, clm_27fadc1864_11]

Rule fired, strong minus: One mechanism failure for efficacy. [clm_27fadc1864_11]

Rule fired, strong minus: Two or more programs on this target discontinued for safety. [clm_27fadc1864_12]

Rule fired, note: Neither genetics nor a target precedent in a related disease (shown for context, not counted: absence of evidence is not negative evidence). [clm_27fadc1864_3, clm_27fadc1864_5]

2 drugs with the same mechanism (BACE1 inhibit) had trials stopped for safety: Atabecestat (NCT02569398: "liver enzymes"); Elenbecestat (NCT02322021: "safety"). [Confirmed automatically: 2 independent sources, quotes found by code and checked a second time.] [clm_27fadc1864_12]


## Critical unknowns

Missing links in the translation chain for this asset: link 1, link 2, link 3, link 4, link 5. Public data can show them only for other drugs of the mechanism; for this asset they need its own data (Phase 1 PK/PD, receptor occupancy, biomarkers) from the company.

No data for these scorecard items: Translation chain, Clinical effect shown, Trial design, Regulatory path. They count as unknown, not as negative.


## Diligence questions

- Is there a response in a relevant animal model, and who reproduced it?
- Is effective exposure reachable safely in humans, and does the drug reach the right tissue?
- Does a pharmacodynamic biomarker change in humans, and does it predict clinical benefit?
- Has target engagement been shown in relevant human tissue?
- Does the path rely on accelerated approval, and has a confirmatory trial started?
- What were the interactions with the FDA: advisory committee votes, letters on data quality or integrity?
- Are patients selected by a biomarker, and is there a validated test for it?
- Who manufactures the drug, and what is the status of the last FDA inspection?
- Did the asset receive an FDA complete response letter, and what is the verbatim reason?
- How does the asset differ from approved drugs of the same mechanism, and what data support it?

## Sources

- Open Targets disease: MONDO_0004975 — https://platform.opentargets.org/disease/MONDO_0004975 [clm_27fadc1864_2]
- Open Targets evidence — https://platform.opentargets.org/evidence/ENSG00000186318/MONDO_0004975 [clm_27fadc1864_3]
- Open Targets target drugs: ENSG00000186318 — https://platform.opentargets.org/target/ENSG00000186318 [clm_27fadc1864_4]
- Open Targets drug: ADUCANUMAB — https://platform.opentargets.org/drug/CHEMBL3039540 [clm_27fadc1864_7]
- Open Targets drug: DONANEMAB — https://platform.opentargets.org/drug/CHEMBL4297245 [clm_27fadc1864_7]
- Open Targets drug: DONEPEZIL — https://platform.opentargets.org/drug/CHEMBL1678 [clm_27fadc1864_7]
- Open Targets drug: GALANTAMINE — https://platform.opentargets.org/drug/CHEMBL1555 [clm_27fadc1864_7]
- Open Targets drug: LECANEMAB — https://platform.opentargets.org/drug/CHEMBL3833321 [clm_27fadc1864_7]
- Open Targets drug: MEMANTINE — https://platform.opentargets.org/drug/CHEMBL1699 [clm_27fadc1864_7]
- Open Targets drug: RIVASTIGMINE — https://platform.opentargets.org/drug/CHEMBL636 [clm_27fadc1864_7]
- clinical trial: NCT02956486 — https://clinicaltrials.gov/study/NCT02956486 [clm_27fadc1864_11]
- clinical trial: NCT02245737 — https://clinicaltrials.gov/study/NCT02245737 [clm_27fadc1864_11]
- clinical trial: NCT02783573 — https://clinicaltrials.gov/study/NCT02783573 [clm_27fadc1864_11]
- clinical trial: NCT02972658 — https://clinicaltrials.gov/study/NCT02972658 [clm_27fadc1864_11]
- clinical trial: NCT02569398 — https://clinicaltrials.gov/study/NCT02569398 [clm_27fadc1864_12]
- clinical trial: NCT02322021 — https://clinicaltrials.gov/study/NCT02322021 [clm_27fadc1864_12]
