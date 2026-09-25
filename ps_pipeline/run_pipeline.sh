#!/usr/bin/env bash
# End-to-end: build test DB -> run engine -> build app.  (Quarto render is optional: see README.)
set -e
cd "$(dirname "$0")/pipeline"
python3 build_test_db.py --xlsx "${1:-../data/ps_monitoring_tables_AI.xlsx}"
python3 ps_engine.py
python3 build_app.py
echo "Optional: quarto render ../quarto/protected_species_safe_section.qmd -P use_mock:true"
