extract_dose_history <- function(input) {
  events <- input$episode_events %||% list()
  dose_events <- Filter(function(e) grepl('dose', tolower(e$event_type %||% '')), events)
  list(
    dose_events = dose_events,
    debug = list(total_dose_events = length(dose_events), used_event_types = lapply(dose_events, function(e) e$event_type))
  )
}
extract_sample_history <- function(input) {
  events <- input$episode_events %||% list()
  samples <- Filter(function(e) tolower(e$event_type %||% '') == 'sample', events)
  valid <- Filter(function(s) !is.null(s$level_mg_l) && !is.na(suppressWarnings(as.numeric(s$level_mg_l))), samples)
  valid_samples <- lapply(valid, function(s) list(time_h=as.numeric(s$time_h %||% 0), value=as.numeric(s$level_mg_l)))
  list(valid_samples = valid_samples, debug = list(total_samples = length(samples), valid_samples = length(valid_samples)))
}
`%||%` <- function(a,b) if (!is.null(a)) a else b
