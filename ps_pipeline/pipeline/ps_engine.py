"""
ps_engine.py — reference implementation of the protected-species anomaly engine.

This mirrors quarto/R/ps_functions.R one-for-one so the Quarto pipeline and the
decision-support app can be cross-validated. It reads the aggregated test
database and writes pipeline_output.json (consumed by the web application).

Statistics (all per species, current year vs. historical years):
  percentile        share of historical years strictly below the current value
  robust_anomaly    (current - median) / (1.4826 * MAD)           [MAD-z]
  trend             Poisson GLM  log E[y] = a + b*year  over the trend window;
                    NB attempted first when overdispersed, Poisson fallback
  bayes             Gamma-Poisson conjugate: prior from historical counts,
                    posterior predictive = NegBin(r, p); tail prob P(X >= current)
                    computed via the NB–incomplete-beta identity (validated vs scipy)
  flag (OR gate)    High if robust_anomaly >= 2  OR  percentile >= 90
                    OR  bayes_tail_prob < alpha (0.05)  — any gate fires
"""
import sqlite3, json, math, argparse
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats, special
import statsmodels.api as sm

ap = argparse.ArgumentParser()
ap.add_argument("--db", default="../data/ps_monitoring_test.sqlite")
ap.add_argument("--out", default="../data/pipeline_output.json")
ap.add_argument("--alpha", type=float, default=0.05)
ap.add_argument("--current-year", type=int, default=2025)
args = ap.parse_args()

con = sqlite3.connect(args.db)
q = lambda s: pd.read_sql(s, con)
species = q("select * from species")
ann = q("select * from ps_interactions_annual order by species_code, year")
eff = q("select * from ps_effort_annual order by year")
spat = q("select * from ps_spatial_annual")
oce  = q("select * from ps_ocean_annual")
its  = q("select * from ref_its")
ctx  = {t: q(f"select * from {t}") for t in ["ctx_spatial_effort","ctx_gear","ctx_fisher_behavior","ctx_demographics","ctx_climate_indicators"]}
ref  = {t: q(f"select * from {t}") for t in ["ref_summary_interactions","ref_summary_rate_spatial","ref_summary_ocean"]}
prov = q("select * from provenance")
CUR = args.current_year

# ---------------------------------------------------------------- helpers
def mad_z(x_hist, x_cur):
    med = np.median(x_hist); mad = np.median(np.abs(x_hist - med)) * 1.4826
    if mad == 0: mad = np.std(x_hist, ddof=1) or 1.0
    return (x_cur - med) / mad

def percentile_rank(x_hist, x_cur):
    return 100.0 * np.mean(x_hist < x_cur)

def fit_trend(years, counts, offset=None):
    """Poisson GLM with optional log-offset; NB tried first if overdispersed."""
    X = sm.add_constant(np.asarray(years, float) - years[0])
    y = np.asarray(counts, float)
    off = np.log(offset) if offset is not None else None
    model_used, flag = "Poisson", "Preferred model"
    try:
        pm = sm.GLM(y, X, family=sm.families.Poisson(), offset=off).fit()
        disp = pm.pearson_chi2 / pm.df_resid if pm.df_resid > 0 else 1
        if disp > 1.5:
            try:
                nb = sm.NegativeBinomial(y, X, offset=off).fit(disp=0, maxiter=200)
                if np.isfinite(nb.params[1]): pm, model_used = nb, "Negative binomial"
                else: flag = "NB fitting error; Poisson fallback"
            except Exception:
                flag = "NB fitting error; Poisson fallback"
        b = float(pm.params[1])
    except Exception:
        b, model_used, flag = float("nan"), "none", "GLM failed"
    apc = (math.exp(b) - 1) * 100 if np.isfinite(b) else float("nan")
    return dict(slope_log=b, annual_pct_change=apc, model=model_used, model_flag=flag)

def theil_sen(years, counts):
    return float(stats.theilslopes(counts, years)[0])

def gamma_poisson_prior(x_hist):
    """Method-of-moments Gamma prior on the annual rate; overdispersion-aware."""
    m, v = np.mean(x_hist), np.var(x_hist, ddof=1)
    if v > m * 1.05:                       # overdispersed -> Gamma prior with matching var
        shape = m * m / (v - m); rate = m / (v - m)
    else:                                  # ~Poisson: tight prior from the count sum
        shape = np.sum(x_hist); rate = len(x_hist)
    return float(shape), float(rate)

def nb_tail_prob(shape, rate, x_cur):
    """P(X >= x_cur) under posterior predictive NB(r=shape, p=rate/(rate+1)).
    Uses the identity P(X <= k) = I_p(r, k+1) with the regularized incomplete beta.
    This is the corrected form that avoids LibreOffice NEGBINOM.DIST integer truncation."""
    p = rate / (rate + 1.0)
    cdf_below = special.betainc(shape, x_cur, p) if x_cur > 0 else 0.0   # P(X <= x_cur-1)
    return float(1.0 - cdf_below)

def nb_quantiles(shape, rate, qs=(0.05, 0.5, 0.95)):
    p = rate / (rate + 1.0)
    return [int(stats.nbinom.ppf(qq, shape, p)) for qq in qs]

def haversine(lon1, lat1, lon2, lat2):
    R = 6371.0; p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1); dp = p2 - p1
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# ------------------------------------------------------------ main loop
rows_int, rows_rate, rows_ocean, bayes, causal, its_track, series = [], [], [], [], [], [], {}
_raw_bayes = {}
eff_idx = eff.set_index("year")
for _, sp in species.iterrows():
    k = sp.species_code
    s = ann[ann.species_code == k].sort_values("year")
    years = s.year.values; counts = s.interactions.values.astype(float)
    hist_mask = years < CUR
    xh, xc = counts[hist_mask], float(counts[~hist_mask][0])
    rates = counts / eff_idx.loc[years, "observed_sets"].values
    rh, rc = rates[hist_mask], float(rates[~hist_mask][0])
    series[k] = dict(years=[int(y) for y in years], interactions=[int(c) for c in counts],
                     rate_per_set=[round(float(r), 5) for r in rates])

    # --- Table 2: interactions
    ra = mad_z(xh, xc); pct = percentile_rank(xh, xc)
    ts = theil_sen(years[hist_mask], xh)
    shape, rate = gamma_poisson_prior(xh)
    ptail = nb_tail_prob(shape, rate, xc)
    q05, q50, q95 = nb_quantiles(shape, rate)
    gates = dict(robust=bool(ra >= 2), percentile=bool(pct >= 90), bayes=bool(ptail < args.alpha))
    flag = "High" if any(gates.values()) else ("Low" if ra <= -2 else "Typical")

    # --- Table 2b: rate + spatial
    tw = 10 if sp.group == "Sea turtle" else 5           # trend window (matches reference sheet)
    win = years >= (CUR - tw + 1)
    tr = fit_trend(years[win], counts[win], eff_idx.loc[years[win], "observed_sets"].values)
    sp_rows = spat[spat.species_code == k]
    hc = sp_rows[sp_rows.year < CUR][["centroid_lon","centroid_lat"]].mean()
    cc = sp_rows[sp_rows.year == CUR].iloc[0]
    shift_km = haversine(hc.centroid_lon, hc.centroid_lat, cc.centroid_lon, cc.centroid_lat)
    rate_ra = mad_z(rh, rc); rate_pct = percentile_rank(rh, rc)

    rows_int.append(dict(species_code=k, species=sp.common, current=int(xc), mean=round(xh.mean(),2), median=float(np.median(xh)),
                         p10=round(float(np.percentile(xh,10)),1), p90=round(float(np.percentile(xh,90)),1),
                         percentile=round(pct,1), robust_anomaly=round(float(ra),3), n_years=int(hist_mask.sum()),
                         trend_slope=round(ts,2), trend="Increasing" if ts > 0 else ("Decreasing" if ts < 0 else "Flat"),
                         flag=flag, gates=gates))
    rows_rate.append(dict(species_code=k, species=sp.common, current_interactions=int(xc), current_rate=round(rc,5),
                          hist_mean_rate=round(float(rh.mean()),5), hist_median_rate=round(float(np.median(rh)),5),
                          hist_p90_rate=round(float(np.percentile(rh,90)),5), rate_percentile=round(rate_pct,1),
                          rate_robust_anomaly=round(float(rate_ra),3), annual_pct_change=round(tr["annual_pct_change"],2),
                          trend_model=tr["model"], trend_model_flag=tr["model_flag"], trend_years=tw,
                          trend="Increasing" if tr["annual_pct_change"] > 0 else "Decreasing", historical_years=int(hist_mask.sum()),
                          hist_centroid_lon=round(float(hc.centroid_lon),3), hist_centroid_lat=round(float(hc.centroid_lat),3),
                          cur_centroid_lon=round(float(cc.centroid_lon),3), cur_centroid_lat=round(float(cc.centroid_lat),3),
                          centroid_shift_km=round(shift_km,1), pct_outside_hist90=round(float(cc.pct_outside_hist90),1)))

    # --- Table 2c: ocean
    ocean_ev = {}
    for v, g in oce[oce.species_code == k].groupby("variable"):
        gh, gc = g[g.year < CUR], g[g.year == CUR].iloc[0]
        med_i = float(gh.interaction_env.median()); sel_hist = gh.interaction_env - gh.fleet_env
        sel_cur = float(gc.interaction_env - gc.fleet_env)
        ip = percentile_rank(gh.interaction_env.values, gc.interaction_env); spct = percentile_rank(sel_hist.values, sel_cur)
        rows_ocean.append(dict(species_code=k, species=sp.common, variable=v, current_interaction_env=round(float(gc.interaction_env),4),
                               hist_interaction_median=round(med_i,4), absolute_anomaly=round(float(gc.interaction_env-med_i),4),
                               current_fleet_env=round(float(gc.fleet_env),4), current_selection_anomaly=round(sel_cur,4),
                               hist_selection_median=round(float(sel_hist.median()),4), selection_shift=round(sel_cur-float(sel_hist.median()),4),
                               interaction_percentile=round(ip,1), selection_percentile=round(spct,1), historical_years=int(len(gh))))
        ocean_ev[v] = dict(interaction_percentile=round(ip,1), selection_percentile=round(spct,1))

    _raw_bayes[k] = (shape, rate, xc, ptail)
    bayes.append(dict(species_code=k, species=sp.common, prior_shape=round(shape,3), prior_rate=round(rate,4),
                      posterior_pred_q05=q05, posterior_pred_median=q50, posterior_pred_q95=q95,
                      p_tail=round(ptail,4), alpha=args.alpha, flagged=bool(ptail < args.alpha),
                      note="P(X >= current) under NegBin posterior predictive; NB–incomplete-beta identity"))

    # --- causal diagnostic evidence (auto-populated answers for the decision tree)
    ocean_extreme = any(e["interaction_percentile"] >= 90 or e["interaction_percentile"] <= 10 for e in ocean_ev.values())
    sel_shift = any(e["selection_percentile"] >= 90 or e["selection_percentile"] <= 10 for e in ocean_ev.values())
    causal.append(dict(species_code=k, species=sp.common,
        higher_than_normal=bool(flag == "High"),
        fishery_changed=bool(shift_km > 250 or cc.pct_outside_hist90 > 10),
        shifted_into_core=bool(cc.pct_outside_hist90 < 5 and shift_km > 250),
        new_method=None,          # gear/bait change — requires SME input (ctx_gear)
        expected_from_trend=bool(q05 <= xc <= q95),
        ocean_changed=bool(ocean_extreme),
        distribution_shift_likely=bool(sel_shift),
        strong_year_class=None,   # requires demographic size-class input (ctx_demographics)
        evidence=dict(centroid_shift_km=round(shift_km,1), pct_outside_hist90=round(float(cc.pct_outside_hist90),1),
                      posterior_pred_interval=[q05,q95], ocean=ocean_ev)))

    # --- ITS running-sum tracker (illustrative ITS values)
    r = its[its.species_code == k].iloc[0]
    if pd.notna(r.annual_its):
        w0 = int(r.window_start_year); n_w = int(r.its_window_years)
        wyrs = [y for y in years if w0 <= y < w0 + n_w]
        # ITS applies to fleet-expanded take: observed / observer coverage (SSLL ~100 %, DSLL ~20 %)
        cov = eff_idx.loc[wyrs, "coverage_rate"].values if sp.sector == "DSLL" else np.ones(len(wyrs))
        expanded = counts[np.isin(years, wyrs)] / cov
        cum = float(expanded.sum())
        exp_factor = float(1/np.mean(cov))
        limit = float(r.annual_its) * n_w
        yrs_left = n_w - len(wyrs)
        # P(cumulative exceeds limit before window closes) under posterior predictive for remaining years
        # remaining-years predictive on the observed scale, then expanded
        p_exceed = 1 - stats.nbinom.cdf((limit - cum)/exp_factor, shape * yrs_left, rate / (rate + 1)) if yrs_left > 0 else float(cum > limit)
        its_track.append(dict(species_code=k, species=sp.common, authority=r.authority, annual_its=int(r.annual_its), window_years=n_w,
                              window_start=w0, years_elapsed=len(wyrs), cumulative=int(round(cum)), expansion_factor=round(exp_factor,2), window_limit=int(limit),
                              pct_of_limit=round(100*cum/limit,1), p_exceed_before_close=round(float(p_exceed),3),
                              alert=bool(p_exceed > 0.25)))
    else:
        its_track.append(dict(species_code=k, species=sp.common, authority=r.authority, annual_its=None))

# --- rule-based narrative drafts (mirror of template_narrative() in R) -------
narratives = []
for r2 in rows_int:
    k = r2["species_code"]; r2b = next(r for r in rows_rate if r["species_code"]==k)
    oc = [r for r in rows_ocean if r["species_code"]==k]
    cz = next(c for c in causal if c["species_code"]==k)
    if not cz["higher_than_normal"]: branch = "not applicable (within expectation)"
    elif cz["fishery_changed"] and cz["shifted_into_core"]: branch = "fishery shift into the core distribution"
    elif cz["fishery_changed"]: branch = "change in where the fishery operated (SME review of gear/bait needed)"
    elif cz["expected_from_trend"]: branch = "expected given recent trend and variability"
    elif cz["ocean_changed"] and cz["distribution_shift_likely"]: branch = "ocean-driven distribution shift"
    elif cz["ocean_changed"]: branch = "ocean-driven change in catchability"
    else: branch = "cause unclear; demographic (year-class) review needed"
    ocean_txt = ", ".join(f"{o['variable']} at the {o['interaction_percentile']:.0f}th percentile" for o in oc)
    txt = (f"{r2['flag']} ({r2['robust_anomaly']:+.2f}): {r2['current']} interactions were observed in {CUR} against a historical "
           f"median of {int(r2['median'])} ({r2['percentile']:.0f}th percentile; Bayesian tail probability {next(b['p_tail'] for b in bayes if b['species_code']==k):.3f}). "
           f"The rate anomaly was {r2b['rate_robust_anomaly']:+.2f} ({r2b['rate_percentile']:.0f}th percentile) with a "
           f"{abs(r2b['annual_pct_change']):.1f}% annual {r2b['trend'].lower()} trend over the last {r2b['trend_years']} years ({r2b['trend_model']}). "
           f"The interaction centroid moved {r2b['centroid_shift_km']:.0f} km and {r2b['pct_outside_hist90']:.1f}% of interactions fell outside the "
           f"historical 90% area. Ocean context: {ocean_txt}. Causal-diagnostic branch supported by the evidence: {branch}.")
    narratives.append(dict(species_code=k, species=r2["species"], flag=r2["flag"], narrative=txt,
                           causal_branch=branch, source="rule-based template",
                           provenance="Generated 2026-09-25 from aggregated pipeline outputs; not reviewed text."))

out = dict(narratives=narratives, meta=dict(generated="2026-09-25", current_year=CUR, alpha=args.alpha, source_db=str(args.db),
                     decision_rule="OR gate: robust_anomaly >= 2 OR percentile >= 90 OR Bayesian tail prob < alpha",
                     data_note="Synthetic aggregated test data calibrated to ps_monitoring_tables_AI.xlsx; ITS and context tables are illustrative."),
           species=species.to_dict("records"), series=series,
           effort=eff.to_dict("records"),
           table2_interactions=rows_int, table2b_rate_spatial=rows_rate, table2c_ocean=rows_ocean,
           bayes=bayes, causal=causal, its=its_track,
           context={k.replace("ctx_",""): v.where(pd.notna(v), None).to_dict("records") for k, v in ctx.items()},
           reference={k.replace("ref_summary_",""): v.where(pd.notna(v), None).to_dict("records") for k, v in ref.items()},
           provenance=prov.to_dict("records"))
def _clean(o):
    if isinstance(o, dict): return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [_clean(v) for v in o]
    if hasattr(o, "item"): o = o.item()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
    return o
Path(args.out).write_text(json.dumps(_clean(out), indent=1, allow_nan=False, default=str))

# --- validation: NB identity vs scipy ---------------------------------------
for k, (sh, ra_, xc, pt) in _raw_bayes.items():
    ref_p = stats.nbinom.sf(xc - 1, sh, ra_/(ra_+1))
    assert abs(ref_p - pt) < 1e-9, (k, ref_p, pt)
print("NB–incomplete-beta identity validated against scipy.stats.nbinom for all species.")
print(pd.DataFrame(rows_int)[["species","current","median","percentile","robust_anomaly","flag"]].to_string(index=False))
print(pd.DataFrame(bayes)[["species","posterior_pred_q05","posterior_pred_q95","p_tail","flagged"]].to_string(index=False))
print(pd.DataFrame([{k:v for k,v in r.items() if k!='evidence'} for r in causal]).to_string(index=False))
print(pd.DataFrame(its_track).to_string(index=False))
print("wrote", args.out)
