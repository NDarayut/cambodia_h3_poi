"""Exploratory plots of WorldPop 2026 Cambodia 100m population raster.

Run: uv run -p 3.11 --with rasterio --with numpy --with matplotlib --with h3 \
        python notebooks/plot_worldpop.py
"""

from pathlib import Path

import h3
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.collections import PolyCollection
from matplotlib.colors import LinearSegmentedColormap, LogNorm

ROOT = Path(__file__).resolve().parents[1]
TIF = ROOT / "khm_pop_2026_CN_100m_R2025A_v1.tif"
OUT = ROOT / "notebooks" / "worldpop_overview.png"
H3_RES = 7
PHNOM_PENH = (104.75, 105.05, 11.45, 11.70)  # xmin, xmax, ymin, ymax

# Sequential single-hue ramp (light -> dark blue)
CMAP = LinearSegmentedColormap.from_list(
    "seq_blue",
    ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"],
)
CMAP.set_bad("#f0efec")


def block_sum(a: np.ndarray, f: int) -> np.ndarray:
    """Sum f x f pixel blocks (keeps values as population counts)."""
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    return a[:h, :w].reshape(h // f, f, w // f, f).sum(axis=(1, 3))


def main() -> None:
    with rasterio.open(TIF) as r:
        arr = r.read(1, masked=True)
        t = r.transform
        b = r.bounds

    data = arr.filled(0).astype("float64")
    valid = ~arr.mask
    total = data.sum()
    print(f"Total population: {total:,.0f}")

    # --- H3 aggregation: pixel centers -> cell, sum population
    rows, cols = np.nonzero(valid & (data > 0))
    lons = t.c + (cols + 0.5) * t.a
    lats = t.f + (rows + 0.5) * t.e
    cells = np.array([h3.latlng_to_cell(la, lo, H3_RES) for la, lo in zip(lats, lons, strict=True)])
    uniq, inv = np.unique(cells, return_inverse=True)
    hex_pop = np.bincount(inv, weights=data[rows, cols])
    print(f"H3 res {H3_RES}: {len(uniq):,} cells, sum {hex_pop.sum():,.0f}")
    polys = [[(lng, lat) for lat, lng in h3.cell_to_boundary(c)] for c in uniq]

    fig, axes = plt.subplots(1, 3, figsize=(20, 7), gridspec_kw={"width_ratios": [1, 1, 0.9]})

    # Panel 1: raster aggregated to 1km blocks
    f = 10
    agg = block_sum(data, f)
    agg_mask = block_sum(valid.astype(int), f) == 0
    ax = axes[0]
    im = ax.imshow(
        np.ma.masked_where(agg_mask | (agg <= 0), agg),
        extent=(b.left, b.left + agg.shape[1] * f * t.a, b.top + agg.shape[0] * f * t.e, b.top),
        cmap=CMAP,
        norm=LogNorm(vmin=1, vmax=agg.max()),
        interpolation="nearest",
    )
    ax.set_title("Population per 1 km² (100 m raster summed)", loc="left")
    fig.colorbar(im, ax=ax, shrink=0.7, label="people (log scale)")

    # Panel 2: H3 hexes
    ax = axes[1]
    pc = PolyCollection(
        polys, array=hex_pop, cmap=CMAP, norm=LogNorm(vmin=1, vmax=hex_pop.max()), edgecolors="none"
    )
    ax.add_collection(pc)
    ax.set_xlim(b.left, b.right)
    ax.set_ylim(b.bottom, b.top)
    ax.set_title(f"Population per H3 res-{H3_RES} cell (~5.2 km²)", loc="left")
    fig.colorbar(pc, ax=ax, shrink=0.7, label="people (log scale)")

    # Panel 3: Phnom Penh at native 100 m
    xmin, xmax, ymin, ymax = PHNOM_PENH
    c0, c1 = int((xmin - t.c) / t.a), int((xmax - t.c) / t.a)
    r0, r1 = int((ymax - t.f) / t.e), int((ymin - t.f) / t.e)
    sub = arr[r0:r1, c0:c1]
    ax = axes[2]
    im = ax.imshow(
        np.ma.masked_less_equal(sub, 0),
        extent=(xmin, xmax, ymin, ymax),
        cmap=CMAP,
        norm=LogNorm(vmin=1, vmax=float(sub.max())),
        interpolation="nearest",
    )
    ax.set_title("Phnom Penh, native 100 m pixels", loc="left")
    fig.colorbar(im, ax=ax, shrink=0.7, label="people per pixel (log scale)")

    for ax in axes:
        ax.set_aspect(1 / np.cos(np.radians(12)))
        ax.tick_params(labelsize=8, colors="#6b6a66")
        for s in ax.spines.values():
            s.set_color("#d6d4cf")
    fig.suptitle(
        f"WorldPop 2026 Cambodia (R2025A, CC BY 4.0) — total {total / 1e6:.2f} M",
        x=0.01,
        ha="left",
        fontsize=14,
    )
    fig.tight_layout()
    fig.savefig(OUT, dpi=130, facecolor="white")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
