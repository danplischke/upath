| workload | LAN/HPC | cloud same-region | laptop->cloud | cross-continent |
|---|---|---|---|---|
| h5ad: obs+var | s3fs 3.98 · gcsfs 3.59 → **1.28** (best 1.00) | s3fs 11.8 · gcsfs 14.2 → **2.68** (best 1.94) | s3fs >60 · gcsfs >60 → **11.0** (best 9.54) | s3fs 45.3 · gcsfs >60 → **6.31** (best 6.03) |
| h5ad: obsm X_pca (200MB) | s3fs 2.31 · gcsfs 1.12 → **0.99** (best 0.72) | s3fs 7.19 · gcsfs 3.17 → **2.76** (best 2.65) | s3fs 53.2 · gcsfs 21.4 → **17.8** (best 17.7) | s3fs 27.3 · gcsfs 11.9 → **10.8** (best 9.51) |
| h5ad: X rows slice 2k | s3fs 2.20 · gcsfs 0.28 → **0.08** (best 0.07) | s3fs 7.44 · gcsfs 1.40 → **0.86** (best 0.59) | s3fs 58.2 · gcsfs 8.67 → **2.29** (best 2.29) | s3fs 30.3 · gcsfs 6.93 → **5.12** (best 3.60) |
| h5ad: X rows random 256 | s3fs 4.96 · gcsfs 2.98 → **1.88** (best 0.77) | s3fs 17.6 · gcsfs 14.7 → **12.5** (best 10.4) | s3fs >60 · gcsfs >60 → **>60** (best 36.8) | s3fs >60 · gcsfs >60 → **50.3** (best 42.6) |
| h5ad: full load | s3fs 11.8 · gcsfs 8.27 → **6.88** (best 5.12) | s3fs 38.3 · gcsfs 32.4 → **20.4** (best 15.1) | – | – |
| parquet: 2 of 20 cols | s3fs 1.60 · gcsfs 0.61 → **0.33** (best 0.33) | s3fs 5.42 · gcsfs 2.45 → **1.51** (best 1.51) | s3fs 40.8 · gcsfs 17.0 → **9.85** (best 9.85) | s3fs 21.1 · gcsfs 10.8 → **7.11** (best 7.11) |
| parquet: 1 rowgroup, 2 cols | s3fs 0.41 · gcsfs 0.10 → **0.06** (best 0.06) | s3fs 1.40 · gcsfs 0.35 → **0.23** (best 0.23) | s3fs 10.2 · gcsfs 2.20 → **1.33** (best 1.33) | s3fs 5.56 · gcsfs 1.60 → **1.17** (best 1.17) |
| parquet: full read | s3fs 6.18 · gcsfs 5.22 → **4.15** (best 4.15) | s3fs 21.3 · gcsfs 16.1 → **13.9** (best 13.9) | – | – |
