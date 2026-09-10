from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze one cooperative ZR10 log session")
    parser.add_argument("session_dir", help="Path containing telemetry.csv")
    return parser.parse_args()


def save_line_plot(df: pd.DataFrame, y_target: str, y_actual: str, ylabel: str, output: Path) -> None:
    fig, ax = plt.subplots()
    for gimbal_id, group in df.groupby("gimbal_id", sort=True):
        group = group.sort_values("elapsed_s")
        ax.plot(group["elapsed_s"], group[y_target], linestyle="--", label=f"{gimbal_id} target")
        ax.plot(group["elapsed_s"], group[y_actual], label=f"{gimbal_id} actual")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(ylabel)
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    session_dir = Path(args.session_dir).expanduser().resolve()
    telemetry_path = session_dir / "telemetry.csv"
    df = pd.read_csv(telemetry_path)

    numeric_columns = [
        "elapsed_s",
        "target_azimuth_deg",
        "target_elevation_deg",
        "actual_azimuth_deg",
        "actual_elevation_deg",
        "azimuth_error_deg",
        "elevation_error_deg",
        "ae_error_norm_deg",
        "command_latency_ms",
        "command_batch_offset_ms",
        "feedback_age_ms",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    summary_rows = []
    for gimbal_id, group in df.groupby("gimbal_id", sort=True):
        summary_rows.append(
            {
                "gimbal_id": gimbal_id,
                "samples": len(group),
                "azimuth_rmse_deg": (group["azimuth_error_deg"].pow(2).mean()) ** 0.5,
                "elevation_rmse_deg": (group["elevation_error_deg"].pow(2).mean()) ** 0.5,
                "ae_rmse_deg": (group["ae_error_norm_deg"].pow(2).mean()) ** 0.5,
                "ae_max_error_deg": group["ae_error_norm_deg"].max(),
                "mean_command_latency_ms": group.loc[
                    group["command_sent"] == True, "command_latency_ms"  # noqa: E712
                ].mean(),
                "max_command_batch_offset_ms": group["command_batch_offset_ms"].max(),
                "mean_feedback_age_ms": group["feedback_age_ms"].mean(),
                "stale_feedback_ratio": group["feedback_stale"].astype(str).str.lower().eq("true").mean(),
                "command_error_rows": group["command_status"].astype(str).eq("error").sum(),
            }
        )

    summary = pd.DataFrame(summary_rows)
    summary_path = session_dir / "analysis_summary.csv"
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")

    save_line_plot(
        df,
        "target_azimuth_deg",
        "actual_azimuth_deg",
        "Azimuth (deg)",
        session_dir / "azimuth_tracking.png",
    )
    save_line_plot(
        df,
        "target_elevation_deg",
        "actual_elevation_deg",
        "Elevation (deg)",
        session_dir / "elevation_tracking.png",
    )

    fig, ax = plt.subplots()
    for gimbal_id, group in df.groupby("gimbal_id", sort=True):
        group = group.sort_values("elapsed_s")
        ax.plot(group["elapsed_s"], group["ae_error_norm_deg"], label=gimbal_id)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("AE error norm (deg)")
    ax.grid(True)
    ax.legend()
    fig.tight_layout()
    fig.savefig(session_dir / "ae_error_norm.png", dpi=180)
    plt.close(fig)

    print(summary.to_string(index=False))
    print(f"\nSaved: {summary_path}")


if __name__ == "__main__":
    main()
