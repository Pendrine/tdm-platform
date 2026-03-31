read_json_file <- function(path) {
  txt <- paste(readLines(path, warn = FALSE, encoding = 'UTF-8'), collapse='\n')
  jsonlite::fromJSON(txt, simplifyVector = FALSE)
}
write_json_file <- function(path, obj) {
  json <- jsonlite::toJSON(obj, auto_unbox = TRUE, null = 'null', pretty = TRUE)
  writeLines(json, path, useBytes = TRUE)
}
