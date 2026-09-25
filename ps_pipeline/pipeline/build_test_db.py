"""
build_test_db.py
----------------
Builds the SQLite test database that stands in for the *aggregated* LOTUS
outputs the SAFE protected-species pipeline consumes.

Design rule (from the workshop): raw PIROP observer records never leave NOAA.
Everything here is aggregated (species x year, species x year x stratum) and the
observed-set counts are large enough that no 3-vessel confidentiality rule is
implicated. The three summary sheets in ps_monitoring_tables_AI.xlsx are copied
in verbatim as the reference ("gold") tables; the annual series are synthesised
so that the pipeline's recomputed statistics land close to the reference values.

Usage:  python build_test_db.py  [--xlsx path] [--out path]
"""
import argparse, sqlite3
from pathlib import Path
import numpy as np, pandas as pd, openpyxl

ap = argparse.ArgumentParser()
ap.add_argument("--xlsx", default="/mnt/project/ps_monitoring_tables_AI.xlsx")
ap.add_argument("--out",  default="../data/ps_monitoring_test.sqlite")
ap.add_argument("--seed", type=int, default=2026)
args = ap.parse_args()
rng = np.random.default_rng(args.seed)

YEARS = list(range(2006, 2026))          # 20 years; 2025 = current
CUR   = YEARS[-1]

# canonical species keys ---------------------------------------------------
SPECIES = {
  "BFAL": dict(common="Black-footed albatross", sheet_int="Albatross, Black-footed", sheet_rate="Black-footed albatross", sci="Phoebastria nigripes",   group="Seabird",     esa="MBTA", sector="DSLL"),
  "LAAL": dict(common="Laysan albatross",       sheet_int="Albatross, Laysan",       sheet_rate="Laysan albatross",       sci="Phoebastria immutabilis", group="Seabird",     esa="MBTA", sector="DSLL"),
  "OWT":  dict(common="Oceanic whitetip shark", sheet_int="Shark, Oceanic White-Tip",sheet_rate="Oceanic whitetip shark", sci="Carcharhinus longimanus", group="Elasmobranch",esa="Threatened", sector="DSLL"),
  "SMA":  dict(common="Shortfin mako shark",    sheet_int="Shark, Shortfin Mako",    sheet_rate="Shortfin mako shark",    sci="Isurus oxyrinchus",       group="Elasmobranch",esa="Not listed (CITES II)", sector="DSLL"),
  "LBT":  dict(common="Leatherback turtle",     sheet_int="Turtle, Leatherback",     sheet_rate="Leatherback turtle",     sci="Dermochelys coriacea",    group="Sea turtle",  esa="Endangered", sector="SSLL"),
  "LHT":  dict(common="Loggerhead turtle",      sheet_int="Turtle, Loggerhead",      sheet_rate="Loggerhead turtle",      sci="Caretta caretta",         group="Sea turtle",  esa="Endangered (N. Pacific DPS)", sector="SSLL"),
}

# ---- read reference sheets ---------------------------------------------
wb = openpyxl.load_workbook(args.xlsx, data_only=True)
def sheet_df(name):
    ws = wb[name]; rows = [r for r in ws.iter_rows(values_only=True) if any(v is not None for v in r)]
    return pd.DataFrame(rows[1:], columns=[c if c is not None else "Variable" for c in rows[0]])
ref_int  = sheet_df("interactions")
ref_rate = sheet_df("rate spatial")
ref_ocean_raw = sheet_df("ocean")

# reshape ocean sheet (species header rows followed by 4 variable rows)
ocean_rows, cur_sp = [], None
for _, r in ref_ocean_raw.iterrows():
    if pd.isna(r["Current Interaction Environment"]): cur_sp = r["Variable"]; continue
    d = r.to_dict(); d["Species"] = cur_sp; ocean_rows.append(d)
ref_ocean = pd.DataFrame(ocean_rows)

# ---- synthesise annual interaction series -------------------------------
def fit_series(mean, median, p10, p90, slope, n=19, tries=6000):
    """Random-search for an integer series whose summary stats approximate the reference."""
    best, best_err = None, 1e18
    sd0 = max((p90 - p10) / 2.56, 0.5)
    t = np.arange(n) - (n - 1) / 2
    for _ in range(tries):
        trend = slope * 0.35 * t
        y = np.clip(np.round(mean + trend + rng.normal(0, sd0, n)), 0, None)
        err = ((y.mean()-mean)/max(mean,1))**2 + ((np.median(y)-median)/max(median,1))**2 \
            + ((np.percentile(y,10)-p10)/max(p10,1))**2 + ((np.percentile(y,90)-p90)/max(p90,1))**2
        if err < best_err: best, best_err = y, err
    return best.astype(int)

annual = []
for key, meta in SPECIES.items():
    r = ref_int.loc[ref_int["Species"] == meta["sheet_int"]].iloc[0]
    hist = fit_series(r["Mean"], r["Median"], r["P10"], r["P90"], r["Trend Slope"])
    series = list(hist) + [int(r["Current"])]
    for y, v in zip(YEARS, series):
        annual.append(dict(species_code=key, year=y, interactions=int(v)))
ann = pd.DataFrame(annual)

# ---- effort (observed sets) so that rate = interactions / observed_sets ---
cur_sets = int(round(37 / 0.0317300782275064))    # reference current rate implies ~1166 observed sets
effort = []
for y in YEARS:
    obs_sets = cur_sets if y == CUR else int(rng.normal(1250, 120))
    total_sets = int(obs_sets / rng.uniform(0.19, 0.24))          # DSLL ~20 % coverage
    hooks_per_set = int(rng.normal(2800, 150))
    effort.append(dict(year=y, sector="DSLL", observed_sets=obs_sets, total_sets=total_sets,
                       observed_hooks=obs_sets*hooks_per_set, total_hooks=total_sets*hooks_per_set,
                       coverage_rate=round(obs_sets/total_sets, 4), observed_trips=int(obs_sets/13)))
eff = pd.DataFrame(effort)

# ---- spatial centroids per year -------------------------------------------
spatial = []
for key, meta in SPECIES.items():
    r = ref_rate.loc[ref_rate["Species"] == meta["sheet_rate"]].iloc[0]
    for y in YEARS:
        if y == CUR:
            lon, lat, out = r["Current Centroid Lon"], r["Current Centroid Lat"], r["Pct Interactions Outside 90"]
        else:
            lon = r["Historical Centroid Lon"] + rng.normal(0, 1.8)
            lat = r["Historical Centroid Lat"] + rng.normal(0, 1.1)
            out = max(0, rng.normal(2.5, 2.0))
        spatial.append(dict(species_code=key, year=y, centroid_lon=round(lon,4), centroid_lat=round(lat,4),
                            pct_outside_hist90=round(out,2)))
spat = pd.DataFrame(spatial)

# ---- ocean environment per year (interaction-weighted & fleet-weighted) ---
ocean = []
VARS = ["Chlorophyll-a", "Distance to seamount", "Sea-level anomaly", "SST"]
for key, meta in SPECIES.items():
    for v in VARS:
        r = ref_ocean.loc[(ref_ocean["Species"] == meta["sheet_rate"]) & (ref_ocean["Variable"] == v)].iloc[0]
        med_i = r["Historical Interaction Median"]
        med_f = r["Historical Selection Median"] + r["Historical Interaction Median"]
        sd = abs(r["Absolute Anomaly"]) * 1.2 + 1e-6
        for y in YEARS:
            if y == CUR:
                vi, vf = r["Current Interaction Environment"], r["Current Fleet Environment"]
            else:
                vi = med_i + rng.normal(0, sd); vf = med_f + rng.normal(0, sd*0.6)
            ocean.append(dict(species_code=key, year=y, variable=v, interaction_env=round(vi,5), fleet_env=round(vf,5)))
oce = pd.DataFrame(ocean)

# ---- multi-disciplinary context tables (illustrative; from workshop topic tables)
spatial_effort = pd.DataFrame([
  ("Latitude: south of 20°N",   44.2, 61.8, "Low bigeye CPUE north; targeting yellowfin",           "OWT,LBT"),
  ("Latitude: 20°N–30°N",        48.1, 32.5, "High fuel cost limiting long northern transits",       "LHT"),
  ("Latitude: north of 30°N",     7.7,  5.7, "Seasonal swordfish sets only",                          "LHT,BFAL,LAAL"),
  ("Longitude: west of 160°W",   31.5, 46.2, "Favourable temperature fronts",                         "LBT"),
], columns=["stratum","baseline_effort_share_pct","current_effort_share_pct","operational_driver","species_overlap"])
spatial_effort["shift_pct_points"] = (spatial_effort.current_effort_share_pct - spatial_effort.baseline_effort_share_pct).round(1)

gear = pd.DataFrame([
  ("Leader type: monofilament", 100.0, 823, 0.1001, 23.9, "~41 % bite-off for sharks; reduced trailing line"),
  ("Leader type: wire",           0.0,   0, None,   None, "Phased out by regulation (2022)"),
  ("Bait: milkfish (vs. sanma)", 85.0, 680, 0.0890, 24.1, "Lower cost; lower bigeye CPUE; potential effort shift"),
  ("Hook position: shallow (hooks 1–3 from float)", None, None, None, 15.8, "49 % of takes; oceanic whitetip and juvenile zone"),
  ("Hook position: deep (hooks ≥4 from float)",     None, None, None, 62.8, "51 % of takes; adult leatherback diving zone"),
], columns=["gear_variable","fleet_adoption_pct","observed_interactions","interaction_cpue_per_1000_hooks","at_vessel_mortality_pct","finding"])

behavior = pd.DataFrame([
  ("0 takes (baseline sets)",        14.2, "Baseline rate",         None, 0, "Standard set spacing"),
  ("1 interaction",                  15.5, "No significant change", 12,   0, "Minor adjustment; vessels typically continue"),
  ("3 interactions",                 22.4, "Variable",              7,    0, "4 moved, 3 ended trip; movement does not guarantee zero takes"),
  ("Trip limit met (≥5 LH or ≥2 LB)", None,"0 % (mandatory stop)",  3,    1, "Return to port; 5-day stand-down"),
], columns=["cumulative_interactions_on_trip","avg_distance_to_next_set_km","post_move_interaction_probability","n_trips","regulatory_limit_triggered","fleet_response"])

demographics = pd.DataFrame([
  ("LBT", "West Pacific leatherback", "juvenile (<115 cm SCL)", 35.0, 62.8, 14.0, 9.3,   "Stable since 2017; historical model −6.0 %/yr"),
  ("LBT", "West Pacific leatherback", "subadult/adult",          65.0, 15.8, 14.0, None,  ""),
  ("LBT", "East Pacific leatherback", "all (5 % of takes by genetics)", 5.0, 22.0, 14.0, 0.5, "Decreasing −8.1 %/yr"),
  ("OWT", "Oceanic whitetip shark",  "100–160 cm TL (mixed subadult/adult)", 100.0, 23.9, 3.2, 1288, "Increasing +6–7 %/yr (2025 WCPO assessment)"),
  ("LHT", "N. Pacific loggerhead",   "juvenile (<60 cm SCL)",   58.0, 4.0, 18.0, None, "Nesting trend increasing (Japan)"),
  ("LHT", "N. Pacific loggerhead",   "subadult/adult",          42.0, 2.0, 18.0, None, ""),
], columns=["species_code","dps","size_class","pct_of_takes","at_vessel_mortality_pct","post_release_mortality_pct","est_total_mortalities_per_yr","population_trend_note"])

climate = pd.DataFrame([
  ("ONI", CUR, 1.2,  "El Niño phase / warm anomaly", "Strong positive", "Shifts target distribution; compresses foraging habitat"),
  ("PDO", CUR, -0.85,"Negative / cool phase",         "Moderate negative","North Pacific boundary currents and prey density"),
  ("TurtleWatch 17.5–18.5 °C band", CUR, None, "South-eastern compression", "Strong positive (SSLL)", "Swordfish-set overlap with loggerheads"),
  ("STCZ latitude", CUR, 22.0, "Southward shift", "Strong positive (DSLL)", "Concentrates prey and juvenile leatherbacks"),
], columns=["indicator","year","value","state","interaction_correlation","mechanism"])

# ITS reference — ILLUSTRATIVE placeholders, replace with BiOp values before Council use
its = pd.DataFrame([
  ("LHT", "SSLL BiOp (illustrative)", 36, 5, 2021),
  ("LBT", "SSLL BiOp (illustrative)", 16, 5, 2021),
  ("OWT", "DSLL BiOp (illustrative)", 300, 5, 2023),
  ("BFAL","Seabird measures (no ITS)", None, None, None),
  ("LAAL","Seabird measures (no ITS)", None, None, None),
  ("SMA", "Not ESA-listed", None, None, None),
], columns=["species_code","authority","annual_its","its_window_years","window_start_year"])

# ---- write --------------------------------------------------------------
out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
if out.exists(): out.unlink()
con = sqlite3.connect(out)
pd.DataFrame([dict(species_code=k, **{kk: vv for kk, vv in v.items() if kk not in ("sheet_int","sheet_rate")}) for k, v in SPECIES.items()]).to_sql("species", con, index=False)
ann.to_sql("ps_interactions_annual", con, index=False)
eff.to_sql("ps_effort_annual", con, index=False)
spat.to_sql("ps_spatial_annual", con, index=False)
oce.to_sql("ps_ocean_annual", con, index=False)
spatial_effort.to_sql("ctx_spatial_effort", con, index=False)
gear.to_sql("ctx_gear", con, index=False)
behavior.to_sql("ctx_fisher_behavior", con, index=False)
demographics.to_sql("ctx_demographics", con, index=False)
climate.to_sql("ctx_climate_indicators", con, index=False)
its.to_sql("ref_its", con, index=False)
ref_int.to_sql("ref_summary_interactions", con, index=False)
ref_rate.to_sql("ref_summary_rate_spatial", con, index=False)
ref_ocean.to_sql("ref_summary_ocean", con, index=False)
pd.DataFrame([dict(table_name=t, source=s, confidentiality=c) for t,s,c in [
  ("ps_interactions_annual","LOTUS aggregated (synthetic test)","Aggregated; no vessel identifiers"),
  ("ps_effort_annual","LOTUS aggregated (synthetic test)","Aggregated"),
  ("ps_spatial_annual","LOTUS + observer set positions, aggregated to centroid (synthetic test)","Centroid only; 3-vessel rule N/A"),
  ("ps_ocean_annual","ERDDAP/OceanWatch matched to sets, aggregated (synthetic test)","Aggregated"),
  ("ctx_*","Workshop topic tables (illustrative)","Illustrative"),
  ("ref_summary_*","ps_monitoring_tables_AI.xlsx (reference)","Reference"),
  ("ref_its","ILLUSTRATIVE — replace with BiOp ITS","Placeholder")]]).to_sql("provenance", con, index=False)
con.commit(); con.close()

# CSV mirrors for users without SQLite tooling
csvdir = out.parent / "csv"; csvdir.mkdir(exist_ok=True)
for name, df in [("ps_interactions_annual",ann),("ps_effort_annual",eff),("ps_spatial_annual",spat),("ps_ocean_annual",oce),
                 ("ctx_spatial_effort",spatial_effort),("ctx_gear",gear),("ctx_fisher_behavior",behavior),
                 ("ctx_demographics",demographics),("ctx_climate_indicators",climate),("ref_its",its),
                 ("ref_summary_interactions",ref_int),("ref_summary_rate_spatial",ref_rate),("ref_summary_ocean",ref_ocean)]:
    df.to_csv(csvdir / f"{name}.csv", index=False)

# quick fidelity report
print("Series fidelity vs reference summary (mean / median / P10 / P90):")
for key, meta in SPECIES.items():
    h = ann[(ann.species_code==key)&(ann.year<CUR)].interactions.values
    r = ref_int.loc[ref_int["Species"]==meta["sheet_int"]].iloc[0]
    print(f"  {key:5s} synth {h.mean():7.1f} {np.median(h):6.1f} {np.percentile(h,10):6.1f} {np.percentile(h,90):7.1f} | ref {r['Mean']:7.1f} {r['Median']:6.1f} {r['P10']:6.1f} {r['P90']:7.1f}")
print("wrote", out, "and", csvdir)
