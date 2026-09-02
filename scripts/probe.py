#!/usr/bin/env python3
"""Prints the board state: firmware and the full sensor list with settings."""

import argparse
import json

from _common import connect, firmware_line

# Datasheet bandwidths and intended use, so that picking a sensor does not
# require digging through ST's documentation.
DESCRIPTIONS = {
    "iis3dwb_acc": "26.7 kHz, band up to 6 kHz, 75 µg/√Hz - vibration, bearings, mechanical ultrasound",
    "ism330dhcx_acc": "up to 6.66 kHz - general purpose, imbalance, long recordings",
    "ism330dhcx_gyro": "gyroscope - only useful on things that rotate",
    "ism330dhcx_mlc": "Machine Learning Core - in-sensor classification, needs a UCF file",
    "iis2iclx_acc": "2-axis inclinometer, ±0.5 g, 15 µg/√Hz - tilt and very low frequencies",
    "iis2iclx_mlc": "inclinometer Machine Learning Core, needs a UCF file",
    "iis2dlpc_acc": "low-power accelerometer - standby and wake-on-threshold",
    "iis2mdc_mag": "magnetometer - detects a running motor from its stray field",
    "ilps22qs_press": "barometer - altitude, tightness, pressure changes",
    "imp23absu_mic": "analogue microphone up to 80 kHz - compressed air leaks, ultrasound",
    "imp34dt05_mic": "digital microphone, audible band - water flow, acoustic events",
    "stts22h_temp": "temperature ±0.5 °C - context for drift compensation",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="dumps the full device status as JSON")
    args = ap.parse_args()

    hsd = connect()
    dev = 0

    print(firmware_line(hsd, dev))

    if args.json:
        print(json.dumps(hsd.get_device(dev), indent=2))
        hsd.close()
        return

    names = sorted(hsd.get_sensors_names(dev))
    print(f"\nSensors: {len(names)}\n")

    for name in names:
        try:
            enabled = hsd.get_sensor_enable(dev, name)
        except Exception:
            enabled = None
        flag = "on " if enabled else "off"
        print(f"  [{flag}] {name:18s} {DESCRIPTIONS.get(name, '')}")

    print(
        "\nNote: the ODR and FS values in the device model are enum indices, not hertz.\n"
        "The analysis scripts derive the real sampling rate from the timestamps."
    )
    hsd.close()


if __name__ == "__main__":
    main()
