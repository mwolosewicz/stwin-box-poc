#!/usr/bin/env python3
"""Records an acquisition over USB into recordings/<name>_<date>."""

import argparse
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from _common import RECORDINGS, connect, firmware_line, hush_loggers, sdk_path


def load_log_controller():
    """LogController from the SDK examples - not part of the wheels, loaded from source."""
    sys.path.insert(0, str(sdk_path() / "stdatalog_examples"))
    try:
        from cli_applications.stdatalog_sensors_streaming.stdatalog_sensors_streaming_common import (
            LogController,
        )
    except ImportError as exc:
        sys.exit(f"Could not load LogController from the SDK: {exc}\nRun ./setup.sh")
    hush_loggers()
    return LogController


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", help="recording label, e.g. fan_healthy")
    ap.add_argument("--sensor", default="iis3dwb_acc",
                    help="sensor or comma-separated list to record "
                         "(default: iis3dwb_acc); 'all' leaves the current "
                         "configuration untouched")
    ap.add_argument("--odr", action="append", default=[], metavar="NAME=HZ",
                    help="sensor ODR, e.g. --odr ism330dhcx_acc=6667 "
                         "(may be repeated)")
    ap.add_argument("--fs", action="append", default=[], metavar="NAME=RANGE",
                    help="measurement range, e.g. --fs ism330dhcx_acc=16 "
                         "(may be repeated)")
    ap.add_argument("--duration", type=float, default=10.0, help="recording length in seconds")
    ap.add_argument("--note", default="", help="note stored in the acquisition metadata")
    ap.add_argument("--out", default=os.environ.get("STWIN_RECORDINGS"),
                    help="directory to save recordings into (default: recordings/ "
                         "in the repo; can also be set with $STWIN_RECORDINGS)")
    args = ap.parse_args()

    LogController = load_log_controller()

    recordings_dir = Path(args.out).expanduser() if args.out else RECORDINGS
    recordings_dir.mkdir(parents=True, exist_ok=True)
    hsd = connect(acquisition_folder=recordings_dir)
    dev = 0
    try:
        print(firmware_line(hsd, dev))

        available = hsd.get_sensors_names(dev)
        if args.sensor != "all":
            wanted = {name.strip() for name in args.sensor.split(",") if name.strip()}
            unknown = wanted - set(available)
            if unknown:
                sys.exit(f"No sensor: {', '.join(sorted(unknown))}. "
                         f"Available: {', '.join(sorted(available))}")
            # Disable the rest: parallel streams with wildly different ODRs load the
            # USB link for nothing and make the later analysis harder.
            for name in available:
                if name.endswith(("_mlc", "_ispu")):
                    continue
                hsd.set_sensor_enable(dev, name in wanted, name)

        for option, setter in ((args.odr, hsd.set_sensor_odr),
                               (args.fs, hsd.set_sensor_fs)):
            for item in option:
                try:
                    name, value = item.split("=", 1)
                    value = float(value)
                except ValueError:
                    ap.error(f"invalid sensor setting '{item}'; expected NAME=NUMBER")
                setter(dev, value, name.strip())

        active = [n for n in available if hsd.get_sensor_enable(dev, n)]
        print(f"Active sensors: {', '.join(active)}")

        hsd.set_acquisition_info(dev, args.name, args.note or f"{args.duration:g} s")

        controller = LogController(hsd, lambda _: None, show_packet_loss_warnings=True)
        print(f"Recording {args.duration:g} s...")
        try:
            controller.start(device_id=dev)
            try:
                time.sleep(args.duration)
            except KeyboardInterrupt:
                print("Interrupted, closing files.")
        finally:
            controller.stop(device_id=dev)

        raw = Path(hsd.get_acquisition_folder())
    finally:
        # Releasing the process file descriptors is not equivalent to closing
        # libhs_datalog: the native PnPL backend requires an explicit close.
        try:
            if hsd.close() is False:
                print("Warning: the USB communication engine did not close cleanly.",
                      file=sys.stderr)
        except Exception as exc:
            print(f"Warning: could not close the USB communication engine: {exc}",
                  file=sys.stderr)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = recordings_dir / f"{args.name}_{stamp}"
    if raw != target:
        shutil.move(str(raw), str(target))

    print(f"\nSaved: {target}")
    for f in sorted(target.iterdir()):
        print(f"  {f.name:26s} {f.stat().st_size:>12,} B")
    print(f"\nAnalysis:  ./stwin analyze {target.relative_to(Path.cwd()) if target.is_relative_to(Path.cwd()) else target}")


if __name__ == "__main__":
    main()
