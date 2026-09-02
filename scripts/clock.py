#!/usr/bin/env python3
"""Reads the board clock and compares it with the computer clock.

The firmware exposes no time property - log_controller has a set_time command
and nothing to read it back with, so ./stwin probe cannot show the clock. The
one place the RTC surfaces is acquisition_info.start_time, which the firmware
stamps when an acquisition starts. So we start one for a fraction of a second
over USB, read the stamp and stop.

The acquisition goes to the USB interface, not to the card, so nothing is
written to the card and no card needs to be inserted.
"""

import argparse
import json
import sys
import time
from datetime import datetime

from _common import connect, firmware_line, quiet

# How much drift is worth complaining about. Recordings started from the USR
# button are ordered by their file dates, and a few seconds do not matter there;
# a clock counted from zero after a power cut does.
DRIFT_FINE_S = 5
DRIFT_LOUD_S = 120

# The board clock runs slow, and not by a little: measured over ten minutes it
# loses 1.87% of the elapsed time, which is 1.1 s a minute and 27 minutes a day.
# That is the order of magnitude of an RC oscillator, not of a crystal. It means
# the reading below says as much about how long ago the clock was set as about
# the clock itself, so it is worth turning the drift back into that.
DRIFT_RATE = 0.0187


def format_drift(seconds):
    """Renders a difference in seconds as something readable: -3 s, +7 h 12 min."""
    sign = "-" if seconds < 0 else "+"
    total = int(abs(round(seconds)))
    if total < 60:
        return f"{sign}{total} s"
    if total < 3600:
        return f"{sign}{total // 60} min {total % 60} s"
    if total < 86400:
        return f"{sign}{total // 3600} h {total % 3600 // 60} min"
    return f"{sign}{total // 86400} d {total % 86400 // 3600} h"


def raw_command(hsd, dev, command, req_name=None, req_value=None):
    """Sends a PnPL command to log_controller, bypassing the SDK's wrappers.

    hsd.start_log() cannot be used here: it calls set_rtc_time first, which is
    exactly the value we are trying to read, and it creates folders for the
    recording on the way.
    """
    from stdatalog_pnpl.PnPLCmd import PnPLCMDManager

    if req_name is None:
        message = PnPLCMDManager.create_command_cmd("log_controller", command)
    else:
        message = PnPLCMDManager.create_command_cmd(
            "log_controller", command, req_name, req_value
        )
    with quiet():
        return hsd.send_command(dev, message)


def acquisition_start_time(hsd, dev):
    with quiet():
        info = hsd.get_component_status(dev, "acquisition_info")
    return info["acquisition_info"].get("start_time", "")


def refusal_reason(response):
    """The firmware's explanation when it declined the command, otherwise None."""
    text = str(response)
    if "{" not in text:
        return None
    try:
        body = json.loads(text[text.index("{"):]).get("PnPL_Response", {})
    except ValueError:
        return None
    if body.get("status"):
        return None
    return body.get("message") or "the firmware declined to start an acquisition"


def read_board_clock(hsd, dev, timeout=3.0):
    """Returns (board clock, computer clock at the same instant, error).

    The computer clock is taken right before the start command rather than after
    the whole exchange, so that connecting and polling do not show up as drift.

    The previous stamp is remembered and a new one is waited for: the firmware
    keeps the last acquisition's start_time, and a refused start would otherwise
    leave us reading a value from minutes ago as if it were the current time.
    """
    previous = acquisition_start_time(hsd, dev)

    host = datetime.now()
    response = raw_command(hsd, dev, "start_log", "interface", 1)  # 1 = USB, 0 = SD card
    refused = refusal_reason(response)
    if refused:
        return None, host, refused

    try:
        deadline = time.monotonic() + timeout
        stamp = ""
        while time.monotonic() < deadline:
            time.sleep(0.3)
            stamp = acquisition_start_time(hsd, dev)
            if stamp and stamp != previous:
                break
        else:
            return None, host, "the board did not stamp the acquisition it had started"
    finally:
        raw_command(hsd, dev, "stop_log")

    # The firmware appends a Z, but the value is the board's local time, not
    # UTC - it stores whatever it was given, without a zone.
    return datetime.strptime(stamp.rstrip("Z")[:19], "%Y-%m-%dT%H:%M:%S"), host, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.parse_args()

    hsd = connect()
    dev = 0
    print(firmware_line(hsd, dev))
    print()

    if hsd.get_component_status(dev, "log_controller")["log_controller"].get("log_status"):
        hsd.close()
        sys.exit("An acquisition is running - stop it before reading the clock.")

    board, host, error = read_board_clock(hsd, dev)
    hsd.close()

    if board is None:
        sys.exit(
            f"Cannot read the clock: {error}.\n\n"
            "The clock is only readable through the timestamp of an acquisition, so "
            "anything\nthat prevents one from starting also prevents the reading. Most "
            "often that is\nhaving no sensor enabled:\n"
            "  ./stwin prepare --sensor ism330dhcx_acc --no-save"
        )

    drift = (board - host).total_seconds()
    print(f"Board clock:     {board:%Y-%m-%d %H:%M:%S}")
    print(f"Computer clock:  {host:%Y-%m-%d %H:%M:%S}")
    print(f"Difference:      {format_drift(drift)}")

    if abs(drift) <= DRIFT_FINE_S:
        print("\nThe clocks agree, which means the board clock was set a few minutes ago "
              "at most.")
    else:
        if abs(drift) > DRIFT_LOUD_S:
            print("\nThe board clock is off. Files written to the card will carry the wrong")
            print("date, which makes recordings impossible to order in time.")
        else:
            print("\nA small difference. Enough for ordering recordings, too much for "
                  "matching them\nagainst an external log second by second.")
        print("\nSet the clock:  ./stwin prepare --no-save")

    print(f"\nThe board clock loses about {DRIFT_RATE * 60:.1f} s a minute, "
          f"{DRIFT_RATE * 86400 / 60:.0f} min a day - that is the board, not the")
    print("measurement, and it cannot be corrected from the outside. So set it right "
          "before")
    print("mounting the device, and after a day of running treat the dates on the card")
    print("as good to the nearest half hour.")
    if drift < -DRIFT_FINE_S:
        print(f"\nAt that rate the difference above amounts to roughly "
              f"{format_drift(drift / DRIFT_RATE).lstrip('-+')}\nsince the clock was set.")


if __name__ == "__main__":
    main()
