"""Numeric constants of the economics module. Every value carries a provenance note.

Tags: [recalled] = from a published source, reproduced from memory/review notes; [assumption] = model choice,
change freely; [derived] = computed from the other constants.
"""
from __future__ import annotations

# Verdict thresholds, weights, scorecard and rules live in config_v11.py (+ fixes.py), not here.

# ---------------------------------------------------------------------------
# Probability of success (BIO / Informa / QLS, "Clinical Development Success Rates 2011–2020") [recalled]
# Phase transition probabilities: ph1->ph2, ph2->ph3, ph3->filing, filing->approval.
# Preclinical->ph1 is NOT in BIO; 0.6 is an [assumption].
# ---------------------------------------------------------------------------
PRECLINICAL_TO_PH1 = 0.60
BIO_SUCCESS = {
    "all":      {"ph1": 0.520, "ph2": 0.289, "ph3": 0.578, "filed": 0.906},
    "oncology": {"ph1": 0.488, "ph2": 0.246, "ph3": 0.477, "filed": 0.920},
}
# Phase durations, years (BIO 2011–2020 averages [recalled]; preclinical [assumption]).
DURATION_Y = {"preclinical": 1.5, "ph1": 2.3, "ph2": 3.6, "ph3": 3.3, "filed": 1.3}

# Cost of each phase, USD million, 2024 dollars (2.2, review patch 01 / F09 / F17).
# base  = Sertkaya et al. (ERG for ASPE, 2014) cost of ONE trial per phase, average over therapeutic areas, nominal
#         2004-2012 dollars (mid-point 2008) [recalled] x trials per phase per application (Sertkaya & Berger, ERG for
#         ASPE 2024, table 5: 1.71 / 1.52 / 2.66 [sourced, review]) x CPI-U 2008->2024 1.457 [sourced, review: BLS
#         215.303 -> 313.689]; plus company overhead per year of the phase (added in economics.phase_plan).
# worse = DiMasi et al. 2016 out-of-pocket cost per compound entering the phase, 2013 dollars [sourced, review C2]
#         x CPI-U 2013->2024 1.347 [sourced, review: 232.957 -> 313.689].
SERTKAYA_TRIAL_M = {"ph1": 4.0, "ph2": 13.0, "ph3": 20.0}       # per trial, nominal ~2008 USD [recalled]
TRIALS_PER_PHASE = {"ph1": 1.71, "ph2": 1.52, "ph3": 2.66}       # [sourced, review patch 01]
CPI_2008_TO_2024 = 1.457                                         # [sourced, review patch 01]
CPI_2013_TO_2024 = 1.347                                         # [sourced, review patch 01]
DIMASI_2016_M = {"ph1": 25.3, "ph2": 58.6, "ph3": 255.4}         # 2013 USD [sourced, review C2]
COMPANY_OVERHEAD_M_PER_YEAR = 5.0                                # small biotech, base of the review's $8 / 5 / 3 m [A]
COST_M = {
    "base":  {"preclinical": 5.0, "filed": 3.0,                  # preclinical and filing [assumption]
              **{k: round(SERTKAYA_TRIAL_M[k] * TRIALS_PER_PHASE[k] * CPI_2008_TO_2024, 1) for k in SERTKAYA_TRIAL_M}},
    "worse": {"preclinical": 10.0, "filed": 3.0,
              **{k: round(v * CPI_2013_TO_2024, 1) for k, v in DIMASI_2016_M.items()}},
}

# Minikel et al. 2024 (Nature): relative success (RS) of genetically supported target–indication pairs [recalled]
GENETIC_RS = {"mendelian": 3.7, "somatic_driver": 2.3, "gwas": 2.0, "other_disease": 1.0, "none": 1.0,
              "no_data": 1.0, "contradicts": 0.5,  # contradicts = [assumption]
              "mendelian_subtype": 2.0}  # [assumption] 2.3: an ordinary genetic link (as GWAS), like its +1 in the scorer
# Share of the RS effect realised at each transition ph1->2, ph2->3, ph3->filing (Minikel phase-wise RS, normalised
# on the log scale) [derived]. Preclinical and filing get none.
RS_PHASE_WEIGHTS = {"ph1": 0.099, "ph2": 0.582, "ph3": 0.319}

# ---------------------------------------------------------------------------
# Economics defaults [assumption unless tagged]
# ---------------------------------------------------------------------------
DISCOUNT_RATE = 0.10
TAX_RATE = 0.21                       # US federal corporate rate [recalled]
COGS_SHARE = {"small_molecule": 0.05, "peptide": 0.08, "nucleic_acid": 0.08, "antibody_like": 0.12, "gene_therapy": 0.20,
              "cell_therapy": 0.30, "radioligand": 0.20, "vaccine": 0.15, "other": 0.10}
SGA_SHARE = 0.25                      # selling, general and admin as share of sales once launched
LAUNCH_SGA_M = 30.0                   # pre-launch commercial build-out, USD m, spent in the filing year
COMPLIANCE = 0.70                     # share of treated-year actually paid (adherence/persistence)
YEARS_TO_PEAK = 6                     # time to peak sales (TIRS style) if not given
LAUNCH_CURVE_ROBEY = [0.10, 0.30, 0.55, 0.75, 0.90, 1.00]  # share of peak in years 1..6 (Robey-shaped)
# Market exclusivity after launch (2.2, review patch 04 / F06 / F13). With a granted or unknown patent: the empirical
# mean market exclusivity period of NMEs, 13.0 years (Grabowski et al., J Med Econ 2021 [sourced, review]). Statutory
# floors: NCE 5, orphan 7, biologic 12 (BPCIA) [sourced, review]. With no patent (none / expired): the floor only.
MARKET_EXCLUSIVITY_EMPIRICAL_Y = 13.0
EXCLUSIVITY_FLOOR_Y = {"nce": 5, "orphan": 7, "biologic": 12}
BIOLOGIC_CLASSES = ("antibody_like", "gene_therapy", "cell_therapy", "vaccine")
POST_LOE_RETENTION = {"small_molecule": 0.10, "peptide": 0.20, "nucleic_acid": 0.30}  # others: 0.35 (biosimilar erosion)
POST_LOE_RETENTION_DEFAULT = 0.35
HORIZON_AFTER_LOE_Y = 3
# Inflation Reduction Act: negotiated price applies from 9 years (small molecule) / 13 years (biologic) after approval
# [recalled]; average first-round net discount ~22% [recalled, CMS 2024 announcement].
MEDICARE_NEGOTIATION_YEAR = {"small_molecule": 9, "default": 13}
MEDICARE_DISCOUNT = 0.22
MEDICARE_SHARE_DEFAULT = 0.30         # share of US sales from Medicare when not given
ORDER_OF_ENTRY_EXP = -0.5             # share of n-th entrant ~ n^-0.5, normalised over entrants
CPI_2016_TO_2024 = 1.307              # used to restate 2016-dollar price analogues [recalled]
# Rare-disease annual net price analogues (P25, P50, P75), Rome-style 2008–2021 data restated to 2024 USD [derived]
RARE_PRICE_ANALOGUES = [102300, 220200, 442300]
EX_US_MULTIPLIER = 0.45               # ex-US sales as share of US sales, if not given

# Monte Carlo spreads (lognormal sigma on the multiplier) [assumption]
MC_SIGMA = {"patients": 0.35, "price": 0.30, "share": 0.40, "cost": 0.30}
MC_DRAWS = 2000
MC_SEED = 20261009

# Economics -> facts thresholds
ECON_NEGATIVE_P = 0.10               # P(rNPV > 0) below this -> economics_negative

# ---------------------------------------------------------------------------
# Forecast for assets without sales (forecast.py). All [assumption] unless tagged; calibrate on CMS launches.
# ---------------------------------------------------------------------------
# Reference annual net prices per patient (P25, P50, P75), 2024 USD, when no analogue price exists (price ladder rung 3)
REFERENCE_PRICE = {
    "rare": RARE_PRICE_ANALOGUES,                      # [derived] Rome 2008-2021 orphan prices, CPI-adjusted
    "oncology": [120000, 200000, 300000],
    "chronic_biologic": [20000, 40000, 70000],         # antibody / protein / nucleic acid, common chronic disease
    "chronic_small": [3000, 8000, 20000],              # small molecule / peptide, common chronic disease
    "acute": [500, 3000, 15000],                       # per course
}
# Uncertainty (lognormal sigma) of the price by where it came from
PRICE_SIGMA = {"user": 0.25, "same_moa": 0.25, "same_indication": 0.35, "reference": 0.6}
PATIENT_SIGMA = {"sourced": 0.35, "assumed": 0.6}
# Willingness to pay per QALY for the value-based price ceiling (ICER range $100-150k [recalled])
WTP_PER_QALY = 150000
# Peak-share multipliers by differentiation (relative to the order-of-entry share); first in class = 1.0
SHARE_MULT = {"best_in_class": 1.6, "claimed_superior": 1.2, "convenience": 0.9, "cost": 1.0,
              "undifferentiated": 0.6, "unknown": 0.8}
COST_DIFF_PRICE_MULT = 0.85        # a cost-based differentiation competes on price
LATE_ENTRY_PENALTY_PER_YEAR = 0.08  # share lost per year behind first in class after the first 2 years
LATE_ENTRY_FLOOR = 0.5
MAX_PEAK_SHARE = 0.8
YEARS_TO_PEAK_BY_SEGMENT = {"rare": 4, "oncology": 5, "chronic_biologic": 7, "chronic_small": 7, "acute": 4}
Z90 = 1.2816                       # P10 / P90 of a normal
