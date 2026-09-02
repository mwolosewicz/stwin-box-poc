#!/usr/bin/env python3
"""Konfiguracja Wi-Fi i serwera FTP na płytce, przez USB.

Firmware wystawia komponent wifi_config z właściwościami ssid i ftp_username
oraz komendami wifi_connect, wifi_disconnect i set_ftp_credentials.

Czego firmware NIE potrafi: zapamiętać hasła. W kodzie DATALOG2 wifi_password
i ftp_password to zwykłe tablice znaków w RAM, zerowane przy każdym starcie
(app_netxduo.c). Nie ma zapisu do flasha. Dlatego hasło trzymamy po stronie
komputera - w pęku kluczy macOS - i wysyłamy je jedną komendą po każdym
restarcie płytki.
"""

import argparse
import getpass
import subprocess
import sys
import time

from _common import connect, firmware_line

COMP = "wifi_config"
KEYCHAIN_SERVICE = "stwin-box-poc-wifi"


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


def keychain_dostepny():
    return sys.platform == "darwin"


def keychain_odczyt(konto):
    if not keychain_dostepny():
        return None
    wynik = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", konto, "-w"],
        capture_output=True, text=True,
    )
    return wynik.stdout.strip() if wynik.returncode == 0 else None


def keychain_zapis(konto, wartosc):
    if not keychain_dostepny():
        print("Zapamiętywanie haseł działa tylko na macOS - pomijam.")
        return
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
         "-a", konto, "-w", wartosc, "-D", "hasło Wi-Fi dla STWIN.box"],
        check=True, capture_output=True,
    )
    print(f"Hasło zapamiętane w pęku kluczy (usługa {KEYCHAIN_SERVICE}, konto {konto}).")


def keychain_usun(konto):
    if not keychain_dostepny():
        return
    wynik = subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", konto],
        capture_output=True, text=True,
    )
    print("Usunięto z pęku kluczy." if wynik.returncode == 0 else "Nie było takiego wpisu.")


def haslo(podane, konto, monit):
    """Kolejność: argument, pęk kluczy, pytanie interaktywne."""
    if podane is not None:
        return podane, False
    zapisane = keychain_odczyt(konto)
    if zapisane:
        print("Używam hasła z pęku kluczy.")
        return zapisane, True
    return getpass.getpass(monit), False


def karta_obecna(hsd, dev):
    """save_config zapisuje na kartę SD i bez niej potrafi zawiesić firmware."""
    try:
        for c in hsd.get_device(dev)["devices"][dev]["components"]:
            if list(c.keys())[0] == "log_controller":
                return bool(c["log_controller"].get("sd_mounted"))
    except Exception:
        pass
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="akcja", required=True)

    sub.add_parser("status", help="pokazuje bieżącą konfigurację")

    p_con = sub.add_parser("connect", help="łączy z siecią Wi-Fi")
    p_con.add_argument("--ssid", required=True)
    p_con.add_argument("--password", default=None,
                       help="pominięcie: hasło z pęku kluczy albo pytanie interaktywne")
    p_con.add_argument("--zapamietaj", action="store_true",
                       help="zapisuje hasło w pęku kluczy macOS na kolejne razy")
    p_con.add_argument("--timeout", type=float, default=30.0,
                       help="ile sekund czekać na adres IP")

    sub.add_parser("disconnect", help="rozłącza Wi-Fi")

    p_zap = sub.add_parser("zapomnij", help="usuwa hasło z pęku kluczy")
    p_zap.add_argument("--ssid", required=True)

    p_ftp = sub.add_parser("ftp", help="ustawia dane logowania do FTP")
    p_ftp.add_argument("--user", required=True)
    p_ftp.add_argument("--password", default=None)

    sub.add_parser("save", help="zapisuje konfigurację na kartę SD (bez haseł)")

    args = ap.parse_args()

    if args.akcja == "zapomnij":
        keychain_usun(args.ssid)
        return

    hsd = connect()
    dev = 0
    print(firmware_line(hsd, dev))
    print()

    if args.akcja == "status":
        print_status(hsd, dev)

    elif args.akcja == "connect":
        pwd, z_pekiem = haslo(args.password, args.ssid, f"Hasło do sieci {args.ssid}: ")
        if args.zapamietaj and not z_pekiem:
            keychain_zapis(args.ssid, pwd)
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
        pwd, _ = haslo(args.password, f"ftp:{args.user}", f"Hasło FTP dla {args.user}: ")
        hsd.set_property(dev, args.user, COMP, "ftp_username")
        send(hsd, dev, "set_ftp_credentials", "password", pwd)
        print("Ustawiono dane logowania do FTP.\n")
        print_status(hsd, dev)

    elif args.akcja == "save":
        if not karta_obecna(hsd, dev):
            print("Brak zamontowanej karty SD - przerywam.\n")
            print("save_config zapisuje device_config.json na kartę i bez niej")
            print("firmware potrafi się zawiesić na próbie montowania (wtedy")
            print("pomaga tylko przycisk RESET). Włóż kartę i spróbuj ponownie.")
            hsd.close()
            sys.exit(1)
        print("Zapisuję device_config.json na kartę...")
        hsd.save_config(dev)
        print("Zapisano. Przy starcie płytka wczyta ten plik.\n")
        print("Utrwalone zostają: SSID, nazwa użytkownika FTP oraz zestaw")
        print("włączonych czujników wraz z ODR i zakresami.")
        print("NIE zostaje utrwalone hasło - firmware trzyma je wyłącznie w RAM.")

    hsd.close()


if __name__ == "__main__":
    main()
