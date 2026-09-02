#!/usr/bin/env python3
"""Analyses a recording: time series, amplitude spectrum and PSD."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from _common import (  # noqa: E402
    data_columns,
    load_acquisition,
    mark_harmonics,
    psd,
    spectrum,
    stats_line,
)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", type=Path, help="acquisition directory")
    ap.add_argument("--sensor", default=None, help="component to analyse (default: first .dat)")
    ap.add_argument("--rpm", type=float, default=None,
                    help="machine speed - draws 1x, 2x, 3x markers")
    ap.add_argument("--fmax", type=float, default=500.0,
                    help="upper limit of the bottom PSD plot, in Hz")
    ap.add_argument("--out", type=Path, default=None, help="path of the resulting PNG")
    args = ap.parse_args()

    comp, df, fs = load_acquisition(args.folder, args.sensor)
    axes_cols = data_columns(df)
    t = df["Time"].to_numpy()

    print(f"Component: {comp}")
    print(f"Samples: {len(df):,}   duration: {t[-1] - t[0]:.3f} s   fs = {fs:,.0f} Hz")
    print("\nStatistics (DC component removed):")
    for c in axes_cols:
        print(stats_line(c, df[c].to_numpy(), fs))

    fig, ax = plt.subplots(3, 1, figsize=(13, 11))

    for c in axes_cols:
        ax[0].plot(t, df[c].to_numpy(), lw=0.4, label=c)
    ax[0].set(xlabel="time [s]", ylabel="acceleration [g]",
              title=f"{comp} - time series ({fs/1000:.1f} kHz)")

    for c in axes_cols:
        f, amp = spectrum(df[c].to_numpy(), fs)
        ax[1].semilogy(f, amp + 1e-12, lw=0.5, label=c)
    ax[1].set(xlabel="frequency [Hz]", ylabel="amplitude [g]", xlim=(0, fs / 2),
              title=f"Amplitude spectrum - full band up to {fs/2000:.1f} kHz")

    for c in axes_cols:
        f, dens = psd(df[c].to_numpy(), fs)
        ax[2].semilogy(f, dens, lw=0.9, label=c)
    mark_harmonics(ax[2], args.rpm, args.fmax)
    ax[2].set(xlabel="frequency [Hz]", ylabel="density [µg/√Hz]", xlim=(0, args.fmax),
              title=f"PSD 0-{args.fmax:g} Hz"
                    + (f" - markers for {args.rpm:g} rpm" if args.rpm else ""))

    for a in ax:
        a.legend(loc="upper right", ncol=3, fontsize=8)
        a.grid(alpha=0.3, which="both")

    plt.tight_layout()
    out = args.out or args.folder / "spectrum.png"
    plt.savefig(out, dpi=115)
    print(f"\nPlot: {out}")


if __name__ == "__main__":
    main()
