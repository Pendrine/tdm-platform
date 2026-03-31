select_model <- function(input) {
  manual <- input$selected_model_key
  if (!is.null(manual) && nzchar(manual) && manual != 'trapezoid_classic') {
    return(list(model_key = manual, debug = list(reason = 'manual_override', eligible = c('goti_2018','roberts_2011','okada_2018'))))
  }
  hsct <- isTRUE(input$patient$hsct)
  icu <- isTRUE(input$patient$icu)
  model_key <- if (hsct) 'okada_2018' else if (icu) 'roberts_2011' else 'goti_2018'
  list(model_key = model_key, debug = list(reason = 'rule_based', hsct = hsct, icu = icu, eligible = c('goti_2018','roberts_2011','okada_2018')))
}
