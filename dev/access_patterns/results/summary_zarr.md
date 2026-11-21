
## zarr: wall seconds by concurrency (real sleeps)

| workload | profile | C=10 (default) | C=64 | C* formula | GETs | MB |
|---|---|---|---|---|---|---|
| 256KiB chunks (4096 objects): 2048x2048 region (16MiB) | LAN | 0.03 | 0.02 | 0.06 (C=6) | 82 | 21 |
| 256KiB chunks (4096 objects): full read (1GiB) | LAN | 1.55 | 1.09 | 3.20 (C=6) | 4097 | 1074 |
| 4MiB chunks (256 objects): 2048x2048 region (16MiB) | LAN | 0.04 | 0.04 | 0.07 (C=4) | 10 | 38 |
| 4MiB chunks (256 objects): full read (1GiB) | LAN | 0.87 | 0.87 | 1.90 (C=4) | 257 | 1074 |
| 64MiB shards / 256KiB inner: 2048x2048 region (16MiB) | LAN | 0.04 | 0.04 | 0.05 (C=6) | 11 | 23 |
| 64MiB shards / 256KiB inner: full read (1GiB) | LAN | 1.93 | 1.92 | 2.94 (C=4) | 17 | 1074 |
| anndata-zarr: obs+var | LAN | 0.70 | 0.51 | - | 18 | 20 |
| anndata-zarr: X rows slice 2k | LAN | 0.05 | 0.04 | - | 8 | 4 |
| anndata-zarr: X rows random 256 | LAN | 0.43 | 0.43 | - | 61 | 182 |
| 256KiB chunks (4096 objects): 2048x2048 region (16MiB) | cloud | 0.25 | 0.08 | 0.06 (C=108) | 82 | 21 |
| 256KiB chunks (4096 objects): full read (1GiB) | cloud | 11.2 | 2.04 | 1.30 (C=108) | 4097 | 1074 |
| 4MiB chunks (256 objects): 2048x2048 region (16MiB) | cloud | 0.10 | 0.10 | 0.10 (C=19) | 10 | 38 |
| 4MiB chunks (256 objects): full read (1GiB) | cloud | 2.46 | 0.92 | 1.39 (C=19) | 257 | 1074 |
| 64MiB shards / 256KiB inner: 2048x2048 region (16MiB) | cloud | 0.15 | 0.15 | 0.14 (C=108) | 11 | 23 |
| 64MiB shards / 256KiB inner: full read (1GiB) | cloud | 3.46 | 3.15 | 3.32 (C=13) | 17 | 1074 |
| anndata-zarr: obs+var | cloud | 1.07 | 1.02 | - | 18 | 20 |
| anndata-zarr: X rows slice 2k | cloud | 0.20 | 0.20 | - | 8 | 4 |
| anndata-zarr: X rows random 256 | cloud | 0.83 | 0.82 | - | 61 | 182 |
| 256KiB chunks (4096 objects): 2048x2048 region (16MiB) | laptop | 1.86 | 1.86 | 1.86 (C=3) | 82 | 21 |
| 4MiB chunks (256 objects): 2048x2048 region (16MiB) | laptop | 3.23 | 3.23 | 3.23 (C=2) | 10 | 38 |
| 64MiB shards / 256KiB inner: 2048x2048 region (16MiB) | laptop | 2.10 | 2.10 | 2.09 (C=3) | 11 | 23 |
| anndata-zarr: obs+var | laptop | 2.87 | 2.90 | - | 18 | 20 |
| anndata-zarr: X rows slice 2k | laptop | 0.68 | 0.67 | - | 8 | 4 |
| anndata-zarr: X rows random 256 | laptop | 15.8 | 15.7 | - | 61 | 182 |
| 256KiB chunks (4096 objects): 2048x2048 region (16MiB) | x-cont | 1.62 | 0.52 | 0.52 (C=62) | 82 | 21 |
| 256KiB chunks (4096 objects): full read (1GiB) | x-cont | 72.7 | 11.5 | 13.9 (C=62) | 4097 | 1074 |
| 4MiB chunks (256 objects): 2048x2048 region (16MiB) | x-cont | 0.68 | 0.68 | 0.91 (C=8) | 10 | 38 |
| 4MiB chunks (256 objects): full read (1GiB) | x-cont | 11.1 | 11.1 | 12.5 (C=8) | 257 | 1074 |
| 64MiB shards / 256KiB inner: 2048x2048 region (16MiB) | x-cont | 0.71 | 0.71 | 0.71 (C=62) | 11 | 23 |
| 64MiB shards / 256KiB inner: full read (1GiB) | x-cont | 11.2 | 11.2 | 15.4 (C=5) | 17 | 1074 |
| anndata-zarr: obs+var | x-cont | 4.06 | 4.06 | - | 18 | 20 |
| anndata-zarr: X rows slice 2k | x-cont | 1.17 | 1.17 | - | 8 | 4 |
| anndata-zarr: X rows random 256 | x-cont | 3.20 | 3.24 | - | 61 | 182 |
