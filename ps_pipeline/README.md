# Protected Species SAFE Pipeline — test build

Working-session deliverable: an automated pipeline from aggregated LOTUS outputs to the SAFE
protected-species section (Pelagic FEP §3.3.2) and a decision-support web app.

```
ps_pipeline/
├── run_pipeline.sh                 one command: test DB → engine → app
├── data/
│   ├── ps_monitoring_tables_AI.xlsx   reference summary tables (source of truth)
│   ├── ps_monitoring_test.sqlite      TEST DATABASE (aggregated views + reference tables)
│   ├── csv/                           CSV mirror of every table
│   └── pipeline_output.json           engine output consumed by the app
├── pipeline/
│   ├── build_test_db.py            synthesises annual series calibrated to the xlsx, loads context tables
│   ├── ps_engine.py                Python reference engine (validated vs scipy); writes pipeline_output.json
│   └── build_app.py                injects the JSON into the app template
├── quarto/
│   ├── protected_species_safe_section.qmd   the SAFE section: Tables 2/2b/2c, Bayesian check, OR gate,
│   │                                        context tables, ITS tracker, Gemini narrative chunk, JSON export
│   └── R/ps_functions.R                     helpers mirroring ps_engine.py (DBI/odbc or RSQLite)
└── app/
    ├── Protected_Species_Decision_Support.html   single-file decision-support app (also published as artifact)
    └── template_*.html                           head / body / script pieces used by build_app.py
```

## Test database (SQLite)

| table | grain | notes |
|---|---|---|
| `species` | species | codes, common/scientific names, ESA status, sector |
| `ps_interactions_annual` | species × year (2006–2025) | synthetic; calibrated so mean/median/P10/P90 ≈ reference |
| `ps_effort_annual` | year | observed/total sets & hooks, coverage (2025 = 1,166 observed sets, implied by the reference rates) |
| `ps_spatial_annual` | species × year | interaction centroid, % outside historical 90 % area |
| `ps_ocean_annual` | species × year × variable | interaction-weighted and fleet-weighted environment |
| `ctx_spatial_effort`, `ctx_gear`, `ctx_fisher_behavior`, `ctx_demographics`, `ctx_climate_indicators` | — | the four workshop review areas (illustrative values from the topic tables) |
| `ref_its` | species | **illustrative** ITS values — replace with BiOp values |
| `ref_summary_interactions`, `ref_summary_rate_spatial`, `ref_summary_ocean` | — | the three sheets of the reference workbook, verbatim |
| `provenance` | table | source and confidentiality class of every table |

Nothing in the database is set-level or vessel-level.

## Running

```bash
./run_pipeline.sh                       # Python path (no R needed)
quarto render quarto/protected_species_safe_section.qmd -P use_mock:true          # test DB
quarto render quarto/protected_species_safe_section.qmd -P use_mock:false         # LOTUS via LOTUS_DSN/UID/PWD
quarto render quarto/protected_species_safe_section.qmd -P use_llm:true           # + Gemini narrative drafts
```

R packages: DBI, RSQLite, odbc, dplyr, tidyr, purrr, gt, ggplot2, MASS, jsonlite, httr2.
The Gemini chunk needs `GEMINI_API_KEY`; set `params$llm_endpoint` to an agency-approved
(FedRAMP / Vertex AI) endpoint before use. Only aggregated table rows are sent.

## SAFE section export

Stage 8 of the app assembles §3.3.2 (aggregation chapter → species accounts → Tables 2/2b/2c → methods)
from `pipeline_output.json` and your edited narratives. **Create Word document** builds the .docx in the
browser (`docx` library) and hands it to you through the artifact `downloads` capability; **Create Google
Doc** sends the same content as HTML to your Google Drive connector, which converts it to a Google Doc and
returns the link. `app/report_module.js` is the single source for both, and `qa/build_sample_docx.js`
builds the same document from node. The Quarto document carries the same aggregation chapter (section 7).

## Decision rule

`High` if **any** gate fires: MAD-z ≥ 2, or rank percentile ≥ 90, or Gamma-Poisson tail probability
P(X ≥ current) < α (0.05). On the test data only the loggerhead turtle flags (percentile and Bayesian
gates), matching the reference workbook.

## Placeholders needing SME validation

ITS values · β reporting-bias scaler · environmental-sensitivity coefficient · gear/hook multipliers ·
juvenile share of take · gate thresholds and α (use the calibration table in the Bayesian tab) ·
LOTUS view names in `ps_sql_lotus`.
