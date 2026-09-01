#!/usr/bin/env python3
"""Nagrywa akwizycję przez USB do katalogu nagrania/<nazwa>_<data>."""

import argparse
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from _common import NAGRANIA, connect, firmware_line, hush_loggers, sdk_path


def load_log_controller():
    """LogController z przykładów SDK - nie wchodzi w skład wheeli, ładujemy ze źródeł."""
    sys.path.insert(0, str(sdk_path() / "stdatalog_examples"))
    try:
        from cli_applications.stdatalog_sensors_streaming.stdatalog_sensors_streaming_common import (
            LogController,
        )
    except ImportError as exc:
        sys.exit(f"Nie udało się załadować LogController z SDK: {exc}\nUruchom ./setup.sh")
    hush_loggers()
    return LogController


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("nazwa", help="etykieta nagrania, np. wentylator_sprawny")
    ap.add_argument("--sensor", default="iis3dwb_acc",
                    help="czujnik do nagrania (domyślnie iis3dwb_acc); "
                         "'all' zostawia obecną konfigurację bez zmian")
    ap.add_argument("--duration", type=float, default=10.0, help="czas nagrania w sekundach")
    ap.add_argument("--opis", default="", help="opis zapisywany w metadanych akwizycji")
    args = ap.parse_args()

    LogController = load_log_controller()

    NAGRANIA.mkdir(parents=True, exist_ok=True)
    hsd = connect(acquisition_folder=NAGRANIA)
    dev = 0
    print(firmware_line(hsd, dev))

    if args.sensor != "all":
        available = hsd.get_sensors_names(dev)
        if args.sensor not in available:
            sys.exit(f"Nie ma czujnika '{args.sensor}'. Dostępne: {', '.join(sorted(available))}")
        # Wyłączamy resztę: równoległe strumienie o bardzo różnych ODR niepotrzebnie
        # obciążają USB i utrudniają późniejszą analizę.
        for name in available:
            if name.endswith(("_mlc", "_ispu")):
                continue
            hsd.set_sensor_enable(dev, name == args.sensor, name)

    active = [n for n in hsd.get_sensors_names(dev) if hsd.get_sensor_enable(dev, n)]
    print(f"Aktywne czujniki: {', '.join(active)}")

    hsd.set_acquisition_info(dev, args.nazwa, args.opis or f"{args.duration:g} s")

    controller = LogController(hsd, lambda _: None, show_packet_loss_warnings=True)
    print(f"Nagrywam {args.duration:g} s...")
    controller.start(device_id=dev)
    try:
        time.sleep(args.duration)
    except KeyboardInterrupt:
        print("Przerwane, zamykam pliki.")
    controller.stop(device_id=dev)

    raw = Path(hsd.get_acquisition_folder())
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = NAGRANIA / f"{args.nazwa}_{stamp}"
    if raw != target:
        shutil.move(str(raw), str(target))

    print(f"\nZapisano: {target}")
    for f in sorted(target.iterdir()):
        print(f"  {f.name:26s} {f.stat().st_size:>12,} B")
    print(f"\nAnaliza:  ./stwin analyze {target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target}")


if __name__ == "__main__":
    main()
