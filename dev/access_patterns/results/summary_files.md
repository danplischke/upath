## File-object workloads: wall seconds (real sleeps)

### LAN/HPC
| workload | needed | s3fs | gcsfs | adlfs | http | none | bc/1M | bc/16M | auto | hybrid@auto | best (config) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| parquet: footer only | 0MB | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.04 | 0.00 (none) | - | 0.00 (adlfs default) |
| parquet: 2 of 20 cols | 108MB | 1.60 | 0.61 | 1.55 | 0.61 | 0.33 | 0.47 | 1.15 | 0.33 (none) | - | 0.33 (none) |
| parquet: 1 rowgroup, 2 cols | 14MB | 0.41 | 0.10 | 0.40 | 0.09 | 0.06 | 0.08 | 0.26 | 0.06 (none) | - | 0.06 (none) |
| h5ad: obs+var | 78MB | 3.98 | 3.59 | 4.26 | 3.54 | 1.74 | 1.00 | 1.13 | 1.00 (blockcache/1M) | 1.28 (hybrid/1M) | 1.00 (blockcache/1M) |
| h5ad: obsm X_pca (200MB) | 200MB | 2.31 | 1.12 | 2.57 | 1.02 | 0.72 | 1.66 | 0.96 | 1.66 (blockcache/1M) | 0.99 (hybrid/1M) | 0.72 (none) |
| h5ad: X rows slice 2k | 6MB | 2.20 | 0.28 | 2.16 | 0.30 | 0.14 | 0.07 | 0.54 | 0.07 (blockcache/1M) | 0.08 (hybrid/1M) | 0.07 (blockcache/1M) |
| h5ad: X rows random 256 | 53MB | 4.96 | 2.98 | 7.39 | 3.44 | 0.77 | 1.81 | 2.66 | 1.81 (blockcache/1M) | 1.88 (hybrid/1M) | 0.77 (none) |
| h5ad: full load | 1091MB | 11.8 | 8.27 | 14.9 | 10.5 | 11.5 | 6.30 | 5.12 | 6.30 (blockcache/1M) | 6.88 (hybrid/1M) | 5.12 (blockcache/16M) |
| parquet: full read | 1186MB | 6.18 | 5.22 | 8.52 | 5.60 | 4.15 | 6.86 | 6.10 | 4.15 (none) | - | 4.15 (none) |

### cloud same-region
| workload | needed | s3fs | gcsfs | adlfs | http | none | bc/1M | bc/16M | auto | hybrid@auto | best (config) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| parquet: footer only | 0MB | 0.04 | 0.04 | 0.04 | 0.04 | 0.04 | 0.05 | 0.16 | 0.04 (none) | - | 0.04 (s3fs default) |
| parquet: 2 of 20 cols | 108MB | 5.42 | 2.45 | 5.34 | 2.41 | 1.51 | 3.75 | 4.24 | 1.51 (none) | - | 1.51 (none) |
| parquet: 1 rowgroup, 2 cols | 14MB | 1.40 | 0.35 | 1.38 | 0.36 | 0.23 | 0.54 | 0.97 | 0.23 (none) | - | 0.23 (none) |
| h5ad: obs+var | 78MB | 11.8 | 14.2 | 13.1 | 14.3 | 25.3 | 3.46 | 1.94 | 2.17 (auto) | 2.68 (hybrid/4M) | 1.94 (blockcache/16M) |
| h5ad: obsm X_pca (200MB) | 200MB | 7.19 | 3.17 | 8.00 | 3.09 | 2.65 | 12.3 | 3.15 | 6.66 (auto) | 2.76 (hybrid/4M) | 2.65 (none) |
| h5ad: X rows slice 2k | 6MB | 7.44 | 1.40 | 7.50 | 1.42 | 3.73 | 0.59 | 2.01 | 0.91 (auto) | 0.86 (hybrid/4M) | 0.59 (hybrid/1M) |
| h5ad: X rows random 256 | 53MB | 17.6 | 14.7 | 24.2 | 16.3 | 16.9 | 15.3 | 10.4 | 12.9 (auto) | 12.5 (hybrid/4M) | 10.4 (blockcache/16M) |
| h5ad: full load | 1091MB | 38.3 | 32.4 | 46.3 | 43.2 | capped | 41.7 | 16.2 | 24.0 (auto) | 20.4 (hybrid/4M) | 15.1 (all) |
| parquet: full read | 1186MB | 21.3 | 16.1 | 25.6 | 16.9 | 13.9 | 51.1 | 15.5 | 13.9 (none) | - | 13.9 (none) |

### laptop->cloud
| workload | needed | s3fs | gcsfs | adlfs | http | none | bc/1M | bc/16M | auto | hybrid@auto | best (config) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| parquet: footer only | 0MB | 0.09 | 0.09 | 0.09 | 0.09 | 0.09 | 0.14 | 1.02 | 0.09 (none) | - | 0.09 (none) |
| parquet: 2 of 20 cols | 108MB | 40.8 | 17.0 | 56.0 | 16.9 | 9.85 | 15.3 | 30.2 | 9.85 (none) | - | 9.85 (none) |
| parquet: 1 rowgroup, 2 cols | 14MB | 10.2 | 2.20 | 10.1 | 2.20 | 1.33 | 2.09 | 6.84 | 1.33 (none) | - | 1.33 (none) |
| h5ad: obs+var | 78MB | capped | capped | capped | capped | 54.5 | 11.4 | 9.70 | 11.4 (blockcache/1M) | 11.0 (hybrid/1M) | 9.54 (hybrid/16M) |
| h5ad: obsm X_pca (200MB) | 200MB | 53.2 | 21.4 | 59.8 | 21.7 | 17.7 | 50.5 | 22.1 | 50.5 (blockcache/1M) | 17.8 (hybrid/1M) | 17.7 (none) |
| h5ad: X rows slice 2k | 6MB | 58.2 | 8.67 | 58.0 | 8.74 | 7.74 | 2.29 | 14.5 | 2.29 (blockcache/1M) | 2.29 (hybrid/1M) | 2.29 (blockcache/1M) |
| h5ad: X rows random 256 | 53MB | capped | capped | capped | capped | 36.8 | capped | capped | capped (blockcache/1M) | capped (hybrid/1M) | 36.8 (none) |

### cross-continent
| workload | needed | s3fs | gcsfs | adlfs | http | none | bc/1M | bc/16M | auto | hybrid@auto | best (config) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| parquet: footer only | 0MB | 0.31 | 0.30 | 0.30 | 0.30 | 0.30 | 0.33 | 0.76 | 0.30 (none) | - | 0.30 (none) |
| parquet: 2 of 20 cols | 108MB | 21.1 | 10.8 | 29.1 | 10.6 | 7.11 | 23.0 | 17.9 | 7.11 (none) | - | 7.11 (none) |
| parquet: 1 rowgroup, 2 cols | 14MB | 5.56 | 1.60 | 5.59 | 1.60 | 1.17 | 3.30 | 4.15 | 1.17 (none) | - | 1.17 (none) |
| h5ad: obs+var | 78MB | 45.3 | capped | 48.3 | capped | capped | 16.8 | 6.18 | 6.61 (auto) | 6.31 (hybrid/8M) | 6.03 (hybrid/16M) |
| h5ad: obsm X_pca (200MB) | 200MB | 27.3 | 11.9 | 30.9 | 12.3 | 11.5 | capped | 13.1 | 13.6 (auto) | 10.8 (hybrid/8M) | 9.51 (hybrid/1M) |
| h5ad: X rows slice 2k | 6MB | 30.3 | 6.93 | 30.3 | 6.96 | 27.2 | 3.61 | 8.55 | 5.06 (auto) | 5.12 (hybrid/8M) | 3.60 (hybrid/1M) |
| h5ad: X rows random 256 | 53MB | capped | capped | capped | capped | capped | capped | 42.6 | 50.0 (auto) | 50.3 (hybrid/8M) | 42.6 (blockcache/16M) |

### paged h5ad (writer fix) vs default layout, best config each
| profile | workload | default-layout best | paged, page_buf 16M | paged, page_buf 64M |
|---|---|---|---|---|
| LAN | obs+var | 1.00 (blockcache/1M) | 2.02 (28 GETs) | 1.38 (21 GETs) |
| LAN | X rows slice 2k | 0.07 (blockcache/1M) | 2.42 (75 GETs) | 0.98 (73 GETs) |
| LAN | X rows random 256 | 0.77 (none) | 6.37 (252 GETs) | 3.26 (251 GETs) |
| cloud | obs+var | 1.94 (blockcache/16M) | 2.83 (28 GETs) | 2.12 (21 GETs) |
| cloud | X rows slice 2k | 0.59 (hybrid/1M) | 4.85 (75 GETs) | 4.61 (73 GETs) |
| cloud | X rows random 256 | 10.4 (blockcache/16M) | 16.3 (252 GETs) | 16.1 (251 GETs) |
| laptop | obs+var | 9.54 (hybrid/16M) | 12.0 (28 GETs) | 8.76 (21 GETs) |
| laptop | X rows slice 2k | 2.29 (blockcache/1M) | 28.5 (75 GETs) | 27.6 (73 GETs) |
| laptop | X rows random 256 | 36.8 (none) | capped (156 GETs) | capped (155 GETs) |
| x-cont | obs+var | 6.03 (hybrid/16M) | 9.99 (28 GETs) | 7.39 (21 GETs) |
| x-cont | X rows slice 2k | 3.60 (hybrid/1M) | 23.8 (75 GETs) | 23.1 (73 GETs) |
| x-cont | X rows random 256 | 42.6 (blockcache/16M) | capped (188 GETs) | capped (189 GETs) |
