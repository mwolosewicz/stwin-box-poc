#!/usr/bin/env python3
"""Compares two recordings - e.g. a healthy machine against a damaged one."""

import argparse
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from _common import data_columns, load_acquisition, mark_harmonics, psd  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder_a", type=Path, help="reference recording (normal state)")
    ap.add_argument("folder_b", type=Path, help="recording under test (suspected anomaly)")
    ap.add_argument("--sensor", default=None)
    ap.add_argument("--axis", default=None, help="axis to compare (default: the first one)")
    ap.add_argument("--rpm", type=float, default=None)
    ap.add_argument("--fmax", type=float, default=1000.0)
    ap.add_argument("--smooth", type=int, default=9,
                    help="ratio smoothing width in bins (0 disables it)")
    ap.add_argument("--out", type=Path, default=Path("comparison.png"))
    args = ap.parse_args()

    comp_a, df_a, fs_a = load_acquisition(args.folder_a, args.sensor)
    comp_b, df_b, fs_b = load_acquisition(args.folder_b, args.sensor)

    col = args.axis or data_columns(df_a)[0]
    fa, da = psd(df_a[col].to_numpy(), fs_a)
    fb, db = psd(df_b[col].to_numpy(), fs_b)

    # The frequency grids differ when the recordings have different lengths, so
    # we interpolate B onto A's grid to be able to compute the ratio at all.
    db_on_a = np.interp(fa, fb, db)
    ratio = db_on_a / np.maximum(da, 1e-12)

    # Welch's estimator averages only a dozen or so segments, so single bins can
    # jump several times over on noise alone. We look for the peak on the
    # smoothed curve so as not to report an artefact as damage.
    k = max(1, args.smooth | 1)
    ratio_smooth = np.convolve(ratio, np.ones(k) / k, mode="same")

    band = fa <= args.fmax
    idx = np.argmax(np.where(band, ratio_smooth, 0))

    print(f"Axis: {col}")
    print(f"A: {args.folder_a.name}  fs={fs_a:,.0f} Hz  RMS={df_a[col].std()*1000:.2f} mg")
    print(f"B: {args.folder_b.name}  fs={fs_b:,.0f} Hz  RMS={df_b[col].std()*1000:.2f} mg")
    print(f"\nLargest increase: {ratio_smooth[idx]:.1f}x at {fa[idx]:.1f} Hz "
          f"(smoothed over {k} bins)")
    print(f"Broadband RMS increase: {df_b[col].std() / max(df_a[col].std(), 1e-12):.2f}x")
    if ratio_smooth[idx] < 2:
        print("The difference is within measurement noise - the classes are not separated.")

    fig, ax = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

    ax[0].semilogy(fa, da, lw=1.0, label=f"A: {args.folder_a.name}")
    ax[0].semilogy(fa, db_on_a, lw=1.0, label=f"B: {args.folder_b.name}", alpha=0.85)
    ax[0].set(ylabel="density [µg/√Hz]", title=f"Spectrum comparison - {col}")

    ax[1].semilogy(fa, ratio, lw=0.6, color="darkgreen", alpha=0.35, label="raw")
    ax[1].semilogy(fa, ratio_smooth, lw=1.4, color="darkgreen", label="smoothed")
    ax[1].legend(loc="upper right", fontsize=8)
    ax[1].axhline(1, color="k", lw=1, ls="--")
    ax[1].set(xlabel="frequency [Hz]", ylabel="B / A", xlim=(0, args.fmax),
              title="B to A ratio - above the line means more vibration")

    for a in ax:
        mark_harmonics(a, args.rpm, args.fmax)
        a.grid(alpha=0.3, which="both")
    ax[0].legend(loc="upper right", fontsize=8)

    plt.tight_layout()
    plt.savefig(args.out, dpi=115)
    print(f"\nPlot: {args.out}")


if __name__ == "__main__":
    main()
