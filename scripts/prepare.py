#!/usr/bin/env python3
"""Prepares the board for field work: picks sensors and persists them to the card.

Why a separate command: ./stwin record also switches sensors, but it starts
streaming over USB right afterwards and the settings stay in RAM only. The
"configure at the desk, mount at the machine, press USR" scenario needs
something that sets the sensors and writes them to the card - because only the
device_config.json on the card survives a reset.
"""

import argparse
import sys
from datetime import datetime

from _common import connect, firmware_line, save_to_card


def sensor_statuses(hsd, dev):
    """Returns {name: status dict} for the components that are sensors."""
    out = {}
    for name in hsd.get_sensors_names(dev):
        try:
            out[name] = hsd.get_component_status(dev, name)[name]
        except Exception:
            out[name] = {}
    return out


def throughput_mb_h(status):
    """Card write rate in MB/h. None when the firmware did not report the fields.

    Derived from sd_dps, the bytes per second per channel that the firmware
    reports for the current ODR - not from the odr field, which is an enum index
    rather than hertz. The firmware rounds the value up to a multiple of 512 B,
    so slow sensors come out overstated; for the fast ones that dominate the
    budget the error stays below a percent.
    """
    dps, dim = status.get("sd_dps"), status.get("dim")
    if not dps or not dim:
        return None
    return dps * dim * 3600 / 1e6


def describe_sensor(name, status):
    mb = throughput_mb_h(status)
    size = f"{mb:,.0f} MB/h" if mb is not None else "size unknown"
    return f"  {name:20s} {size:>14s}"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sensor", action="append", default=None, metavar="NAME",
                    help="sensor to enable; may be repeated or comma-separated. "
                         "All others will be disabled")
    ap.add_argument("--odr", type=float, default=None,
                    help="sets the ODR on the selected sensors")
    ap.add_argument("--fs", type=float, default=None,
                    help="sets the measurement range on the selected sensors")
    ap.add_argument("--no-save", dest="no_save", action="store_true",
                    help="only apply the settings, without persisting them (lost on reset)")
    ap.add_argument("--no-clock", dest="no_clock", action="store_true",
                    help="do not sync the board clock with the computer clock")
    args = ap.parse_args()

    selected = []
    for item in args.sensor or []:
        selected += [s.strip() for s in item.split(",") if s.strip()]

    hsd = connect()
    dev = 0
    print(firmware_line(hsd, dev))
    print()

    # Acquisitions started with the USR button have nowhere to get the time
    # from, unlike the USB ones where the SDK sets the RTC on every start_log.
    # Without this the recordings on the card get a date counted from zero and
    # cannot be ordered in time.
    if not args.no_clock:
        now = datetime.now()
        hsd.set_rtc_time(dev)
        print(f"Board clock set to {now:%Y-%m-%d %H:%M:%S}.")
        print("Power keeps it running - after cutting USB and the battery, set it again.\n")

    available = hsd.get_sensors_names(dev)
    unknown = [s for s in selected if s not in available]
    if unknown:
        hsd.close()
        sys.exit(f"No such sensor: {', '.join(unknown)}.\n"
                 f"Available: {', '.join(sorted(available))}")

    if selected:
        # MLC and ISPU are left alone: those are compute blocks inside the
        # sensor, driven by a UCF file, not streams to be logged.
        for name in available:
            if name.endswith(("_mlc", "_ispu")):
                continue
            hsd.set_sensor_enable(dev, name in selected, name)
        for name in selected:
            if args.odr is not None:
                hsd.set_sensor_odr(dev, args.odr, name)
            if args.fs is not None:
                hsd.set_sensor_fs(dev, args.fs, name)

    statuses = sensor_statuses(hsd, dev)
    active = [n for n in available if statuses.get(n, {}).get("enable")]

    if not active:
        print("No sensor is enabled - the board would record nothing.")
        print(f"Available: {', '.join(sorted(available))}")
        hsd.close()
        sys.exit(1)

    print("Sensors that will collect data:")
    for name in active:
        print(describe_sensor(name, statuses[name]))

    rates = [throughput_mb_h(statuses[n]) for n in active]
    if all(r is not None for r in rates) and sum(rates) > 0:
        total = sum(rates)
        if len(active) > 1:
            print(f"  {'total':20s} {f'{total:,.0f} MB/h':>14s}")
        print()
        for capacity, label in ((32000, "32 GB"), (64000, "64 GB"), (128000, "128 GB")):
            hours = capacity / total
            print(f"  A {label} card fills up in about {hours:,.0f} h "
                  f"({hours / 24:,.1f} days)")

    if args.no_save:
        print("\nNot writing to the card (--no-save). The settings will be lost on reset.")
    else:
        print("\nWriting device_config.json to the card...")
        save_to_card(hsd, dev)
        print("Saved. After a reset the board will load this configuration from the card.")
        print("\nYou can unplug USB and mount the device.")

    hsd.close()


if __name__ == "__main__":
    main()
