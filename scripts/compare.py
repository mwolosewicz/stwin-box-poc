#!/usr/bin/env python3
"""Porównuje dwa nagrania - np. maszynę sprawną z uszkodzoną."""

import argparse
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from _common import data_columns, load_acquisition, mark_harmonics, psd  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder_a", type=Path, help="nagranie odniesienia (stan normalny)")
    ap.add_argument("folder_b", type=Path, help="nagranie porównywane (podejrzenie anomalii)")
    ap.add_argument("--sensor", default=None)
    ap.add_argument("--axis", default=None, help="oś do porównania (domyślnie pierwsza)")
    ap.add_argument("--rpm", type=float, default=None)
    ap.add_argument("--fmax", type=float, default=1000.0)
    ap.add_argument("--smooth", type=int, default=9,
                    help="szerokość wygładzania stosunku w prążkach (0 wyłącza)")
    ap.add_argument("--out", type=Path, default=Path("porownanie.png"))
    args = ap.parse_args()

    comp_a, df_a, fs_a = load_acquisition(args.folder_a, args.sensor)
    comp_b, df_b, fs_b = load_acquisition(args.folder_b, args.sensor)

    col = args.axis or data_columns(df_a)[0]
    fa, da = psd(df_a[col].to_numpy(), fs_a)
    fb, db = psd(df_b[col].to_numpy(), fs_b)

    # Siatki częstotliwości różnią się, jeśli nagrania mają różną długość -
    # interpolujemy B na siatkę A, żeby dało się policzyć stosunek.
    db_on_a = np.interp(fa, fb, db)
    ratio = db_on_a / np.maximum(da, 1e-12)

    # Estymator Welcha uśrednia tylko kilkanaście segmentów, więc pojedyncze
    # prążki potrafią odskoczyć kilkukrotnie na samym szumie. Szczytu szukamy
    # na wygładzonej krzywej, żeby nie raportować artefaktu jako uszkodzenia.
    k = max(1, args.smooth | 1)
    ratio_gladki = np.convolve(ratio, np.ones(k) / k, mode="same")

    band = fa <= args.fmax
    idx = np.argmax(np.where(band, ratio_gladki, 0))

    print(f"Oś: {col}")
    print(f"A: {args.folder_a.name}  fs={fs_a:,.0f} Hz  RMS={df_a[col].std()*1000:.2f} mg")
    print(f"B: {args.folder_b.name}  fs={fs_b:,.0f} Hz  RMS={df_b[col].std()*1000:.2f} mg")
    print(f"\nNajwiększy wzrost: {ratio_gladki[idx]:.1f}x przy {fa[idx]:.1f} Hz "
          f"(wygładzone {k} prążków)")
    print(f"Wzrost RMS szerokopasmowego: {df_b[col].std() / max(df_a[col].std(), 1e-12):.2f}x")
    if ratio_gladki[idx] < 2:
        print("Różnica jest w granicach szumu pomiarowego - klasy nie są rozdzielone.")

    fig, ax = plt.subplots(2, 1, figsize=(13, 8), sharex=True)

    ax[0].semilogy(fa, da, lw=1.0, label=f"A: {args.folder_a.name}")
    ax[0].semilogy(fa, db_on_a, lw=1.0, label=f"B: {args.folder_b.name}", alpha=0.85)
    ax[0].set(ylabel="gęstość [µg/√Hz]", title=f"Porównanie widm - {col}")

    ax[1].semilogy(fa, ratio, lw=0.6, color="darkgreen", alpha=0.35, label="surowy")
    ax[1].semilogy(fa, ratio_gladki, lw=1.4, color="darkgreen", label="wygładzony")
    ax[1].legend(loc="upper right", fontsize=8)
    ax[1].axhline(1, color="k", lw=1, ls="--")
    ax[1].set(xlabel="częstotliwość [Hz]", ylabel="B / A", xlim=(0, args.fmax),
              title="Stosunek B do A - powyżej linii oznacza wzrost drgań")

    for a in ax:
        mark_harmonics(a, args.rpm, args.fmax)
        a.grid(alpha=0.3, which="both")
    ax[0].legend(loc="upper right", fontsize=8)

    plt.tight_layout()
    plt.savefig(args.out, dpi=115)
    print(f"\nWykres: {args.out}")


if __name__ == "__main__":
    main()
