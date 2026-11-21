"""Generate ~150-350 MB files of other formats read through file objects."""

import os
import sys
import warnings

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.orc as orc
import tifffile
from astropy.io import fits
from scipy.io import netcdf_file

warnings.filterwarnings("ignore")
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(0)

# tiled, compressed GeoTIFF-like image (COG layout: tiles + overview pages)
y, x = np.mgrid[0:12000, 0:12000]
img = ((np.sin(x / 300) + np.cos(y / 200)) * 8000 + 20000).astype(np.uint16)
img += rng.integers(0, 64, img.shape, dtype=np.uint16)
with tifffile.TiffWriter(f"{OUT}/image.tif") as tw:
    tw.write(img, tile=(512, 512), compression="zlib", subifds=2)
    tw.write(img[::2, ::2], tile=(512, 512), compression="zlib", subfiletype=1)
    tw.write(img[::4, ::4], tile=(512, 512), compression="zlib", subfiletype=1)
del y, x

# tables: 2M rows x 20 cols
n = 2_000_000
cols = {f"f{i}": rng.random(n) for i in range(16)}
cols |= {f"i{i}": rng.integers(0, 1_000_000, n) for i in range(3)}
cols["s"] = pa.array(rng.choice(["alpha", "beta", "gamma", "delta"], n))
table = pa.table(cols)
feather.write_feather(table, f"{OUT}/table.feather", compression="uncompressed")
orc.write_table(table, f"{OUT}/table.orc", stripe_size=32 * 2**20)
pd.DataFrame({k: cols[k] for k in list(cols)[:10]}).to_csv(
    f"{OUT}/table.csv.gz", index=False, compression="gzip"
)
del cols, table

# npz: 10 arrays x 32 MB
np.savez(f"{OUT}/arrays.npz", **{f"a{i}": rng.random(4_000_000) for i in range(10)})

# netCDF3 classic: 10 float32 variables 2000 x 4000
with netcdf_file(f"{OUT}/data.nc", "w") as nc:
    nc.createDimension("y", 2000)
    nc.createDimension("x", 4000)
    for i in range(10):
        v = nc.createVariable(f"v{i}", "f4", ("y", "x"))
        v[:] = rng.random((2000, 4000), dtype=np.float32)

# FITS: primary + 3 image HDUs of 4096^2 float32
hdus = [fits.PrimaryHDU()] + [
    fits.ImageHDU(rng.random((4096, 4096), dtype=np.float32), name=f"SCI{i}")
    for i in range(3)
]
fits.HDUList(hdus).writeto(f"{OUT}/image.fits", overwrite=True)

for name in sorted(os.listdir(OUT)):
    print(f"{name:16s} {os.path.getsize(f'{OUT}/{name}') / 2**20:7.1f} MiB")
