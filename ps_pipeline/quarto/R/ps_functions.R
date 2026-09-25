# ps_functions.R --------------------------------------------------------------
# Helper functions for the SAFE protected-species pipeline. Mirrors
# pipeline/ps_engine.py one-for-one so the two can be cross-validated.
#
# Dependencies: DBI, RSQLite (test mode) or odbc (LOTUS), dplyr, tidyr, MASS,
#               purrr, jsonlite, httr2 (narrative chunk only)

# ---- data access -------------------------------------------------------------

#' Open a connection to LOTUS (aggregated views) or the SQLite test database.
ps_connect <- function(use_mock = TRUE, sqlite_path = "../data/ps_monitoring_test.sqlite",
                       dsn = Sys.getenv("LOTUS_DSN"), uid = Sys.getenv("LOTUS_UID"),
                       pwd = Sys.getenv("LOTUS_PWD")) {
  if (use_mock) {
    DBI::dbConnect(RSQLite::SQLite(), sqlite_path)
  } else {
    DBI::dbConnect(odbc::odbc(), dsn = dsn, uid = uid, pwd = pwd)
  }
}

# Every query below returns AGGREGATED rows only (species x year, or
# species x year x stratum). No set-level or vessel-level records leave NOAA.
ps_sql <- list(
  species      = "SELECT * FROM species",
  interactions = "SELECT species_code, year, interactions FROM ps_interactions_annual ORDER BY species_code, year",
  effort       = "SELECT * FROM ps_effort_annual ORDER BY year",
  spatial      = "SELECT * FROM ps_spatial_annual",
  ocean        = "SELECT * FROM ps_ocean_annual",
  its          = "SELECT * FROM ref_its",
  ctx_spatial  = "SELECT * FROM ctx_spatial_effort",
  ctx_gear     = "SELECT * FROM ctx_gear",
  ctx_behavior = "SELECT * FROM ctx_fisher_behavior",
  ctx_demo     = "SELECT * FROM ctx_demographics",
  ctx_climate  = "SELECT * FROM ctx_climate_indicators"
)

# In LOTUS mode the same names map to the schema-qualified aggregated views
# that PIFSC exposes for the pipeline (names are placeholders to be confirmed).
ps_sql_lotus <- list(
  species      = "SELECT * FROM SAFE_PS.SPECIES_LOOKUP",
  interactions = "SELECT SPECIES_CODE AS species_code, FISHING_YEAR AS year, N_INTERACTIONS AS interactions
                  FROM SAFE_PS.V_PS_INTERACTIONS_ANNUAL ORDER BY 1,2",
  effort       = "SELECT FISHING_YEAR AS year, SECTOR AS sector, OBS_SETS AS observed_sets, TOTAL_SETS AS total_sets,
                  OBS_HOOKS AS observed_hooks, TOTAL_HOOKS AS total_hooks, COVERAGE AS coverage_rate, OBS_TRIPS AS observed_trips
                  FROM SAFE_PS.V_EFFORT_ANNUAL ORDER BY 1",
  spatial      = "SELECT SPECIES_CODE AS species_code, FISHING_YEAR AS year, CENTROID_LON AS centroid_lon,
                  CENTROID_LAT AS centroid_lat, PCT_OUTSIDE_HIST90 AS pct_outside_hist90 FROM SAFE_PS.V_PS_CENTROID_ANNUAL",
  ocean        = "SELECT SPECIES_CODE AS species_code, FISHING_YEAR AS year, VARIABLE AS variable,
                  INTERACTION_ENV AS interaction_env, FLEET_ENV AS fleet_env FROM SAFE_PS.V_PS_OCEAN_ANNUAL",
  its          = "SELECT * FROM SAFE_PS.REF_ITS"
)

ps_read <- function(con, name, use_mock = TRUE) {
  sql <- if (use_mock) ps_sql[[name]] else (ps_sql_lotus[[name]] %||% ps_sql[[name]])
  DBI::dbGetQuery(con, sql)
}
`%||%` <- function(a, b) if (is.null(a)) b else a

# ---- statistics -------------------------------------------------------------

#' MAD-based z score of the current value against the historical series.
mad_z <- function(x_hist, x_cur) {
  med <- median(x_hist); mad <- stats::mad(x_hist, constant = 1.4826)
  if (mad == 0) mad <- sd(x_hist); if (is.na(mad) || mad == 0) mad <- 1
  (x_cur - med) / mad
}

#' Share of historical years strictly below the current value (0-100).
percentile_rank <- function(x_hist, x_cur) 100 * mean(x_hist < x_cur)

#' Theil-Sen slope (robust linear trend in count units per year).
theil_sen <- function(years, counts) {
  ij <- combn(length(years), 2)
  median((counts[ij[2, ]] - counts[ij[1, ]]) / (years[ij[2, ]] - years[ij[1, ]]))
}

#' Poisson GLM (log-link, optional offset) with NB upgrade when overdispersed.
fit_trend <- function(years, counts, offset = NULL) {
  df <- data.frame(y = counts, t = years - min(years), off = if (is.null(offset)) 0 else log(offset))
  model <- "Poisson"; flag <- "Preferred model"; b <- NA_real_
  pm <- tryCatch(glm(y ~ t + offset(off), family = poisson, data = df), error = function(e) NULL)
  if (!is.null(pm)) {
    b <- coef(pm)[["t"]]
    disp <- sum(residuals(pm, type = "pearson")^2) / pm$df.residual
    if (is.finite(disp) && disp > 1.5) {
      nb <- tryCatch(suppressWarnings(MASS::glm.nb(y ~ t + offset(off), data = df)), error = function(e) NULL)
      if (!is.null(nb) && is.finite(coef(nb)[["t"]])) { b <- coef(nb)[["t"]]; model <- "Negative binomial" }
      else flag <- "NB fitting error; Poisson fallback"
    }
  } else { model <- "none"; flag <- "GLM failed" }
  list(slope_log = b, annual_pct_change = (exp(b) - 1) * 100, model = model, model_flag = flag)
}

#' Method-of-moments Gamma prior on the annual mean (overdispersion aware).
gamma_poisson_prior <- function(x_hist) {
  m <- mean(x_hist); v <- var(x_hist)
  if (v > m * 1.05) c(shape = m^2 / (v - m), rate = m / (v - m))
  else               c(shape = sum(x_hist),    rate = length(x_hist))
}

#' P(X >= x_cur) under the NegBin posterior predictive. R's pnbinom accepts a
#' non-integer size, so we call it directly; the incomplete-beta identity
#' I_p(r, k+1) = P(X <= k) is used in the JS/Python ports and spreadsheets.
nb_tail_prob <- function(shape, rate, x_cur) {
  p <- rate / (rate + 1)
  if (x_cur <= 0) return(1)
  1 - pbeta(p, shape, x_cur)          # == 1 - pnbinom(x_cur - 1, size = shape, prob = p)
}
nb_quantiles <- function(shape, rate, q = c(.05, .5, .95)) qnbinom(q, size = shape, prob = rate / (rate + 1))

haversine_km <- function(lon1, lat1, lon2, lat2) {
  r <- 6371; to_rad <- pi / 180
  dlat <- (lat2 - lat1) * to_rad; dlon <- (lon2 - lon1) * to_rad
  a <- sin(dlat / 2)^2 + cos(lat1 * to_rad) * cos(lat2 * to_rad) * sin(dlon / 2)^2
  2 * r * asin(sqrt(a))
}

# ---- OR-gate decision rule --------------------------------------------------

#' The anomaly decision. Any one gate firing flags the species as "High".
or_gate <- function(robust, percentile, p_tail, alpha = 0.05,
                    robust_thr = 2, pct_thr = 90) {
  gates <- c(robust = robust >= robust_thr, percentile = percentile >= pct_thr, bayes = p_tail < alpha)
  flag <- if (any(gates)) "High" else if (robust <= -robust_thr) "Low" else "Typical"
  list(flag = flag, gates = gates)
}

# ---- rule-based narrative fallback (used when the LLM chunk is disabled) ---
template_narrative <- function(r2, r2b, oc) {
  ocean_txt <- oc |>
    dplyr::mutate(txt = sprintf("%s at the %.0fth percentile", variable, interaction_percentile)) |>
    dplyr::pull(txt) |> paste(collapse = ", ")
  sprintf(paste0(
    "%s (%+.2f): %d interactions were observed in %d against a historical median of %d ",
    "(%.0fth percentile). The interaction rate anomaly was %+.2f (%.0fth percentile) with a %.1f%% annual ",
    "%s trend over the last %d years (%s). The interaction centroid moved %.0f km and %.1f%% of interactions ",
    "fell outside the historical 90%% area. Ocean context: %s."),
    r2$flag, r2$robust_anomaly, r2$current, r2$year, as.integer(r2$median), r2$percentile,
    r2b$rate_robust_anomaly, r2b$rate_percentile, abs(r2b$annual_pct_change),
    tolower(r2b$trend), r2b$trend_years, r2b$trend_model, r2b$centroid_shift_km,
    r2b$pct_outside_hist90, ocean_txt)
}
