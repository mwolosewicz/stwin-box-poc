#!/usr/bin/env python3
"""BLE scan - checks whether the board advertises over Bluetooth, and how strongly.

Why: the Wi-Fi password cannot be stored on the board (the firmware keeps it in
RAM), so someone has to send it after every reset. For a permanently mounted
node the most convenient way is a phone over BLE, using the ST BLE Sensor app.
This script answers the two questions that cannot be checked any other way than
on site: whether the board advertises over BLE at all, and whether the signal
reaches the place you want to configure it from.

The scan needs Bluetooth permission for whatever launched the terminal - macOS
asks for it on the first run.
"""

import argparse
import asyncio
import sys

# DATALOG2 3.3.0 advertises as "HSD2v33" - the name carries the firmware
# version, so a different version will show a different name. Hence the match
# on fragments.
PATTERNS = ("HSD", "STWIN", "DATALOG", "AM1V")


def rate(rssi):
    if rssi is None:
        return "no reading"
    if rssi >= -70:
        return "strong - configuring from a phone will be no trouble"
    if rssi >= -85:
        return "weak - works up close, but not through a wall"
    return "at the edge of range - you will have to walk up to the device"


async def scan(seconds, show_all):
    from bleak import BleakScanner

    print(f"Scanning for {seconds:.0f} s...\n")
    found = await BleakScanner.discover(timeout=seconds, return_adv=True)

    results = []
    for address, (dev, adv) in found.items():
        name = adv.local_name or dev.name
        if not show_all and not (name and any(p in name.upper() for p in PATTERNS)):
            continue
        results.append((adv.rssi, name or "(no name)", address))

    results.sort(key=lambda r: -(r[0] if r[0] is not None else -999))
    return results, len(found)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seconds", type=float, default=8.0, help="scan length in seconds")
    ap.add_argument("--all", dest="show_all", action="store_true",
                    help="lists every BLE device, not just the board")
    args = ap.parse_args()

    try:
        results, total = asyncio.run(scan(args.seconds, args.show_all))
    except ImportError:
        sys.exit("The bleak package is missing. Run ./setup.sh")

    if not results:
        print(f"Board not found. BLE devices in range: {total}.\n")
        print("Possible reasons:")
        print("  - the board is powered from USB only with an active PnPL session")
        print("    (the firmware may not advertise during a USB session),")
        print("  - an acquisition is running - advertising is sometimes off while logging,")
        print("  - no Bluetooth permission for the terminal in System Settings.")
        print("\nFull list of devices seen: ./stwin ble --all")
        return

    print(f"{'RSSI':>6}  {'Name':24}  Address")
    for rssi, name, address in results:
        print(f"{rssi if rssi is not None else '?':>6}  {name:24}  {address}")

    print()
    best = results[0]
    print(f"Strongest signal: {best[1]} ({best[0]} dBm) - {rate(best[0])}")
    print("\nThe phone will see the board under the same name in the ST BLE Sensor app.")


if __name__ == "__main__":
    main()
