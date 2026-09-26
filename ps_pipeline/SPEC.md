# Protected Species SAFE Pipeline & Decision-Support App — Specification

| | |
|---|---|
| **Version** | 0.3 (2026-09-25) |
| **Status** | Working draft — test data only; not approved for Council use |
| **Owner** | Neptune statistics team (T. Stockton) |
| **Users** | WPRFMC protected-species staff (A. Ishizaki, T. Remington); PIFSC data providers; Neptune/PIFSC analysts |
| **Scope** | Pelagic FEP SAFE report §3.3.2 (protected species interactions), Hawaii deep-set and shallow-set longline fisheries |

How to use this document: each requirement has an ID (`P-`, `E-`, `A-`, `X-`, `N-`) so it can be referenced in issues and change notes. Edit in place; record changes in §12. Anything marked **PLACEHOLDER** must be resolved before v1.0.

---

## 1. Purpose

Replace the manual annual workflow (ad hoc SQL → spreadsheets → Word) for the protected-species section of the SAFE report with an automated, defensible pipeline and a decision-support application that:

1. computes the three SAFE summary tables (Tables 2, 2b, 2c) from aggregated observer data;
2. flags species whose interaction counts are anomalous, using redundant statistical checks;
3. assembles the multi-disciplinary context (spatial effort, gear, fisher behaviour, ocean, demographics) needed to characterise an anomaly;
4. walks the working group's causal-diagnostic checklist, with expert input where the data cannot answer;
5. drafts, and lets staff edit, the species narratives;
6. produces the report section as a Word document or Google Doc;
7. is usable by non-technical staff without R, Quarto or programming.

## 2. Non-goals (this version)

- Replacing the Biological Opinion ITS methodology (PBR- or λ-anchored thresholds are a separate workstream).
- Accessing set-level or vessel-level PIROP observer records.
- Fleet-management decisions (closures, trip limits). The tool informs; it does not decide.
- Species beyond the six monitored: black-footed albatross, Laysan albatross, oceanic whitetip shark, shortfin mako shark, leatherback turtle, loggerhead turtle.

## 3. Architecture

```
NOAA / PIFSC (confidential)                 Pipeline (R/Quarto or Python)        Decision-support app (HTML)
──────────────────────────────              ──────────────────────────────        ───────────────────────────
Field tablets → Pirops → LOTUS   ──SQL──▶   aggregated views                 ──▶  pipeline_output.json
                                            engine: tables, trend, Bayes,          loaded by staff
                                            OR gate, ITS tracker, narratives       review → judge → edit → export
                                            Quarto → SAFE section (.docx/.html)    Word (.docx) | Google Doc
```

### 3.1 Components

| Component | File(s) | Language | Owner |
|---|---|---|---|
| Test database builder | `pipeline/build_test_db.py` | Python | Neptune |
| Reference engine | `pipeline/ps_engine.py` | Python | Neptune |
| Production pipeline | `quarto/protected_species_safe_section.qmd`, `quarto/R/ps_functions.R` | R / Quarto | Neptune → PIFSC |
| App builder | `pipeline/build_app.py` (injects JSON into `app/template_*.html`) | Python | Neptune |
| Report module | `app/report_module.js` (aggregation chapter, section builder, docx/HTML renderers) | JS | Neptune |
| Decision-support app | `app/Protected_Species_Decision_Support.html` (single file, published as claude.ai artifact) | HTML/JS | Neptune |
| QA harness | `qa/shots.py`, `qa/build_sample_docx.js`, `qa/build_quickstart.js` | Python / Node | Neptune |

### 3.2 Data-confidentiality principle

**P-1** Raw PIROP observer data never leaves NOAA. Every table the pipeline reads is aggregated to species × year or species × year × stratum. **P-2** No vessel identifiers, set positions or trip records appear in any output. **P-3** Spatial products are centroids and percent-outside-area only; the 3-vessel confidentiality rule is enforced upstream in the LOTUS views. **P-4** Any LLM call sends only the aggregated table rows for one species (the "evidence packet"), through an agency-approved endpoint.

## 4. Data contract

### 4.1 Input views (LOTUS in production; SQLite in test)

| View | Grain | Required columns |
|---|---|---|
| `species` | species | `species_code, common, sci, group, esa, sector` |
| `ps_interactions_annual` | species × year | `species_code, year, interactions` |
| `ps_effort_annual` | year | `year, sector, observed_sets, total_sets, observed_hooks, total_hooks, coverage_rate` |
| `ps_spatial_annual` | species × year | `species_code, year, centroid_lon, centroid_lat, pct_outside_hist90` |
| `ps_ocean_annual` | species × year × variable | `species_code, year, variable, interaction_env, fleet_env` |
| `ref_its` | species | `species_code, authority, annual_its, its_window_years, window_start_year` |
| `ctx_spatial_effort`, `ctx_gear`, `ctx_fisher_behavior`, `ctx_demographics`, `ctx_climate_indicators` | topic tables | see `data/csv/*.csv` for columns |

**PLACEHOLDER** LOTUS view names in `ps_sql_lotus` (`SAFE_PS.V_*`) are to be confirmed with PIFSC.
**PLACEHOLDER** `ref_its` values are illustrative; replace with governing BiOp values.
**PLACEHOLDER** `ctx_*` tables are transcribed workshop values; the demographic table should become a computed species × year × size-class view.

### 4.2 Output: `pipeline_output.json`

Top-level keys (all required unless noted):

| Key | Content |
|---|---|
| `meta` | `generated, current_year, alpha, mode ("test"\|"lotus"), decision_rule, data_note` |
| `species` | array of species rows |
| `series` | `{code: {years[], interactions[], rate_per_set[]}}` |
| `effort` | effort rows |
| `table2_interactions` | Table 2 rows incl. `gates {robust, percentile, bayes}` and `flag` |
| `table2b_rate_spatial` | Table 2b rows incl. `trend_model, trend_model_flag, centroid_shift_km` |
| `table2c_ocean` | Table 2c rows |
| `bayes` | prior shape/rate, predictive q05/median/q95, `p_tail`, `flagged` |
| `causal` | pre-answered decision-tree nodes + evidence per species |
| `its` | running-sum tracker rows |
| `narratives` | `{species_code, species, flag, narrative, causal_branch, source, provenance}` |
| `aggregation` (optional) | findings and ocean-regime table from the Quarto run |
| `context` | the five `ctx_*` tables |
| `reference` (optional) | the three reference-workbook sheets |
| `provenance` | table → source → confidentiality class |

**P-5** The file must be valid JSON (no `NaN`/`Infinity`; nulls instead). **P-6** Field names are stable across versions; additions are allowed, renames require a version bump of this spec.

## 5. Statistical methods (engine)

All per species, current year vs. historical years (2006–2024 in test data).

| ID | Method | Definition | Notes |
|---|---|---|---|
| E-1 | Rank percentile | 100 × share of historical years strictly below current | scale-free |
| E-2 | Robust anomaly (MAD-z) | (current − median) ÷ (1.4826 × MAD); SD fallback if MAD = 0 | distribution-free |
| E-3 | Long-run slope | Theil–Sen slope of counts on year | Table 2 "trend slope" |
| E-4 | Trend model | log-linear Poisson GLM, offset = log(observed sets); window 5 yr (seabirds, sharks) / 10 yr (turtles); NB if Pearson dispersion > 1.5; on NB failure keep Poisson and set flag "NB fitting error; Poisson fallback" | annual % change = (e^β − 1)·100 |
| E-5 | Bayesian check | Gamma-Poisson conjugate; prior by method of moments (variance-matched if var > 1.05·mean, else shape = Σx, rate = n); posterior predictive NB(r, p = rate/(rate+1)); tail P(X ≥ current) = 1 − I_p(r, current) | validated vs `scipy.stats.nbinom` and R `pnbinom` to 1e-9; JS port agrees to 1e-5 |
| E-6 | Spatial shift | haversine distance historical mean centroid → current centroid; `pct_outside_hist90` passed through | |
| E-7 | Ocean selection anomaly | interaction_env − fleet_env; percentiles of both against history | |
| E-8 | ITS tracker | cumulative fleet-expanded take (observed ÷ coverage; SSLL coverage = 1) over the ITS window vs annual ITS × window; P(exceed before close) from NB predictive for remaining years; alert if > 0.25 | |
| E-9 | OR gate | flag = High if E-2 ≥ 2 **or** E-1 ≥ 90 **or** E-5 < α (0.05); Low if E-2 ≤ −2; else Typical | thresholds are parameters |
| E-10 | Causal pre-answers | higher_than_normal = flag High; fishery_changed = shift > 250 km or outside > 10 %; shifted_into_core = shift > 250 km and outside < 5 %; expected_from_trend = current within predictive 90 %; ocean_changed = any variable ≤ 10th or ≥ 90th percentile; distribution_shift = any selection percentile ≤ 10 or ≥ 90; gear change and year class = expert input | |
| E-11 | Narrative template | rule-based paragraph from Tables 2/2b/2c + causal branch; LLM draft optional (see §8) | |

Known pitfalls to preserve in code comments: spreadsheet `NEGBINOM.DIST` truncates non-integer shape; β-scaler and environmental index must not multiply independently; utility formulas must be scaled by species median.

## 6. Decision-support app requirements

### 6.1 Global

| ID | Requirement |
|---|---|
| A-1 | Single self-contained HTML file; external scripts only from cdnjs/jsdelivr (Chart.js 4.4.1, docx 9.5.1 lazy-loaded). |
| A-2 | Works with embedded example data and with any loaded `pipeline_output.json`; every page re-renders on load. |
| A-3 | Default view is plain-language. A "Show technical details" switch (persisted per browser) reveals statistics, run log, provenance, adjustment sliders. |
| A-4 | Navigation is a task list: Start here → 1 Load → 2 Which species look unusual? → 3 Why might that be? → 4 Check the report tables → 5 Edit the species paragraphs → 6 Create the report section; plus A Check the statistics, B Compare with the take limit, ? Glossary & methods. Established names (Anomaly Detection Dashboard, SAFE Summary Tables, Bayesian Anomaly Tool) appear as subtitles. |
| A-5 | Palette navy `#21295C`, ocean `#065A82`, teal `#1C7293`, orange `#F18F01` (flags/emphasis only); Georgia numerals, Calibri body; no Neptune/GiSdT branding in the app; light and dark themes. |
| A-6 | Terminology: "Pirops"; "Interactions"; "Characterization"; no "Phase 2", "NEW" badges, version numbers or "not yet built" language in the UI. |
| A-7 | No page runs without Chart.js: charts degrade to a note; tables always render. |

### 6.2 Per stage

| Stage | ID | Requirement |
|---|---|---|
| Start here | A-10 | "This year at a glance" in ≤ 5 plain sentences (flags, spatial shifts, ITS use); step checklist with completion state; who-does-what, flag legend, what-to-do-if-wrong. |
| 1 Load | A-11 | File picker for `pipeline_output.json`; validation with a plain error; "Back to example data"; plain summary of what is loaded. Technical: pipeline flow diagram, run status, provenance, run log, inputs table. |
| 2 Unusual? | A-12 | Six species cards: count vs typical, sparkline, three plain gate chips (far from typical / top 10 % / unexpected), flag colour. Selected species: time series with usual range, typical year, expected-this-year bar; plain reading (count, percentile, Bayesian chance, rate agreement, trend, space, ocean); "Work out why →" for flagged species. Context panels: spatial effort, fisher behaviour, gear, ocean chart + climate indicators, demographics. |
| 3 Why? | A-13 | Working-group decision tree as SVG with the walked path highlighted; data-answered nodes pre-filled; expert questions (gear/method change, expected effect, year class) as Yes/No/Not sure buttons; conclusion in plain language; answers written into the species narrative and export. |
| 4 Tables | A-14 | Tables 2, 2b, 2c as they will print; column tooltips; CSV download; technical: toggle to reference-workbook values. |
| 5 Paragraphs | A-15 | Editable draft per species, flagged first, with likely explanation and provenance line; Markdown export. |
| 6 Create | A-16 | Key findings preview; cross-species aggregation table; ocean-regime table; document outline; **Create Word document** (docx built in browser, delivered via `downloads` capability) and **Create Google Doc** (HTML sent to the viewer's Google Drive connector via `mcp`, link returned). Clear messages for declined/unavailable/not-connected. |
| A Statistics | A-17 | Species, cut-off α, baseline window, what-if count; plain result cards (chance of ≥ count in a normal year; expected range; unexpected/not); predictive distribution chart. Technical: prior weight, overdispersion toggle, α-calibration table (historical flag rate). |
| B Take limit | A-18 | LOTUS-anchored calibration: expanded = observed ÷ coverage; one bounded combined factor (β ≤ 2.5, env ± 40 %, gear ± 30 %; combined 0.6–3.0); Gamma take distribution with CV from history (0.15–1.2); P(expanded take > annual ITS); posture banner (within expectation / enhanced monitoring / escalate for review); ITS 5-year running-sum chart; calibration audit listing every factor; demographic penalty curve. Adjustment sliders are technical. |
| ? Glossary | A-19 | Plain definitions for every term; technical method cards; validation checklist; feature notes. |

## 7. Report section (export) requirements

| ID | Requirement |
|---|---|
| X-1 | Single source: `report_module.js` produces a block model (headings, paragraphs, bullets, tables) used by both renderers and by the node sample build. |
| X-2 | Section order: 3.3.2 title and provenance note → **3.3.2.1 Data aggregation and key findings** (computed findings; cross-species aggregation table; ocean regime; climate indicators; fleet dynamics, gear, behaviour; demographics; ITS status; data gaps) → **3.3.2.2 Species accounts** (edited narratives with provenance) → **3.3.2.3 Summary tables** (2, 2b, 2c) → Methods and provenance. |
| X-3 | Key findings are generated from data (flags and gates; count/rate agreement; predictive-interval exceedances; centroid shifts > 250 km; coherent ocean regime; selection anomalies; largest effort shift; ITS status; NB fallbacks; species needing expert input). Editing a finding means editing its source, not the sentence. |
| X-4 | Word: US Letter landscape, Calibri, navy headings, DXA table widths, header row shaded `#DDE7EE`. Google Doc: HTML with inline CSS converted by Drive. |
| X-5 | The Quarto document carries the same aggregation chapter (section 7) and exports the same JSON. |

## 8. LLM narrative drafting (optional)

| ID | Requirement |
|---|---|
| N-1 | Off by default (`params$use_llm = false`); rule-based template otherwise. |
| N-2 | Input is the evidence packet only (Tables 2/2b/2c rows, context rows for that species). |
| N-3 | Endpoint configurable (`params$llm_endpoint`); NOAA analysts use only agency-approved, FedRAMP-authorised or internal platforms. |
| N-4 | Every draft carries a provenance line (model, date, "requires analyst review"). |
| N-5 | Any failure falls back to the template with the error prefixed. |

## 9. Non-functional requirements

- **Reproducibility**: `run_pipeline.sh` rebuilds DB → JSON → app deterministically (seed 2026 for test data).
- **Validation**: engine asserts NB identity against scipy; QA script screenshots every page, exercises Word export, checks console errors = 0.
- **Accessibility**: keyboard-reachable buttons, `aria-pressed` on species cards, focus outlines, reduced-motion respected.
- **Performance**: app < 250 kB excluding CDN libraries; loads in < 2 s on a laptop.
- **Browser**: current Chrome, Edge, Safari, Firefox; mobile layout ≥ 380 px.
- **Sharing**: the published artifact declares `downloads` and `mcp` (Google Drive); it can be shared within the organisation, not by public link.

## 10. Roles and annual workflow

| Step | Who | What |
|---|---|---|
| 1 | PIFSC | Refresh LOTUS aggregated views; run the pipeline (`quarto render … -P use_mock:false`); send `pipeline_output.json`. |
| 2 | Council staff | Load the file; review flags; answer expert questions for flagged species; skim tables; edit paragraphs; create Word/Google Doc. |
| 3 | Neptune / analysts | Maintain engine and app; review technical pages; validate placeholders (§11). |
| 4 | Plan Team | Set gate thresholds and α by structured elicitation (calibration table in page A). |

## 11. Open items before v1.0

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Confirm LOTUS view names and column mapping | PIFSC | open |
| 2 | Replace illustrative ITS values with BiOp values; confirm expanded vs observed basis | PIFSC / Council | open |
| 3 | Validate β scaler, environmental sensitivity, gear multipliers, juvenile share, demographic weight | SMEs | open |
| 4 | Set OR-gate thresholds and α via SDM elicitation | Plan Team | open |
| 5 | Computed size-class view for demographics | PIFSC | open |
| 6 | Confirm 5/10-year trend windows and NB dispersion switch (1.5) | Neptune | open |
| 7 | Approve LLM endpoint or keep template-only | NOAA | open |
| 8 | Interpretation of selection anomaly (distribution shift vs catchability) | J. Wren / SMEs | open |
| 9 | Narrative gaps in SAFE §3.3.2.5 and §3.3.2.6 to be addressed by pipeline outputs | Council staff | open |
| 10 | Decide whether app is hosted as claude.ai artifact, static file, or Council server | Council / Neptune | open |

## 12. Change log

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-09-25 | Test database, Python engine, Quarto document with Gemini chunk, eight-stage app. |
| 0.2 | 2026-09-25 | Word/Google Doc export; computed aggregation chapter (3.3.2.1) in app and Quarto; `report_module.js`. |
| 0.3 | 2026-09-25 | Non-technical edition: Start-here page, task-named steps, plain-language readings, Yes/No expert questions wired into narratives, technical-details switch, glossary, quick-start guide. |

## 13. Acceptance criteria (v1.0)

- [ ] Pipeline runs against LOTUS views with `use_mock:false` and reproduces the reference workbook within rounding for a past year.
- [ ] Only the loggerhead flags on the 2025 test data; flags on real data reviewed by SMEs.
- [ ] Non-technical staff complete steps 1–6 unaided using the quick-start guide (usability check with A. Ishizaki / T. Remington).
- [ ] Every placeholder in §11 resolved or explicitly deferred by the Plan Team.
- [ ] Section 3.3.2 produced by the app accepted into the SAFE report draft without manual retyping of numbers.
