#!/usr/bin/env python3
"""Konfiguracja Wi-Fi i serwera FTP na płytce, przez USB.

Firmware wystawia komponent wifi_config z właściwościami ssid i ftp_username
oraz komendami wifi_connect, wifi_disconnect i set_ftp_credentials. Hasła są
tylko do zapisu - urządzenie ich nie zwraca.
"""

import argparse
import getpass
import time

from _common import connect, firmware_line

COMP = "wifi_config"


def send(hsd, dev, command, req_name=None, req_value=None):
    from stdatalog_pnpl.PnPLCmd import PnPLCMDManager

    msg = PnPLCMDManager.create_command_cmd(COMP, command, req_name, req_value)
    return hsd.send_command(dev, msg)


def read_status(hsd, dev):
    def prop(name):
        try:
            return hsd.get_string_property(dev, COMP, name)
        except Exception:
            return None

    return prop("ssid"), prop("ip"), prop("ftp_username")


def print_status(hsd, dev):
    ssid, ip, user = read_status(hsd, dev)
    print(f"  SSID          : {ssid or '(nie ustawiony)'}")
    print(f"  Adres IP      : {ip or '0.0.0.0'}")
    print(f"  Użytkownik FTP: {user or '(brak)'}")
    if ip and ip != "0.0.0.0":
        print(f"\n  Serwer FTP: ftp://{ip}/   (użytkownik: {user or 'anonymous'})")
    return ip


def haslo(podane, monit):
    """Hasło pytamy interaktywnie, żeby nie zostawało w historii powłoki."""
    return podane if podane is not None else getpass.getpass(monit)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="akcja", required=True)

    sub.add_parser("status", help="pokazuje bieżącą konfigurację")

    p_con = sub.add_parser("connect", help="łączy z siecią Wi-Fi")
    p_con.add_argument("--ssid", required=True)
    p_con.add_argument("--password", default=None, help="pominięcie spowoduje zapytanie")
    p_con.add_argument("--timeout", type=float, default=30.0,
                       help="ile sekund czekać na adres IP")

    sub.add_parser("disconnect", help="rozłącza Wi-Fi")

    p_ftp = sub.add_parser("ftp", help="ustawia dane logowania do FTP")
    p_ftp.add_argument("--user", required=True)
    p_ftp.add_argument("--password", default=None)

    args = ap.parse_args()

    hsd = connect()
    dev = 0
    print(firmware_line(hsd, dev))
    print()

    if args.akcja == "status":
        print_status(hsd, dev)

    elif args.akcja == "connect":
        pwd = haslo(args.password, f"Hasło do sieci {args.ssid}: ")
        hsd.set_property(dev, args.ssid, COMP, "ssid")
        send(hsd, dev, "wifi_connect", "password", pwd)

        print(f"Łączę z {args.ssid}...")
        ip = None
        koniec = time.time() + args.timeout
        while time.time() < koniec:
            time.sleep(2)
            _, ip, _ = read_status(hsd, dev)
            if ip and ip != "0.0.0.0":
                break

        print()
        if not ip or ip == "0.0.0.0":
            print("Nie dostałem adresu IP w zadanym czasie.\n")
            print("Najczęstsza przyczyna: nieaktualny firmware modułu EMW3080.")
            print("Dokumentacja ST wymaga jego aktualizacji przed użyciem Wi-Fi")
            print("w DATALOG2 - plik binarny jest w paczce FP-SNS-DATALOG2,")
            print("w katalogu Utilities/WiFi_module_upgrade.")
            print("\nSprawdź też, czy sieć działa w paśmie 2,4 GHz - moduł nie obsługuje 5 GHz.")
        else:
            print_status(hsd, dev)

    elif args.akcja == "disconnect":
        send(hsd, dev, "wifi_disconnect")
        print("Rozłączono.")

    elif args.akcja == "ftp":
        pwd = haslo(args.password, f"Hasło FTP dla {args.user}: ")
        hsd.set_property(dev, args.user, COMP, "ftp_username")
        send(hsd, dev, "set_ftp_credentials", "password", pwd)
        print("Ustawiono dane logowania do FTP.\n")
        print_status(hsd, dev)

    hsd.close()


if __name__ == "__main__":
    main()
