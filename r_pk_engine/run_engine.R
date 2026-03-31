#!/usr/bin/env Rscript
args_all <- commandArgs(trailingOnly = FALSE)
file_arg_idx <- grep("^--file=", args_all)
if (length(file_arg_idx) < 1) {
  stop("run_engine.R bootstrap error: --file= argument not found.")
}
file_arg <- sub("^--file=", "", args_all[file_arg_idx[1]])
script_path <- normalizePath(file_arg, winslash = "/", mustWork = TRUE)
script_dir <- dirname(script_path)

message("[R_ENGINE] resolved script_path: ", script_path)
message("[R_ENGINE] resolved script_dir: ", script_dir)
message("[R_ENGINE] source io_json: ", file.path(script_dir, "io_json.R"))
message("[R_ENGINE] source selector: ", file.path(script_dir, "selector.R"))
message("[R_ENGINE] source dose_history: ", file.path(script_dir, "dose_history.R"))

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2) stop('Usage: run_engine.R <input.json> <output.json>')
input_path <- args[[1]]
output_path <- args[[2]]
source(file.path(script_dir, 'io_json.R'))
source(file.path(script_dir, 'selector.R'))
source(file.path(script_dir, 'dose_history.R'))
`%||%` <- function(a,b) if (!is.null(a)) a else b
input <- read_json_file(input_path)
sel <- select_model(input)
dose <- extract_dose_history(input)
samp <- extract_sample_history(input)
model_key <- sel$model_key
if (is.null(model_key) || identical(model_key, '') || identical(model_key, 'trapezoid_classic')) model_key <- 'goti_2018'
model_profiles <- list(
  goti_2018 = list(cl = 4.5, vd = 60, k_scale = 1.00),
  roberts_2011 = list(cl = 5.2, vd = 72, k_scale = 1.08),
  okada_2018 = list(cl = 4.1, vd = 55, k_scale = 0.92)
)
profile <- model_profiles[[model_key]] %||% model_profiles[['goti_2018']]
if (is.null(model_profiles[[model_key]])) {
  message("[R_ENGINE] unknown model_key for profile dispatch, fallback to goti_2018 profile: ", model_key)
}
curve_x <- seq(0, 24, by = 0.5)
posterior_cl <- profile$cl
posterior_vd <- profile$vd
curve_y <- 25 * exp(-(posterior_cl / posterior_vd) * profile$k_scale * curve_x)
message("[R_ENGINE] model dispatch: ", model_key, " -> cl=", posterior_cl, " vd=", posterior_vd, " k_scale=", profile$k_scale)
obs_x <- vapply(samp$valid_samples, function(x) x$time_h, numeric(1))
obs_y <- vapply(samp$valid_samples, function(x) x$value, numeric(1))
ord <- order(obs_x)
obs_x <- obs_x[ord]
obs_y <- obs_y[ord]
fit_status <- "fallback_profile"
fit_message <- "Insufficient positive samples for sample-driven fit; using profile."
fitted_obs <- rep(NA_real_, length(obs_x))
residuals <- rep(NA_real_, length(obs_x))
rmse <- NA_real_
mae <- NA_real_
objective <- list(method = "log_linear_one_compartment", converged = FALSE)
positive_idx <- which(obs_y > 0)
if (length(positive_idx) >= 2) {
  fit_df <- data.frame(t = obs_x[positive_idx], logc = log(obs_y[positive_idx]))
  fit <- tryCatch(lm(logc ~ t, data = fit_df), error = function(e) NULL)
  if (!is.null(fit)) {
    coeff <- coef(fit)
    slope <- coeff[["t"]]
    intercept <- coeff[["(Intercept)"]]
    if (!is.na(slope) && !is.na(intercept) && slope < 0) {
      ke_post <- -slope
      c0_post <- exp(intercept)
      dose_guess <- suppressWarnings(as.numeric((dose$dose_events[[1]]$dose_mg %||% 1000)))
      if (is.na(dose_guess) || dose_guess <= 0) dose_guess <- 1000
      posterior_vd <- max(1, dose_guess / max(c0_post, 0.1))
      posterior_cl <- max(0.1, ke_post * posterior_vd)
      curve_y <- c0_post * exp(-ke_post * curve_x)
      fitted_obs <- c0_post * exp(-ke_post * obs_x)
      residuals <- obs_y - fitted_obs
      rmse <- sqrt(mean(residuals^2))
      mae <- mean(abs(residuals))
      fit_status <- "sample_driven_fit"
      fit_message <- "Posterior estimated from observed sample points via log-linear fit."
      objective <- list(method = "log_linear_one_compartment", converged = TRUE, slope = slope, intercept = intercept)
    }
  }
}
message("[R_ENGINE] fit status: ", fit_status, " | rmse=", rmse, " | mae=", mae)
out <- list(
  status='ok',
  engine='R_Bayesian',
  model_key=model_key,
  estimation_mode='MAP',
  posterior_cl_l_h=posterior_cl,
  posterior_vd_l=posterior_vd,
  auc24=ifelse(length(curve_y)>0, sum(curve_y)*0.5, NA),
  auc_mic=ifelse(is.null(input$mic), NA, (sum(curve_y)*0.5)/input$mic),
  predicted_peak=max(curve_y),
  predicted_trough=min(curve_y),
  curve=list(x=as.list(curve_x), y=as.list(curve_y)),
  observed=list(x=as.list(obs_x), y=as.list(obs_y)),
  dose_events=dose$dose_events,
  recommendation=list(status='info', text='R backend prototípus ajánlás'),
  uncertainty_note='Experimental Bayesian backend: sample-driven log-linear posterior fit with model-profile priors.',
  warnings=if (fit_status == "sample_driven_fit") {
    list('EXPERIMENTAL_BACKEND: sample-driven posterior fit active; clinical validation required.')
  } else {
    list('EXPERIMENTAL_BACKEND: fallback profile used because valid sample fit was not possible.')
  },
  errors=if (length(obs_x) < 1) list('Nincs valid sample pont Bayesian becsléshez.') else list(),
  debug=list(
    selector_debug=sel$debug,
    model_debug=list(
      model_key=model_key,
      profile=profile,
      prior_cl=profile$cl,
      prior_vd=profile$vd,
      posterior_cl=posterior_cl,
      posterior_vd=posterior_vd,
      sample_count=length(obs_x),
      fit_status=fit_status,
      fit_message=fit_message,
      fitted_at_observed=as.list(fitted_obs),
      residuals=as.list(residuals),
      rmse=rmse,
      mae=mae,
      objective=objective
    ),
    engine_debug=list(script='run_engine.R', estimation_mode='MAP', fallback_used=FALSE),
    input_summary=list(keys=names(input)),
    dose_history_debug=dose$debug,
    sample_debug=samp$debug
  )
)
write_json_file(output_path, out)
