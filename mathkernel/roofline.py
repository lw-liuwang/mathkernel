"""Render Roofline data supplied by an experiment report."""

import json
import math
import os
from pathlib import Path

from .inputs import InputError
from .paths import scratch_directory


def plot_roofline_data(data, output):
    """Plot evaluated sequential operations independently of the kernel model."""
    os.environ.setdefault("MPLCONFIGDIR", str(scratch_directory() / "matplotlib"))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.ticker import LogLocator, FuncFormatter
    except ImportError as error:
        raise InputError("Install requirements-plot.txt and run roofline with that Python environment") from error

    hardware, points = data["hardware"], data["points"]
    peak = hardware["peak_flops_per_second"] / 10**12
    bandwidth = hardware["hbm_bytes_per_second"]
    ridge = data["ridge_intensity_flops_per_byte"]
    positioned = [point for point in points if point["intensity_flops_per_byte"] and point["performance_tflops"] > 0]
    low = min(min((point["intensity_flops_per_byte"] for point in positioned), default=ridge) / 4, ridge / 8)
    high = max(max((point["intensity_flops_per_byte"] for point in positioned), default=ridge) * 4, ridge * 4)
    x_values = [math.exp(math.log(low) + index * math.log(high / low) / 255) for index in range(256)]
    x_values.append(ridge)
    x_values.sort()
    y_values = [min(peak, bandwidth * intensity / 10**12) for intensity in x_values]
    colors = {"baseline": "#2563eb", "candidate": "#ea580c"}

    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 11}):
        figure, (axis, timing) = plt.subplots(
            1, 2, figsize=(13.6, 6.3), gridspec_kw={"width_ratios": [2.5, 1]},
            layout="constrained",
        )
        figure.suptitle("MathKernel: modeled Roofline", fontsize=18, fontweight="bold")
        axis.set_title("Modeled throughput and arithmetic intensity", loc="left", pad=18)
        axis.set_xscale("log", base=2)
        axis.set_yscale("log", base=2)
        axis.plot(x_values, y_values, color="#334155", linewidth=2.4)
        axis.axvline(ridge, color="#94a3b8", linestyle="--", linewidth=1)
        axis.text(ridge * 1.08, peak * 0.45, f"Ridge: {ridge:g} FLOP/B", fontsize=10, color="#475569")
        axis.text(high * 0.92, peak * 1.12, f"Compute ceiling: {peak:g} TFLOP/s", ha="right", fontsize=10)
        axis.text(low * 1.2, min(peak, bandwidth * low * 1.2 / 10**12) * 1.45,
                  f"Bandwidth: {bandwidth / 10**12:g} TB/s", rotation=32, color="#475569", fontsize=10)

        for point in positioned:
            baseline = point["plan"] == "baseline"
            total = point["kind"] == "total"
            axis.scatter(
                point["intensity_flops_per_byte"], point["performance_tflops"],
                marker="o" if baseline else "x", s=(230 if total else 130) if baseline else (100 if total else 65),
                facecolors="white" if baseline else colors["candidate"],
                edgecolors=colors[point["plan"]] if baseline else None,
                color=colors[point["plan"]], linewidths=2.2, zorder=5 if baseline else 6,
            )

        groups = {}
        for point in positioned:
            key = (point["intensity_flops_per_byte"], point["performance_tflops"], point["kind"])
            groups.setdefault(key, []).append(point)
        operation_index = 0
        for (intensity, performance, kind), group in sorted(groups.items()):
            if kind == "total":
                label = " / ".join(point["plan"].capitalize() for point in group) + " total"
                text = f"{label}\n{intensity:.3f} FLOP/B; {performance:.3f} TFLOP/s"
                offset = (28, -65)
            else:
                text = " / ".join(dict.fromkeys(point["label"] for point in group))
                offset = (-70, 32) if operation_index % 2 == 0 else (20, -15)
                operation_index += 1
            axis.annotate(text, (intensity, performance), xytext=offset, textcoords="offset points",
                          fontsize=9, arrowprops={"arrowstyle": "-", "color": "#94a3b8"})

        axis.set_xlim(low, high)
        axis.set_ylim(min(y_values) / 1.7, peak * 1.65)
        axis.set_xlabel("Arithmetic intensity (FLOP / byte)")
        axis.set_ylabel("Modeled throughput (TFLOP / s)")
        for log_axis in (axis.xaxis, axis.yaxis):
            log_axis.set_major_locator(LogLocator(base=2))
            log_axis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
        axis.grid(which="major", alpha=0.18)
        axis.legend(handles=[
            Line2D([], [], marker="o", color=colors["baseline"], markerfacecolor="white", linestyle="none", markersize=9, label="Baseline"),
            Line2D([], [], marker="x", color=colors["candidate"], linestyle="none", markersize=8, label="Candidate"),
        ], loc="upper left", frameon=False)

        totals = [point for point in points if point["kind"] == "total"]
        times = [point["estimated_microseconds"] for point in totals]
        timing.barh([1, 0], times, color=[colors[point["plan"]] for point in totals], height=0.42)
        for row, microseconds in zip((1, 0), times):
            timing.text(microseconds + max(times) * 0.03, row, f"{microseconds:.6f}", va="center", fontsize=10)
        timing.set_yticks([1, 0], ["Baseline", "Candidate"])
        timing.set_xlim(0, max(times) * 1.5)
        timing.set_ylim(-0.8, 1.8)
        timing.set_xlabel("Modeled time (microseconds)")
        title = f"Baseline / candidate: {data['model_speedup']:g}x" if data["model_speedup"] is not None else "Model time comparison"
        timing.set_title(title, loc="left", pad=18)
        timing.grid(axis="x", alpha=0.18)
        timing.set_axisbelow(True)
        for panel in (axis, timing):
            panel.spines[["top", "right"]].set_visible(False)

        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        files = {extension: Path(str(output) + "." + extension) for extension in ("png", "json")}
        figure.savefig(files["png"], dpi=180)
        plt.close(figure)
    files["json"].write_text(json.dumps(data, indent=2) + "\n")
    return {"artifacts": {key: str(path.resolve()) for key, path in files.items()}, "roofline": data}
