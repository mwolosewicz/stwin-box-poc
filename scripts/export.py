#!/usr/bin/env python3
"""Converts a recording into a flat numpy array, so analysis needs no SDK.

The .dat file cannot be read with np.fromfile as it stands: it is a sequence of
packets, each opening with a 4-byte counter, and the sample stream inside has a
float64 timestamp injected after every samples_per_ts samples. This strips both
and writes out a plain (N, axes) array that np.load can memory-map.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

COUNTER_SIZE = 4  # every packet opens with a uint32 byte counter
TIMESTAMP_SIZE = 8  # float64, one after each block of samples_per_ts samples

DTYPES = {"int8": np.int8, "uint8": np.uint8, "int16": np.int16,
          "uint16": np.uint16, "int32": np.int32, "uint32": np.uint32,
          "float": np.float32, "double": np.float64}


def component_status(folder: Path, name=None):
    cfg = json.loads((folder / "device_config.json").read_text())
    components = cfg["devices"][0]["components"]
    if name is None:
        dat = sorted(folder.glob("*.dat"))
        if not dat:
            sys.exit(f"No .dat files in {folder}")
        name = dat[0].stem
    for c in components:
        if name in c:
            return name, c[name]
    sys.exit(f"No component {name} in device_config.json")


def packet_size(status, interface):
    """Payload bytes per packet. The field depends on where the data came from."""
    field = {0: "sd_dps", 1: "usb_dps", 2: "ble_dps", 3: "serial_dps"}.get(interface)
    if field is None:
        sys.exit(f"Unknown interface: {interface}")
    size = status.get(field)
    if not size:
        sys.exit(f"No {field} in the configuration of this component")
    # On the card the firmware counts the counter into the declared packet size;
    # on the other interfaces it is added on top of it.
    return size - COUNTER_SIZE if interface == 0 else size


def convert(folder: Path, name, status, interface):
    dtype = DTYPES.get(status["data_type"])
    if dtype is None:
        sys.exit(f"Unsupported data type: {status['data_type']}")
    dim = status["dim"]
    spts = status.get("samples_per_ts", 0)

    payload_size = packet_size(status, interface)
    full_packet = payload_size + COUNTER_SIZE
    path = folder / f"{name}.dat"
    n_packets = path.stat().st_size // full_packet

    raw = np.fromfile(path, dtype=np.uint8, count=n_packets * full_packet)
    raw = raw.reshape(n_packets, full_packet)

    # The counter holds a running payload byte total. A step other than the
    # payload size means the firmware dropped packets - worth knowing about,
    # because the timestamps stay plausible and the loss is otherwise invisible.
    counters = raw[:, :COUNTER_SIZE].copy().view(np.uint32).ravel().astype(np.int64)
    gaps = int((np.diff(counters) != payload_size).sum())

    payload = raw[:, COUNTER_SIZE:].ravel()

    if spts:
        frame = spts * dim * np.dtype(dtype).itemsize + TIMESTAMP_SIZE
        n_frames = payload.size // frame
        payload = payload[:n_frames * frame].reshape(n_frames, frame)
        split = spts * dim * np.dtype(dtype).itemsize
        data = payload[:, :split].copy().view(dtype).reshape(-1, dim)
        times = payload[:, split:].copy().view(np.float64).ravel()
    else:
        n_samples = payload.size // (dim * np.dtype(dtype).itemsize)
        data = payload[:n_samples * dim * np.dtype(dtype).itemsize].copy()
        data = data.view(dtype).reshape(-1, dim)
        times = np.array([])

    return data, times, gaps


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path, help="acquisition directory")
    ap.add_argument("--sensor", default=None, help="component (default: first .dat)")
    ap.add_argument("--out", type=Path, default=None,
                    help="output directory (default: the acquisition directory)")
    ap.add_argument("--float", dest="as_float", action="store_true",
                    help="write float32 in g instead of raw int16 (twice the size)")
    args = ap.parse_args()

    folder = args.folder
    out = args.out or folder
    out.mkdir(parents=True, exist_ok=True)

    acq = json.loads((folder / "acquisition_info.json").read_text())
    name, status = component_status(folder, args.sensor)
    data, times, gaps = convert(folder, name, status, acq["interface"])

    spts = status.get("samples_per_ts", 0)
    sensitivity = status.get("sensitivity", 1.0)
    if len(times) > 1:
        # Across the whole file rather than from neighbouring timestamps: the
        # firmware's own measodr is off by enough to drift by over a second
        # across a couple of hours.
        fs = (len(times) - 1) * spts / (times[-1] - times[0])
    else:
        fs = float(status.get("measodr") or 0.0)

    if args.as_float:
        array = (data.astype(np.float32) * np.float32(sensitivity))
        unit, stored = "g", "float32"
    else:
        array = data
        unit, stored = "LSB", str(data.dtype)

    np.save(out / f"{name}.npy", array)
    if len(times):
        np.save(out / f"{name}_time.npy", times)
    meta = {
        "component": name,
        "samples": int(len(data)),
        "axes": int(data.shape[1]),
        "dtype": stored,
        "unit": unit,
        "sensitivity": None if args.as_float else sensitivity,
        "fs": fs,
        "samples_per_ts": spts,
        "duration_s": len(data) / fs if fs else None,
        "source": str(folder),
        "interface": acq["interface"],
        "dropped_packet_gaps": gaps,
    }
    (out / f"{name}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    mb = array.nbytes / 2**20
    print(f"{name}: {len(data):,} samples x {data.shape[1]} axes, "
          f"fs = {fs:,.2f} Hz, {len(data)/fs/60:.1f} min")
    print(f"Packet counter gaps: {gaps}" + ("  <- data was lost" if gaps else ""))
    print(f"\nWritten to {out}/")
    print(f"  {name}.npy         {mb:,.0f} MB  ({stored}, {unit})")
    if len(times):
        print(f"  {name}_time.npy    timestamp per {spts} samples")
    print(f"  {name}.meta.json")
    print(f"""
    import json, numpy as np
    meta = json.load(open("{out}/{name}.meta.json"))
    a = np.load("{out}/{name}.npy", mmap_mode="r")   # no RAM used until sliced
    """.rstrip())


if __name__ == "__main__":
    main()
