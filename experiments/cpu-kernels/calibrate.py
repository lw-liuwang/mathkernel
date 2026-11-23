"""Record single-CPU effective compute and payload-streaming rates."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess


FLAGS = ["-O3", "-std=c11", "-march=native", "-fno-fast-math", "-ffp-contract=off",
         "-Wall", "-Wextra", "-Werror"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, required=True)
    parser.add_argument("--cpu", type=int)
    args = parser.parse_args()
    available = os.sched_getaffinity(0)
    cpu = min(available) if args.cpu is None else args.cpu
    if cpu not in available:
        parser.error(f"CPU {cpu} is outside this process's allowed affinity")
    os.sched_setaffinity(0, {cpu})
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_suffix(".c")
    binary = build / "calibrate"
    command = ["cc", *FLAGS, str(source), "-o", str(binary)]
    subprocess.run(command, check=True)
    samples = json.loads(subprocess.check_output([str(binary)], text=True))
    compute = round(16 * samples["rounds"] / statistics.median(samples["compute_seconds"]))
    bandwidth = round(16 * samples["stream_elements"] / statistics.median(samples["stream_seconds"]))
    cache = Path(f"/sys/devices/system/cpu/cpu{cpu}/cache")
    caches = [{key: (index / key).read_text().strip()
               for key in ("level", "type", "size", "shared_cpu_list")}
              for index in sorted(cache.glob("index*"))]
    cpu_info = Path("/proc/cpuinfo").read_text().splitlines()
    model_name = next(line.split(":", 1)[1].strip() for line in cpu_info if line.startswith("model name"))
    print(json.dumps({
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(), "cpu_model": model_name, "logical_cpu": cpu,
        "cache_topology_reported_by_guest": caches,
        "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
        "compile_command": command, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "samples": samples,
        "effective_flops_per_second": compute,
        "effective_payload_bytes_per_second": bandwidth,
        "basis": "Medians of seven samples after one warmup; compute counts 16 separate FP64 operations per round; streaming counts one 8-byte read and one 8-byte write per element. These are effective calibration rates, not vendor peaks or measured DRAM transactions.",
    }, indent=2))


if __name__ == "__main__":
    main()
