"""Human-readable output of evaluate(): a one-screen card and a markdown report.

Tags: [S] fact given (person, Open Targets, confirmed LLM claim), [D] derived or computed by this package,
[A] assumption (model default in the economics).
"""
from __future__ import annotations

COLOR = {"G": "green", "Y": "yellow", "R": "red", "U": "unknown"}


def _m(x):
    return "n/a" if x is None else f"{'−' if x < 0 else ''}${abs(x):,.1f}m"


def _be(k, v):
    if v is None:
        return "not reachable"
    if k == "patients":
        return f"{v:,.0f} eligible patients"
    if k == "annual_net_price_usd":
        return f"${v:,.0f}/yr"
    return _pct(v)


def _pct(x):
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _v(x):
    return {True: "yes", False: "no", None: "unknown"}.get(x, str(x)) if isinstance(x, (bool, type(None))) else str(x)


def card(p: dict) -> str:
    v, s = p["verdict"], p["score"]
    cov = s["coverage"]
    out = [f"VERDICT: {v['decision']}  ({v['grounds_text']})",
           f"  pluses {s['pos']} (science {s['science_pos']}), minuses {s['neg']}; "
           f"data for {cov['items_known']} of {cov['items_total']} items ({cov['asset_known']} asset-level)",
           f"  {v['reason']}"]
    for c in v.get("caps") or []:
        out.append(f"  CAP: {c['reason']}")
    out.append("Scorecard: " + "; ".join(f"{i['name']} [{COLOR[i['color']]}{'+' if i.get('points') == 2 else ''}]"
                                         for i in p["scorecard"]))
    counted = [r for r in p["rules"] if r["counted"]]
    if counted:
        out.append("Minuses: " + "; ".join(f"{r['name']} ({r['tier']})" for r in counted))
    ref = p.get("reference") or {}
    ev = ref.get("evidence") or {}
    if ev.get("range"):
        out.append(f"Reference: {ev['range'][0]:.0%}–{ev['range'][1]:.0%} of similar pairs reached launch "
                   f"from {ev['from']} [D]")
    e = p.get("economics")
    if e:
        mc = e["monte_carlo"]
        tag = "[D from sourced inputs]" if e.get("drives_verdict") else "[D from ASSUMED inputs: not used in verdict]"
        out.append(f"Peak US sales {_m(e['base']['peak_us_m'])}; rNPV base {_m(e['base']['rnpv_m'])}; Monte Carlo "
                   f"P10/P50/P90 {_m(mc['p10_m'])} / {_m(mc['p50_m'])} / {_m(mc['p90_m'])}; "
                   f"P(rNPV>0) {_pct(mc['p_positive'])} {tag}")
        fc = e.get("forecast")
        if fc:
            sc = fc["scenarios"]
            out.append(f"Forecast: price ${fc['price']['value']:,.0f}/yr ({fc['price']['rung']}), peak share "
                       f"{_pct(fc['peak_share']['value'])} ({fc['peak_share']['class'] or 'entered'}), peak in "
                       f"{fc['years_to_peak']} y; rNPV bear / median / bull {_m(sc['bear']['rnpv_m'])} / "
                       f"{_m(sc['median']['rnpv_m'])} / {_m(sc['bull']['rnpv_m'])}")
            be = fc["break_even"]
            need = [f"{k.replace('_', ' ')} ≥ {_be(k, v)}" for k, v in be.items()]
            out.append("To break even you need ONE of: " + "; ".join(need)
                       + f". Biggest driver: {fc['tornado'][0]['driver']}")
            if fc.get("required_peak_for_post_money_m") is not None or "post_money_m" in fc:
                rp = fc.get("required_peak_for_post_money_m")
                out.append(f"Post-money ${fc['post_money_m']:.0f}m needs peak US sales "
                           + ("beyond any plausible level" if rp is None else _m(rp)))
        ms = e.get("milestone")
        if ms:
            lo, hi = ms["capital_to_milestone_m"]
            out.append(f"Next milestone: {ms['next_milestone']} — ${lo:.0f}–{hi:.0f}m, {ms['years_to_milestone']:.1f} years, "
                       f"P(success) {_pct(ms['p_milestone_success'])}; to approval ${ms['capital_to_approval_m'][0]:.0f}–"
                       f"{ms['capital_to_approval_m'][1]:.0f}m in {ms['financing_rounds_to_approval']} rounds"
                       + (f"; cash ${ms['cash_m']:.0f}m" + (" (SHORT)" if ms.get("runway_short") else "")
                          if "cash_m" in ms else ""))
        if "investor" in e:
            iv = e["investor"]
            out.append(f"Investor: expected MOIC {iv['moic_expected']:.2f}x (if success {iv['moic_if_success']:.2f}x), "
                       f"expected IRR {_pct(iv['irr_expected'])} [D]")
    elif p.get("economics_note"):
        out.append(f"Economics: {p['economics_note']}")
    gate = p.get("gate") or {}
    if gate.get("pending"):
        out.append(f"Pending (not scored until a human confirms): {len(gate['pending'])} — "
                   + "; ".join(f"{x['fact']}={_v(x['value'])}" for x in gate["pending"]))
    if v.get("conditions"):
        out.append("Conditions for Invest: " + "; ".join(f"{c['label'].split('. ')[0]} -> {_v(c['to'])}"
                                                       for c in v["conditions"][:5]))
    qs = p.get("dd_questions") or []
    if qs:
        out.append("Due-diligence questions:")
        out += [f"  {i + 1}. {q['question']}" + (" (can change the verdict)" if q.get("critical") else "")
                + (f" — needs: {', '.join(q['needs'])}" if q.get("needs") else "") for i, q in enumerate(qs[:5])]
    return "\n".join(out)


def markdown(p: dict, title: str = "Scoring report") -> str:
    v, s = p["verdict"], p["score"]
    out = [f"# {title}", "", f"**Verdict: {v['decision']}** — {v['grounds_text']}.", "", v["reason"], "",
           f"Scorer {p['config']['version']} (sha256 {str(p['config']['sha256'])[:12]}…)", ""]
    for c in v.get("caps") or []:
        out.append(f"- Cap: {c['reason']}")
    out += ["", "## Scorecard", "", "| Item | Colour | Points | Facts |", "|---|---|---|---|"]
    for i in p["scorecard"]:
        out.append(f"| {i['name']} | {COLOR[i['color']]} | {i['points']} | {', '.join(i['facts']) or '—'} |")
    out += ["", "## Rules that fired", ""]
    if p["rules"]:
        out += ["| Rule | Tier | Counted | Facts |", "|---|---|---|---|"]
        out += [f"| {r['name']} | {r['tier']} | {'yes' if r['counted'] else ('no (note)' if r['tier'] == 'note' else 'no (' + str(r['absorbed_by']) + ')')} | "
                f"{', '.join(r['facts'])} |" for r in p["rules"]]
    else:
        out.append("None.")
    e = p.get("economics")
    out += ["", "## Economics", ""]
    if e:
        b, mc = e["base"], e["monte_carlo"]
        out += [f"- Peak US sales {_m(b['peak_us_m'])}, worldwide {_m(b['peak_total_m'])} [D]",
                f"- Launch in {b['launch_in_y']:.1f} years; P(approval) {_pct(b['pos'])} [D]",
                f"- rNPV base {_m(b['rnpv_m'])}; with DiMasi-level costs {_m(e['worse_cost_case']['rnpv_m'])} [D]",
                f"- Monte Carlo ({mc['draws']} draws): P10 {_m(mc['p10_m'])}, P50 {_m(mc['p50_m'])}, P90 {_m(mc['p90_m'])};"
                f" P(rNPV>0) {_pct(mc['p_positive'])} [D]",
                f"- Break-even net price per patient-year: "
                + ("never positive" if e["break_even_price_usd"] is None else f"${e['break_even_price_usd']:,.0f}")
                + " [D]",
                f"- Economic facts produced: {e['facts']} [D]"
                + ("" if e.get("drives_verdict") else " — patients or price are assumptions, so economics does NOT "
                   "change the verdict")]
        fc = e.get("forecast")
        if fc:
            out += ["", "### Forecast without sales: where the numbers come from and what you have to believe", "",
                    f"- Segment: {fc['segment']}; time to peak {fc['years_to_peak']} years [A]",
                    f"- Price ${fc['price']['value']:,.0f} per patient-year (range ${fc['price']['range'][0]:,.0f}–"
                    f"${fc['price']['range'][1]:,.0f}); rung '{fc['price']['rung']}': {fc['price']['basis']}",
                    f"- Peak share {_pct(fc['peak_share']['value'])}: {fc['peak_share']['basis']}",
                    f"- Uncertainty (lognormal sigma): {fc['sigma']}", "",
                    "| Driver | rNPV at low | rNPV at high | Swing | Decides the sign |", "|---|---|---|---|---|"]
            out += [f"| {t['driver']} | {_m(t['low_rnpv_m'])} | {_m(t['high_rnpv_m'])} | {_m(t['swing_m'])} | "
                    f"{'yes' if t['crosses_zero'] else 'no'} |" for t in fc["tornado"]]
            out += ["", "Break-even (each alone, others at base): "
                    + "; ".join(f"{k.replace('_', ' ')} ≥ {_be(k, v)}" for k, v in fc["break_even"].items()), "",
                    "| Scenario | Peak US sales | rNPV | Why |", "|---|---|---|---|"]
            out += [f"| {n} | {_m(fc['scenarios'][n]['peak_us_m'])} | {_m(fc['scenarios'][n]['rnpv_m'])} | "
                    f"{fc['scenarios'][n]['why']} |" for n in ("bear", "median", "bull")]
            if "post_money_m" in fc:
                rp = fc.get("required_peak_for_post_money_m")
                out.append(f"\nTo justify the post-money ${fc['post_money_m']:.0f}m the asset needs peak US sales of "
                           + ("more than any plausible level" if rp is None else _m(rp)) + ".")
        ms = e.get("milestone")
        if ms:
            out += ["", "### Capital to next milestone [D]", "",
                    f"- Next milestone: {ms['next_milestone']}; capital ${ms['capital_to_milestone_m'][0]:.0f}–"
                    f"{ms['capital_to_milestone_m'][1]:.0f}m (Sertkaya–DiMasi); {ms['years_to_milestone']:.1f} years; "
                    f"P(success) {_pct(ms['p_milestone_success'])}",
                    f"- Capital to approval ${ms['capital_to_approval_m'][0]:.0f}–{ms['capital_to_approval_m'][1]:.0f}m "
                    f"(expected, with stopping after a failure: ${ms['expected_capital_to_approval_m']:.0f}m), "
                    f"about {ms['financing_rounds_to_approval']} financing rounds",
                    f"- Value after the milestone (rNPV, the step-up a licensee or buyer pays for): "
                    f"{_m(ms['rnpv_after_milestone_m'])}"]
            if "cash_m" in ms:
                out.append(f"- Company cash ${ms['cash_m']:.0f}m: " + ("does NOT reach the milestone"
                                                                     if ms["runway_short"] else "reaches the milestone"))
        if "investor" in e:
            iv = e["investor"]
            out.append(f"- Investor: stake {_pct(iv['stake_now'])} now, {_pct(iv['stake_at_exit'])} at exit; expected "
                       f"MOIC {iv['moic_expected']:.2f}x, if success {iv['moic_if_success']:.2f}x; expected IRR "
                       f"{_pct(iv['irr_expected'])} vs required {_pct(iv['required_irr'])}; highest pre-money that "
                       f"earns it ${iv['max_pre_money_m']:.0f}m"
                       + ("" if iv["earns_cost_of_capital"] else " — the round is priced above that") + " [D]")
        if "license" in e:
            out.append(f"- Licensing: licensor NPV {_m(e['license']['licensor_npv_m'])} [D]")
        assumed = set(e["assumptions"].get("assumed") or [])
        out += ["", "Inputs (tag [A] = assumption; the rest of the model parameters are defaults from constants.py):", ""]
        out += [f"- {k}: {val}{' [A]' if k in assumed else ''}" for k, val in e["assumptions"].items() if k != "assumed"]
    else:
        out.append(p.get("economics_note") or "not run")
    out += ["", "## What would change the verdict", ""]
    flips = p["what_would_change"][:15]
    if flips:
        out += ["| Fact | Now | Change to | Verdict |", "|---|---|---|---|"]
        out += [f"| {f['label']} | {_v(f['from'])} | {'hidden' if f['action'] == 'hide' else _v(f['to'])} | "
                f"{f['verdict_to']} |" for f in flips]
    else:
        out.append("No single fact changes the verdict.")
    out += ["", "## Due-diligence questions", ""]
    out += [f"{i + 1}. {q['question']}" + (" *(can change the verdict)*" if q.get("critical") else "")
            + (f" — needs: {', '.join(q['needs'])}" if q.get("needs") else "") for i, q in enumerate(p["dd_questions"])]
    gate = p.get("gate") or {}
    if gate.get("pending"):
        out += ["", "## Pending claims (not scored until confirmed)", "", "| Fact | Value | Reason |", "|---|---|---|"]
        out += [f"| {x['fact']} | {_v(x['value'])} | {x['reason']} |" for x in gate["pending"]]
    f = p["facts"]
    out += ["", "## Facts", "", "| Fact | Value | Tag |", "|---|---|---|"]
    out += [f"| {k} | {_v(x)} | [S] |" for k, x in sorted(f["given"].items())]
    out += [f"| {k} | {_v(x)} | [D] from {', '.join(f['derived_from'].get(k, []))} |" for k, x in sorted(f["derived"].items())]
    return "\n".join(out) + "\n"
