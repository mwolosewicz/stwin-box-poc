#!/usr/bin/env python3
"""Configures Wi-Fi and the FTP server on the board, over USB.

The firmware exposes a wifi_config component with ssid and ftp_username
properties plus wifi_connect, wifi_disconnect and set_ftp_credentials commands.

What the firmware cannot do: remember a password. In the DATALOG2 code
wifi_password and ftp_password are plain character arrays in RAM, zeroed on
every boot (app_netxduo.c). There is no write to flash. So we keep the password
on the computer side - in the macOS keychain - and send it with a single command
after every reset of the board.
"""

import argparse
import getpass
import subprocess
import sys
import time

from _common import connect, firmware_line, save_to_card

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
    print(f"  SSID        : {ssid or '(not set)'}")
    print(f"  IP address  : {ip or '0.0.0.0'}")
    print(f"  FTP user    : {user or '(none)'}")
    if ip and ip != "0.0.0.0":
        print(f"\n  FTP server: ftp://{ip}/   (user: {user or 'anonymous'})")
    return ip


def keychain_available():
    return sys.platform == "darwin"


def keychain_read(account):
    if not keychain_available():
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def keychain_write(account, value):
    if not keychain_available():
        print("Remembering passwords only works on macOS - skipping.")
        return
    subprocess.run(
        ["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE,
         "-a", account, "-w", value, "-D", "Wi-Fi password for STWIN.box"],
        check=True, capture_output=True,
    )
    print(f"Password stored in the keychain (service {KEYCHAIN_SERVICE}, account {account}).")


def keychain_delete(account):
    if not keychain_available():
        return
    result = subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account],
        capture_output=True, text=True,
    )
    print("Removed from the keychain." if result.returncode == 0 else "There was no such entry.")


def password(given, account, prompt):
    """Order of preference: argument, keychain, interactive prompt."""
    if given is not None:
        return given, False
    stored = keychain_read(account)
    if stored:
        print("Using the password from the keychain.")
        return stored, True
    return getpass.getpass(prompt), False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="action", required=True)

    sub.add_parser("status", help="shows the current configuration")

    p_con = sub.add_parser("connect", help="connects to a Wi-Fi network")
    p_con.add_argument("--ssid", required=True)
    p_con.add_argument("--password", default=None,
                       help="omit it to use the keychain or be asked interactively")
    p_con.add_argument("--remember", action="store_true",
                       help="stores the password in the macOS keychain for next time")
    p_con.add_argument("--timeout", type=float, default=30.0,
                       help="how many seconds to wait for an IP address")

    sub.add_parser("disconnect", help="disconnects Wi-Fi")

    p_forget = sub.add_parser("forget", help="removes the password from the keychain")
    p_forget.add_argument("--ssid", required=True)

    p_ftp = sub.add_parser("ftp", help="sets the FTP login credentials")
    p_ftp.add_argument("--user", required=True)
    p_ftp.add_argument("--password", default=None)

    sub.add_parser("save", help="writes the configuration to the SD card (without passwords)")

    args = ap.parse_args()

    if args.action == "forget":
        keychain_delete(args.ssid)
        return

    hsd = connect()
    dev = 0
    print(firmware_line(hsd, dev))
    print()

    if args.action == "status":
        print_status(hsd, dev)

    elif args.action == "connect":
        pwd, from_keychain = password(args.password, args.ssid,
                                      f"Password for network {args.ssid}: ")
        if args.remember and not from_keychain:
            keychain_write(args.ssid, pwd)
        hsd.set_property(dev, args.ssid, COMP, "ssid")
        send(hsd, dev, "wifi_connect", "password", pwd)

        print(f"Connecting to {args.ssid}...")
        ip = None
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            time.sleep(2)
            _, ip, _ = read_status(hsd, dev)
            if ip and ip != "0.0.0.0":
                break

        print()
        if not ip or ip == "0.0.0.0":
            print("No IP address within the given time.\n")
            print("The most common cause: outdated firmware on the EMW3080 module.")
            print("ST's documentation requires updating it before using Wi-Fi")
            print("in DATALOG2 - the binary ships with the FP-SNS-DATALOG2 package,")
            print("under Utilities/WiFi_module_upgrade.")
            print("\nAlso check the network runs on 2.4 GHz - the module has no 5 GHz.")
        else:
            print_status(hsd, dev)

    elif args.action == "disconnect":
        send(hsd, dev, "wifi_disconnect")
        print("Disconnected.")

    elif args.action == "ftp":
        pwd, _ = password(args.password, f"ftp:{args.user}", f"FTP password for {args.user}: ")
        hsd.set_property(dev, args.user, COMP, "ftp_username")
        send(hsd, dev, "set_ftp_credentials", "password", pwd)
        print("FTP credentials set.\n")
        print_status(hsd, dev)

    elif args.action == "save":
        print("Writing device_config.json to the card...")
        save_to_card(hsd, dev)
        print("Saved. The board will load this file at startup.\n")
        print("What is persisted: the SSID, the FTP user name and the set of")
        print("enabled sensors together with their ODRs and ranges.")
        print("The password is NOT persisted - the firmware keeps it in RAM only.")

    hsd.close()


if __name__ == "__main__":
    main()
