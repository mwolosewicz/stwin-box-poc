"""Wspólna warstwa dla skryptów: połączenie z płytką, wczytywanie nagrań, wykresy."""

import contextlib
import io
import logging
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
NAGRANIA = REPO / "nagrania"

# SDK przy każdym połączeniu synchronizuje katalog modeli DTDL i raportuje to
# przez logger oraz przez zwykłe print(). Bez wyciszenia właściwe wyjście ginie
# w kilkudziesięciu linijkach o pobieranych plikach i błędach 404 po stronie ST.
logging.getLogger("HSDatalogApp").setLevel(logging.CRITICAL)


def hush_loggers():
    """Wycisza logi SDK.

    Samo setLevel nie wystarcza: SDK wywołuje setup_applevel_logger(), które
    czyści handlery i przywraca własne poziomy przy każdym imporcie modułu.
    logging.disable() działa globalnie i nie da się go nadpisać z zewnątrz.
    """
    if os.environ.get("STWIN_DEBUG"):
        return
    logging.disable(logging.INFO)
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("HSDatalogApp"):
            logging.getLogger(name).setLevel(logging.CRITICAL)


class _FilteredStdout:
    """Odsiewa pseudo-logi SDK z stdout.

    Część komunikatów SDK to zwykłe print() sformatowane tak, żeby wyglądały jak
    wpisy loggera ("... - HSDatalogApp.<moduł> - INFO - ..."). Nie da się ich
    wyłączyć konfiguracją logowania, więc filtrujemy je po treści linii.
    """

    WZORCE = (" - HSDatalogApp.", "Added DTMI:", "Modified DTMI:",
              "Added entries:", "Removed entries:", "Modified entries:")

    def __init__(self, stream):
        self._stream = stream
        self._bufor = ""

    def write(self, text):
        self._bufor += text
        while "\n" in self._bufor:
            linia, self._bufor = self._bufor.split("\n", 1)
            if not any(w in linia for w in self.WZORCE):
                self._stream.write(linia + "\n")

    def flush(self):
        if self._bufor and not any(w in self._bufor for w in self.WZORCE):
            self._stream.write(self._bufor)
        self._bufor = ""
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


if not os.environ.get("STWIN_DEBUG"):
    sys.stdout = _FilteredStdout(sys.stdout)


@contextlib.contextmanager
def quiet(enabled=True):
    """Tłumi stdout i stderr SDK. Wyłączane przez STWIN_DEBUG=1."""
    if not enabled or os.environ.get("STWIN_DEBUG"):
        yield
        return
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def sdk_path() -> Path:
    marker = REPO / ".sdk_path"
    if not marker.exists():
        sys.exit("Brak pliku .sdk_path. Uruchom ./setup.sh")
    return Path(marker.read_text().strip())


def connect(acquisition_folder=None):
    """Otwiera połączenie USB z płytką i zwraca obiekt HSDLink."""
    from stdatalog_core.HSD_link.HSDLink import HSDLink

    hush_loggers()
    with quiet():
        hsd = HSDLink().create_hsd_link(
            dev_com_type="st_hsd",
            acquisition_folder=str(acquisition_folder) if acquisition_folder else None,
        )
    hush_loggers()
    if hsd is None:
        sys.exit(
            "Nie znaleziono płytki.\n"
            "Sprawdź: kabel USB-C obsługujący dane, wgrany FP-SNS-DATALOG2, "
            "brak innego programu trzymającego urządzenie (np. otwarte GUI SDK)."
        )
    return hsd


def firmware_line(hsd, dev=0) -> str:
    fw = hsd.get_firmware_info(dev)["firmware_info"]
    return f"{hsd.get_device_alias(dev)} | {fw['fw_name']} v{fw['fw_version']} | {fw['mac_address']}"


def load_acquisition(folder, component=None):
    """Wczytuje nagranie do DataFrame. Zwraca (nazwa_komponentu, df, fs)."""
    from stdatalog_core.HSD.HSDatalog import HSDatalog

    if component is None:
        dat_files = sorted(Path(folder).glob("*.dat"))
        if not dat_files:
            sys.exit(f"Brak plików .dat w {folder}")
        component = dat_files[0].stem

    hush_loggers()
    with quiet():
        hsd = HSDatalog().create_hsd(acquisition_folder=str(folder))
        comp = HSDatalog.get_component(hsd, component)
        df = HSDatalog.get_dataframe(hsd, comp)[0]

    t = df["Time"].to_numpy()
    # Liczymy fs ze znaczników czasu, a nie z nominalnego ODR: IIS3DWB potrafi
    # odbiegać od katalogowych 26 667 Hz o ponad procent, co przy szukaniu
    # częstotliwości łożyskowych daje błąd rzędu dziesiątek herców.
    fs = 1.0 / np.median(np.diff(t))
    return component, df, fs


def data_columns(df):
    return [c for c in df.columns if c != "Time"]


def spectrum(x, fs):
    """Jednostronne widmo amplitudowe z oknem Hanninga, skalowane do [g]."""
    x = x - x.mean()
    win = np.hanning(len(x))
    amp = np.abs(np.fft.rfft(x * win)) / (np.sum(win) / 2)
    freq = np.fft.rfftfreq(len(x), 1 / fs)
    return freq, amp


def psd(x, fs, nperseg=32768):
    """Pierwiastek z PSD w µg/√Hz - w tych jednostkach podaje się szum czujnika."""
    from scipy import signal

    x = x - x.mean()
    nperseg = min(nperseg, len(x))
    f, pxx = signal.welch(x, fs=fs, nperseg=nperseg)
    return f, np.sqrt(pxx) * 1e6


def mark_harmonics(ax, rpm, fmax, count=5):
    """Rysuje pionowe znaczniki przy 1x, 2x, 3x... częstotliwości obrotowej."""
    if not rpm:
        return
    f1 = rpm / 60.0
    for k in range(1, count + 1):
        f = f1 * k
        if f > fmax:
            break
        ax.axvline(f, color="crimson", ls=":", lw=1, alpha=0.8)
        ax.annotate(f"{k}x", xy=(f, 0.97), xycoords=("data", "axes fraction"),
                    color="crimson", fontsize=8, ha="center", va="top")


def stats_line(name, x, fs):
    xr = x - x.mean()
    f, dens = psd(xr, fs)
    band = (f >= 10) & (f <= 1000)
    return (f"  {name:10s} offset={x.mean():+7.4f} g   RMS={xr.std()*1000:7.2f} mg   "
            f"szczyt={np.abs(xr).max()*1000:7.1f} mg   "
            f"gęstość 10-1000 Hz={dens[band].mean():6.0f} µg/√Hz")
