# STWIN.box – PoC tooling

A set of scripts for working with the **STEVAL-STWINBX1** board (STWIN.box)
running the **FP-SNS-DATALOG2** firmware, over USB, with no SD card and no phone.

The goal: one command to record a machine's vibration, a second to see the
spectrum, and a third to compare a healthy state against a damaged one.

## Installation

```bash
git clone <this-repo-url> ~/git/stwin-box-poc
cd ~/git/stwin-box-poc
./setup.sh
```

`setup.sh` clones ST's SDK, fetches its submodules, creates an isolated Python
3.12 environment and installs everything needed. It can be run repeatedly. The
first run takes about 2–3 minutes.

Then plug the board in with a USB-C cable (it must carry data, not just power):

```bash
./stwin probe
```

## Usage

### Checking the board

```bash
./stwin probe            # firmware, sensor list, what each one is for
./stwin probe --json     # full device status
```

### Preparing the board for mounting

When the node is to work on its own — mounted at the machine, started with the
USR button, with data landing on the card — it has to be told beforehand which
sensors should collect data, and that has to be persisted so it survives a reset:

```bash
./stwin prepare --sensor iis3dwb_acc
./stwin prepare --sensor ism330dhcx_acc,ism330dhcx_gyro
./stwin prepare --sensor iis3dwb_acc --no-save    # apply only, do not persist
```

The command enables the listed sensors, disables the rest and writes the
configuration to the card through the firmware's `save_config`. Along the way it
shows how much data per hour the chosen set will produce and how many hours the
card will last — with `iis3dwb_acc` that is 575 MB/h, a little over two days on
a 32 GB card.

The size is derived from the `sd_dps` field, which the firmware reports for the
current ODR, and not from the `odr` field — the latter is an enum index, not
hertz. The firmware rounds `sd_dps` up to a multiple of 512 B, so for slow
sensors the result is overstated; for the fast ones that dominate the budget the
error drops below a percent.

While it is at it, `prepare` sets the **board clock** to the computer's time.
This only matters for acquisitions started without a computer: recordings made
over USB get the right time by themselves, because the SDK sets the RTC on every
`start_log`, but an acquisition started from the USR button or from automode has
nowhere to get it from and the files on the card end up with a date counted from
zero. Power keeps the clock running — after cutting USB and the battery it has
to be set again. This can be turned off with `--no-clock`.

### Checking the board clock

```bash
./stwin clock
```

Prints the board's time next to the computer's and the difference between them.
Worth running before mounting the device, and again after coming back to it —
the date on everything the board writes to the card on its own depends on it.

The firmware exposes no time property, so there is nothing to simply read: the
`log_controller` component has a `set_time` command and no counterpart to get it
back. The one place the clock surfaces is `acquisition_info.start_time`, which
the firmware stamps when an acquisition starts. So the script starts one for a
fraction of a second, reads the stamp and stops. The acquisition goes to the USB
interface rather than to the card, so nothing is written to the card and none
needs to be inserted.

Two consequences of taking the reading that way. The clock cannot be read while
a recording is in progress, and it cannot be read with every sensor disabled —
the firmware refuses to start an acquisition that would collect nothing, and the
script passes its complaint on rather than reporting the previous acquisition's
stamp as if it were the current time. And the resolution is one second, so a
difference of a second or so means the clocks agree.

**The board clock runs slow, and not by a little.** Measured over ten minutes
against a freshly synchronised start, it lost 1.87% of the elapsed time — 1.1 s
a minute, 27 minutes a day, holding steady to within a few percent of itself
across the run. That is the order of magnitude of an RC oscillator rather than a
crystal, and nothing on the computer's side can compensate for it. Two things
follow: set the clock immediately before mounting the device rather than the day
before, and after a day of unattended running treat the dates on the card as
good to the nearest half hour. If you need to line a card recording up with an
external log more precisely than that, anchor it on an event visible in both
signals instead of on the timestamp.

Ironically this makes `./stwin clock` most useful read backwards: the difference
it prints, divided by that rate, says how long ago the clock was last set. The
script prints that estimate too.

Without `prepare` the same thing can be achieved in a roundabout way —
`./stwin record` also switches sensors — but the change then lives in RAM only
and is lost on reset.

### Recording

```bash
./stwin record desk_background --duration 6
./stwin record fan_healthy --duration 20
./stwin record fan_unbalanced --duration 20 --note "2 g of putty on a blade"
./stwin record washing_machine --sensor ism330dhcx_acc --duration 600
./stwin record bearing --sensor iis3dwb_acc,ism330dhcx_acc \
  --odr iis3dwb_acc=26667 --odr ism330dhcx_acc=6667 \
  --fs ism330dhcx_acc=16 --duration 60
./stwin record pump_baseline --duration 60 --out /mnt/usb/recordings
```

The recording lands in `recordings/<name>_<date>/` as a complete set of
HSDatalog files: the raw `.dat`, `device_config.json` and
`acquisition_info.json`. By default `iis3dwb_acc` is recorded and the other
sensors are disabled, so that streams with wildly different rates do not get
mixed. Pass a comma-separated list to `--sensor` to record several sensors at
once. `--odr NAME=HZ` and `--fs NAME=RANGE` set a sensor's output data rate and
measurement range; repeat either option to configure multiple sensors. Use
`--sensor all` to keep the board's current sensor configuration unchanged.

`--out` points the recording somewhere else — useful when the repo sits on a
small or slow disk, like the SD card of a Raspberry Pi, and the data should go
to an attached drive. The same thing can be set once and for all with the
`STWIN_RECORDINGS` environment variable; the flag wins when both are given.

### Analysis

```bash
./stwin analyze recordings/fan_healthy_20260901_204512
./stwin analyze recordings/fan_healthy_20260901_204512 --rpm 2400 --fmax 300
```

Writes `spectrum.png` into the recording's directory: the time series, the
amplitude spectrum across the full band and the PSD over the low frequencies.
`--rpm` adds markers at 1x, 2x, 3x of the rotational frequency — imbalance sits
at 1x.

> This loads the whole recording into memory and tops out around 10 M samples —
> roughly 20 minutes at 7 kHz. On anything longer it analyses the beginning and
> says so only in the sample count. For recordings measured in hours use
> `./stwin export` and see [docs/data-analysis.md](docs/data-analysis.md).

### Export for analysis in numpy

```bash
./stwin export recordings/rura
./stwin export recordings/rura --float --out /tmp/rura
```

Rewrites the `.dat` as a flat `.npy` array that `np.load(..., mmap_mode="r")`
can memory-map, alongside a `.meta.json` with the sampling rate and the
sensitivity, and the raw per-block timestamps. A 385 MB recording converts in
under a second and the result is bit-identical to what the SDK returns.

This is the way to work with long recordings. The SDK's reader is built for
whole files or for sequential streaming, its windowed variant computes file
offsets from the firmware's nominal rate and drifts by over a second across a
couple of hours, and it stores parser state inside the component dictionary you
pass it. With a memory-mapped array none of that applies and no dependency
beyond numpy is needed.

The conversion also checks the per-packet byte counters and reports gaps, which
is the only way to notice that the firmware dropped data — the timestamps stay
plausible either way.

### Comparing a healthy state against a damaged one

```bash
./stwin compare recordings/fan_healthy_... recordings/fan_unbalanced_... --rpm 2400
```

Overlays both spectra and plots their ratio. It prints at which frequency the
increase is largest and how big it is. This is the fastest way to check whether
the damage is visible at all — before starting to build a model.

The peak is looked for on the smoothed curve (`--smooth`, 9 bins by default),
because Welch's estimator can produce several-fold jumps in single bins on noise
alone. If the smoothed increase does not exceed 2x, the script says outright
that the classes are not separated.

### Wi-Fi and the FTP server

The firmware has a built-in FTP server that serves the contents of the SD card.
It is configured over USB, with no phone involved:

```bash
./stwin wifi status
./stwin wifi connect --ssid MyNetwork      # will ask for the password
./stwin wifi ftp --user username           # will ask for the password
./stwin wifi disconnect
```

Omitting `--password` triggers an interactive prompt, so that the password does
not end up in the shell history. After a successful connection the script prints
the address the board serves FTP on.

This is the only way to get data off the card without taking it out of the
board — it cannot be done over USB, because the firmware does not present itself
as mass storage. Useful for a node permanently mounted at a machine.

#### What survives a reset and what does not

**The password cannot be stored on the board.** In the DATALOG2 code
(`app_netxduo.c`) `wifi_password` and `ftp_password` are plain character arrays
in RAM, zeroed on every boot. There is no write to flash nor to the Wi-Fi
module. After every reset they have to be sent again — there is no way around it
without modifying the firmware.

That is why the password is kept on the computer side, in the macOS keychain:

```bash
./stwin wifi connect --ssid MyNetwork --remember   # once, on the first connection
./stwin wifi connect --ssid MyNetwork              # afterwards, without being asked
./stwin wifi forget --ssid MyNetwork               # removing the entry
```

#### Configuring from a phone, without a computer

Keeping the password in the keychain only helps when you can walk up to the
board with a laptop and a cable. With a node mounted on a machine that is
usually impossible — and then BLE is the way out. The same `wifi_config`
component that `./stwin wifi` drives is exposed over Bluetooth to the **ST BLE
Sensor** app; in the device model it appears as a separate "Applications ST BLE
Sensor" entry with a `wifi_config` field. So after a reset you walk up with a
phone, connect over BLE and send the password from there.

Before the device goes on site, it is worth checking whether it will be visible
at all and whether the signal reaches the place you want to configure it from:

```bash
./stwin ble           # looks for the board and shows the signal strength
./stwin ble --all     # every BLE device, when the board cannot be seen
```

The board advertises under a name carrying the firmware version — with 3.3.0
that is `HSD2v33`. You will see it under the same name in the phone app. It also
advertises during an active USB session, so the test does not require unplugging
the cable.

An RSSI stronger than −70 dBm means configuring from a phone will be no trouble;
below −85 dBm you have to walk right up to the device. Measure this **after**
mounting, from the spot you will realistically operate the node from — the sheet
metal of a control cabinet can eat tens of dB.

> The ST BLE Sensor app shows an incomplete sensor list (see below), so before
> trusting this route, walk the whole path once at the desk: reset the board,
> connect from the phone, enter the password, confirm it got an IP address.

**The SSID, the FTP user name and the sensor configuration do survive a reset**,
provided you write them to the card:

```bash
./stwin wifi save
```

This calls the firmware's `save_config`, which writes `device_config.json` into
the root directory of the SD card; the board loads that file at startup. The
complete sensor settings are stored — enabled channels, ODRs, ranges — so it is
useful outside the Wi-Fi context too, for preparing the board for field
recordings.

> **Careful.** `save_config` without a card inserted can hang the firmware while
> trying to mount it, and then only the RESET button helps. The script checks
> `sd_mounted` and refuses when there is no card.

#### Anonymous FTP

It does not need to be enabled — that is the default state. The firmware starts
with `ftp_username = "anonymous"` and an empty password, and access control is a
plain comparison of both fields. You log in as `anonymous` with an empty password
and it works.

The IP address cannot be set from the board — the `ip` property is read-only and
the address comes from DHCP. For a fixed address, make a DHCP reservation on the
router against the Wi-Fi module's MAC. Careful: the MAC shown by `./stwin probe`
belongs to the Bluetooth module, not the Wi-Fi one — you will see the latter on
the router after the first successful connection.

Three conditions that are easy to trip over:

- **The EMW3080 module's firmware must be up to date.** ST's documentation lists
  this as a requirement for DATALOG2 to work on the STWIN.box. The binary ships
  with the FP-SNS-DATALOG2 package, under `Utilities/WiFi_module_upgrade`.
  Without it the connection will not come up, and the script will say so.
- **2.4 GHz only** — the module has no 5 GHz support.
- **An SD card must be inserted**, because FTP serves exactly its contents.

### Export to NanoEdge AI Studio

```bash
./stwin nanoedge recordings/fan_healthy_... -sl 1024 -o dataset/normal
./stwin nanoedge recordings/fan_unbalanced_... -sl 1024 -o dataset/anomaly
```

`-sl` is the window length in samples; it must be the same for both classes and
the same as in the on-device configuration. It calls ST's original converter, so
it accepts all of its options (`-h` shows the full list).

## Choosing a sensor

The board has nine sensors and one of them is usually the obvious choice.

| Task | Sensor | Notes |
|---|---|---|
| Machine vibration, bearings | `iis3dwb_acc` | 26.7 kHz, band up to 6 kHz, 75 µg/√Hz |
| Long recordings (hours) | `ism330dhcx_acc` | 18 MB/h instead of 570 MB/h |
| Compressed air leaks | `imp23absu_mic` | band up to 80 kHz, ultrasound 25–45 kHz |
| Water flow, acoustic events | `imp34dt05_mic` | audible band |
| Tilt, very low frequencies | `iis2iclx_acc` | ±0.5 g, 15 µg/√Hz |
| Detecting a running motor | `iis2mdc_mag` | stray field, a free "the device draws current" signal |
| Battery-powered standby | `iis2dlpc_acc` | a few µA, wake on threshold |

## Things that catch you out

**The real ODR differs from the catalogue one.** The ISM330DHCX at a nominal
6,667 Hz was measured at 7,299 Hz — 9.5% out, which at 500 Hz would put a peak
47 Hz away from where you look for it. The IIS3DWB is well behaved by
comparison: 26,649 Hz against a nominal 26,667 Hz. The scripts compute `fs`
from the timestamps rather than the nominal value — if you write your own
analysis, do the same.

**Do not take a median of the timestamp differences.** The SDK quantises its
`Time` column to a microsecond, so at 26 kHz the per-sample differences only
ever come out as 37 or 38 µs. A median picks one of them and claims
26,316 Hz — a 1.25% error, and the source of a figure that earlier versions of
this file reported as a property of the sensor. Average over the whole span
instead: `(len(t) - 1) / (t[-1] - t[0])`.

**ODR and FS in the device model are enum indices, not hertz and not g.**
`odr=0` for the IIS3DWB means its only available value, i.e. 26,667 Hz.

**The board clock loses 27 minutes a day.** See `./stwin clock` above. Anything
the board timestamps on its own drifts at that rate from the moment the clock was
set.

**The ST BLE Sensor app shows an incomplete sensor list.** The IIS3DWB is
missing from it, among others, because 1.3 Mbit/s will not fit through BLE. The
board and the firmware see the full set — `./stwin probe` shows it.

**The card has to be FAT32, and that caps a recording at 4 GiB.** The firmware
does not support exFAT: in the DATALOG2 project for the STWIN.box,
`FileX/Target/fx_user.h` has `#define FX_ENABLE_EXFAT` commented out — exFAT
needs a separate licence from Microsoft — and nothing else in the project turns
it on. An exFAT card will not mount. The 4 GiB ceiling on a single file works
out at 27 hours of `ism330dhcx_acc` at 6.7 kHz, or under 8 hours of
`iis3dwb_acc`. ST tested with FAT32 formatted at a 32 KB allocation unit.

**The SD card cannot be read over USB.** The firmware exposes a HID interface
with the PnPL protocol for control and streaming, not mass storage. Data is
taken off the card with a reader or through the FTP server over Wi-Fi
(`./stwin wifi`). When working at a desk it is simplest not to use the card at
all and stream over USB — that is how these scripts work.

**Mounting decides the outcome more than the model does.** Rigid bolting or
glue; double-sided tape and foam act as a low-pass filter and kill everything
above roughly 1 kHz. Remounting the sensor changes the signature enough that a
model trained before the move will raise false alarms — it is worth having
several different mountings in the training data.

## Layout

```
setup.sh              SDK and environment installation
stwin                 entry point to all the tools
scripts/_common.py    connection, loading recordings, spectra, plots
scripts/probe.py      board state and sensor list
scripts/prepare.py    sensor selection and persisting the configuration to the card
scripts/clock.py      reading the board clock and comparing it with the computer's
scripts/record.py     acquisition over USB
scripts/analyze.py    time series, spectrum, PSD
scripts/export.py     conversion of a recording to a flat .npy array
scripts/compare.py    comparison of two recordings
scripts/wifi.py       Wi-Fi and FTP server configuration
scripts/ble.py        BLE scan - board visibility and signal strength
recordings/           acquisition results (outside the repository)
vendor/               ST's SDK (outside the repository, fetched by setup.sh)
docs/data-analysis.md browsing and analysing recordings, with exercises
docs/zbieranie-danych.md  collecting a day of data and separating water sources
docs/hydrofor-rul.md  predicting when the hydrophore's air cushion runs out
```

## Troubleshooting

The SDK is very talkative and some of its messages are plain `print()` calls
formatted to look like logger entries — which is why the scripts filter the
output. If something does not work and you want to see everything:

```bash
STWIN_DEBUG=1 ./stwin probe
```

When the board is not found: check that the USB-C cable carries data and that no
other program is holding the device (the SDK GUI, ST BLE Sensor over USB).

If the scripts say the board is visible on USB but does not answer commands, the
firmware has hung. This happens after an interrupted SD card operation. Only the
RESET button helps; unplugging USB alone is not enough when a battery is
attached. In that situation the SDK quietly falls back to the serial backend and
only blows up on the first command, which is why the scripts check connectivity
right after connecting and say plainly what to do.

## Requirements

macOS or Linux, `git`, `curl`. `uv` and Python 3.12 install themselves through
`setup.sh`. The board must have FP-SNS-DATALOG2 flashed — tested with 3.3.0.
