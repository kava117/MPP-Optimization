# keyplayer_analysis.R
# ─────────────────────────────────────────────────────────────────────────────
# Finds k=5 key players for KPP-Neg and KPP-Pos on driving and walking
# adjacency matrices using the keyplayer package (An & Liu 2016, based on
# Borgatti 2006).
#
# Search strategy: greedy with random restarts (seed="random", round=50).
# This is the package's built-in optimizer — there is no GA option.
#
# KPP-Neg → type="fragment", method="min"
#   Nodes whose removal most fragments the network.
#
# KPP-Pos → type="mreach.degree", method="max", M=2
#   Nodes that collectively reach the most other nodes within 2 hops.
#   M=2 is meaningful here: "which centers can serve neighbors within
#   2 connections?" With M=Inf on a connected graph all nodes tie at n-1.
#
# Outputs 4 CSVs:
#   keyplayer_{matrix}_{type}.csv  (columns: name, rank, centrality_score)
#
# Within-set rank uses each node's individual kpcent() score: rank 1 = most
# important individually, rank 5 = least important within the set.
# ─────────────────────────────────────────────────────────────────────────────

if (!requireNamespace("keyplayer", quietly = TRUE)) {
  message("Installing keyplayer package...")
  install.packages("keyplayer", repos = "https://cran.r-project.org")
}
library(keyplayer)

K      <- 5
ROUNDS <- 50   # random-restart rounds for quality; increase for better results
SEED_R <- 42   # R RNG seed for reproducibility

# Scenario definitions: label, kpset type, kpset method, kpcent method, M
SCENARIOS <- list(
  list(label = "fragment",     type = "fragment",      method = "min", M = Inf),
  list(label = "mreach",       type = "mreach.degree", method = "max", M = 2L)
)

read_matrix <- function(matrix_csv) {
  df        <- read.csv(matrix_csv, check.names = FALSE)
  row_names <- make.unique(as.character(df[[1]]))  # handles duplicate names
  df        <- df[, -1, drop = FALSE]
  mat       <- as.matrix(df)
  rownames(mat) <- row_names
  colnames(mat) <- row_names
  mat
}

run_scenario <- function(mat, scenario, matrix_label) {
  cat(sprintf("\n[%s | %s]\n", matrix_label, scenario$label))

  mat_bin        <- (mat > 0) * 1L
  diag(mat_bin)  <- 0L
  storage.mode(mat_bin) <- "integer"
  n <- nrow(mat_bin)
  cat(sprintf("  Nodes: %d\n", n))

  # ── Find key player set ────────────────────────────────────────────────────
  cat(sprintf("  Running kpset (round=%d, seed=random)...\n", ROUNDS))
  set.seed(SEED_R)
  kp_result  <- kpset(
    mat_bin,
    size      = K,
    type      = scenario$type,
    M         = scenario$M,
    method    = scenario$method,
    seed      = "random",
    round     = ROUNDS,
    iteration = n
  )
  kp_indices <- kp_result$keyplayers   # 1-based R indices
  kp_cent    <- kp_result$centrality

  node_names <- rownames(mat_bin)
  cat(sprintf("  Set centrality : %.4f\n", kp_cent))
  cat(sprintf("  Indices        : %s\n",   paste(kp_indices, collapse = ", ")))
  cat(sprintf("  Names          : %s\n",   paste(node_names[kp_indices], collapse = ", ")))

  # ── Individual scores for within-set ranking ───────────────────────────────
  cat("  Computing individual kpcent scores for ranking...\n")
  kp_ind_scores <- sapply(kp_indices, function(i) {
    kpcent(mat_bin, nodes = i, type = scenario$type, M = scenario$M,
           method = scenario$method)
  })

  kp_names  <- node_names[kp_indices]
  kp_ranks  <- rank(-kp_ind_scores, ties.method = "first")

  result_df <- data.frame(
    name             = kp_names,
    rank             = as.integer(kp_ranks),
    centrality_score = round(kp_ind_scores, 6),
    stringsAsFactors = FALSE
  )
  result_df <- result_df[order(result_df$rank), ]

  cat("  Ranked key players:\n")
  for (i in seq_len(nrow(result_df))) {
    r <- result_df[i, ]
    cat(sprintf("    #%d  %-45s  score=%.4f\n", r$rank, r$name, r$centrality_score))
  }

  result_df
}

matrices <- list(
  list(csv = "driving_matrix.csv", label = "driving"),
  list(csv = "walking_matrix.csv", label = "walking")
)

for (m in matrices) {
  mat <- read_matrix(m$csv)
  for (sc in SCENARIOS) {
    result   <- run_scenario(mat, sc, m$label)
    out_file <- sprintf("keyplayer_%s_%s.csv", m$label, sc$label)
    write.csv(result, out_file, row.names = FALSE)
    cat(sprintf("  Saved: %s\n", out_file))
  }
}

cat("\nR analysis complete.\n")
