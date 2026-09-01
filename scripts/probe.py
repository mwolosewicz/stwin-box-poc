#!/usr/bin/env python3
"""Wypisuje stan płytki: firmware i pełną listę czujników z ustawieniami."""

import argparse
import json

from _common import connect, firmware_line

# Katalogowe pasma i przeznaczenie - żeby przy wyborze czujnika nie trzeba było
# sięgać do dokumentacji ST.
OPIS = {
    "iis3dwb_acc": "26,7 kHz, pasmo do 6 kHz, 75 µg/√Hz - drgania, łożyska, ultradźwięki mechaniczne",
    "ism330dhcx_acc": "do 6,66 kHz - ogólnego przeznaczenia, niewyważenie, długie nagrania",
    "ism330dhcx_gyro": "żyroskop - przydatny tylko na obiektach, które się obracają",
    "ism330dhcx_mlc": "Machine Learning Core - klasyfikacja w czujniku, wymaga pliku UCF",
    "iis2iclx_acc": "inklinometr 2-osiowy, ±0,5 g, 15 µg/√Hz - przechylenia i bardzo niskie częstotliwości",
    "iis2iclx_mlc": "Machine Learning Core inklinometru, wymaga pliku UCF",
    "iis2dlpc_acc": "akcelerometr niskiego poboru - czuwanie i wybudzanie",
    "iis2mdc_mag": "magnetometr - wykrywa pracę silnika po polu rozproszonym",
    "ilps22qs_press": "barometr - wysokość, szczelność, zmiany ciśnienia",
    "imp23absu_mic": "mikrofon analogowy do 80 kHz - wycieki sprężonego powietrza, ultradźwięki",
    "imp34dt05_mic": "mikrofon cyfrowy, pasmo słyszalne - przepływ wody, zdarzenia dźwiękowe",
    "stts22h_temp": "temperatura ±0,5 °C - kontekst do kompensacji dryfu",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="zrzuca pełny status urządzenia w JSON")
    args = ap.parse_args()

    hsd = connect()
    dev = 0

    print(firmware_line(hsd, dev))

    if args.json:
        print(json.dumps(hsd.get_device(dev), indent=2))
        hsd.close()
        return

    names = sorted(hsd.get_sensors_names(dev))
    print(f"\nCzujniki: {len(names)}\n")

    for name in names:
        try:
            enabled = hsd.get_sensor_enable(dev, name)
        except Exception:
            enabled = None
        flag = "wł. " if enabled else "wył."
        print(f"  [{flag}] {name:18s} {OPIS.get(name, '')}")

    print(
        "\nUwaga: wartości ODR i FS w modelu urządzenia to indeksy enum, nie herce.\n"
        "Rzeczywistą częstotliwość próbkowania wyliczają skrypty analizy ze znaczników czasu."
    )
    hsd.close()


if __name__ == "__main__":
    main()
