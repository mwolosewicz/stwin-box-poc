"""Shared layer for the scripts: board connection, loading acquisitions, plots."""

import contextlib
import io
import logging
import os
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
RECORDINGS = REPO / "recordings"

# On every connection the SDK synchronises its DTDL model catalogue and reports
# it both through a logger and through plain print(). Without silencing that,
# the actual output drowns in dozens of lines about downloaded files and 404s
# on ST's side.
logging.getLogger("HSDatalogApp").setLevel(logging.CRITICAL)


def hush_loggers():
    """Silences the SDK loggers.

    setLevel alone is not enough: the SDK calls setup_applevel_logger(), which
    clears handlers and restores its own levels on every module import.
    logging.disable() works globally and cannot be overridden from outside.
    """
    if os.environ.get("STWIN_DEBUG"):
        return
    logging.disable(logging.INFO)
    for name in list(logging.root.manager.loggerDict):
        if name.startswith("HSDatalogApp"):
            logging.getLogger(name).setLevel(logging.CRITICAL)


class _FilteredStdout:
    """Filters the SDK's pseudo-logs out of stdout.

    Some SDK messages are plain print() calls formatted to look like logger
    entries ("... - HSDatalogApp.<module> - INFO - ..."). They cannot be turned
    off through logging configuration, so we filter them by line content.
    """

    PATTERNS = (" - HSDatalogApp.", "Added DTMI:", "Modified DTMI:",
                "Added entries:", "Removed entries:", "Modified entries:")

    def __init__(self, stream):
        self._stream = stream
        self._buffer = ""

    def write(self, text):
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if not any(p in line for p in self.PATTERNS):
                self._stream.write(line + "\n")

    def flush(self):
        if self._buffer and not any(p in self._buffer for p in self.PATTERNS):
            self._stream.write(self._buffer)
        self._buffer = ""
        self._stream.flush()

    def __getattr__(self, name):
        return getattr(self._stream, name)


if not os.environ.get("STWIN_DEBUG"):
    sys.stdout = _FilteredStdout(sys.stdout)


@contextlib.contextmanager
def quiet(enabled=True):
    """Suppresses the SDK's stdout and stderr. Disabled by STWIN_DEBUG=1."""
    if not enabled or os.environ.get("STWIN_DEBUG"):
        yield
        return
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield


def sdk_path() -> Path:
    marker = REPO / ".sdk_path"
    if not marker.exists():
        sys.exit("No .sdk_path file. Run ./setup.sh")
    return Path(marker.read_text().strip())


def connect(acquisition_folder=None):
    """Opens a USB connection to the board and returns an HSDLink object."""
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
            "Board not found.\n"
            "Check: a USB-C cable that carries data, FP-SNS-DATALOG2 flashed, "
            "no other program holding the device (e.g. the SDK GUI left open)."
        )

    # When USB fails to open, the SDK factory quietly substitutes the serial
    # backend, which only raises EmptyCommandResponse on the first command.
    # Better to catch it here and say what to do about it.
    try:
        with quiet():
            hsd.get_device_status(0)
    except Exception:
        sys.exit(
            "The board is visible on USB but does not answer commands.\n"
            "Usually the firmware hung after an interrupted SD card operation.\n"
            "Press RESET on the board (or unplug USB and the battery) and try again."
        )
    return hsd


def sd_card_mounted(hsd, dev=0) -> bool:
    """save_config writes to the SD card and without one it can hang the firmware."""
    try:
        for c in hsd.get_device(dev)["devices"][dev]["components"]:
            if list(c.keys())[0] == "log_controller":
                return bool(c["log_controller"].get("sd_mounted"))
    except Exception:
        pass
    return False


def save_to_card(hsd, dev=0):
    """Persists the configuration into device_config.json. Exits when no card is present."""
    if not sd_card_mounted(hsd, dev):
        print("\nNo SD card mounted - not saving.\n")
        print("save_config writes device_config.json to the card, and without one the")
        print("firmware can hang while trying to mount it (only RESET helps then).")
        print("Insert a card and try again.")
        hsd.close()
        sys.exit(1)
    hsd.save_config(dev)


def firmware_line(hsd, dev=0) -> str:
    fw = hsd.get_firmware_info(dev)["firmware_info"]
    return f"{hsd.get_device_alias(dev)} | {fw['fw_name']} v{fw['fw_version']} | {fw['mac_address']}"


def load_acquisition(folder, component=None):
    """Loads an acquisition into a DataFrame. Returns (component_name, df, fs)."""
    from stdatalog_core.HSD.HSDatalog import HSDatalog

    if component is None:
        dat_files = sorted(Path(folder).glob("*.dat"))
        if not dat_files:
            sys.exit(f"No .dat files in {folder}")
        component = dat_files[0].stem

    hush_loggers()
    with quiet():
        hsd = HSDatalog().create_hsd(acquisition_folder=str(folder))
        comp = HSDatalog.get_component(hsd, component)
        df = HSDatalog.get_dataframe(hsd, comp)[0]

    t = df["Time"].to_numpy()
    # We derive fs from the timestamps rather than the nominal ODR: the IIS3DWB
    # can deviate from its catalogue 26,667 Hz by more than a percent, which
    # when hunting for bearing frequencies means an error of tens of hertz.
    fs = 1.0 / np.median(np.diff(t))
    return component, df, fs


def data_columns(df):
    return [c for c in df.columns if c != "Time"]


def spectrum(x, fs):
    """One-sided amplitude spectrum with a Hann window, scaled to [g]."""
    x = x - x.mean()
    win = np.hanning(len(x))
    amp = np.abs(np.fft.rfft(x * win)) / (np.sum(win) / 2)
    freq = np.fft.rfftfreq(len(x), 1 / fs)
    return freq, amp


def psd(x, fs, nperseg=32768):
    """Square root of the PSD in µg/√Hz - the unit sensor noise is quoted in."""
    from scipy import signal

    x = x - x.mean()
    nperseg = min(nperseg, len(x))
    f, pxx = signal.welch(x, fs=fs, nperseg=nperseg)
    return f, np.sqrt(pxx) * 1e6


def mark_harmonics(ax, rpm, fmax, count=5):
    """Draws vertical markers at 1x, 2x, 3x... of the rotational frequency."""
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
            f"peak={np.abs(xr).max()*1000:7.1f} mg   "
            f"density 10-1000 Hz={dens[band].mean():6.0f} µg/√Hz")
