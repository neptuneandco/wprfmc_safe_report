
library(tidyverse)

# Create test dataframe matching SAFE report structure
ds_its_summary_2024 <- tibble::tribble(
  ~Species, ~Observed_Takes, ~Estimated_Takes, ~Five_Year_ITS, ~Percent_ITS,
  "Olive Ridley Turtle", 14, 70, 161, "43.5%",
  "Green Sea Turtle", 2, 10, 50, "20.0%",
  "Loggerhead Turtle", 1, 5, 25, "20.0%",
  "Oceanic Whitetip Shark", 45, 225, 1020, "22.1%",
  "Giant Manta Ray", 8, 40, 284, "14.1%",
  "False Killer Whale (MHI)", 0, 0, 4, "0.0%"
)

# Ensure output directory exists locally
# dir.create("protected_species", showWarnings = FALSE)

# Save test dataset
saveRDS(ds_its_summary_2024, file = "data/ds_its_summary_2024.rds")
