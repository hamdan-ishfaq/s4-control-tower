"""Build runner: `python tasks.py all`, or name one or more stages.

Behaves the same in PowerShell and in CI. Stages run in the order given.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from pipeline.config import ROOT, load_config


def ingest(cfg: dict) -> None:
    from pipeline import ingest_m5

    ingest_m5.run(cfg)


def simulate(cfg: dict) -> None:
    from pipeline import simulate as sim

    sim.run(cfg)


def data(cfg: dict) -> None:
    ingest(cfg)
    simulate(cfg)


def models(cfg: dict) -> None:
    raise NotImplementedError("models: SQL models (M1)")


def forecast(cfg: dict) -> None:
    raise NotImplementedError("forecast: forecast and backtest (M2)")


def policy(cfg: dict) -> None:
    raise NotImplementedError("policy: safety stock and CP-SAT proposals (M2-M3)")


def exceptions(cfg: dict) -> None:
    raise NotImplementedError("exceptions: scorecard and exception rules (M3)")


def brief(cfg: dict) -> None:
    raise NotImplementedError("brief: AI brief (M3)")


def export(cfg: dict) -> None:
    raise NotImplementedError("export: Parquet, JSON, CSV and Excel (M1-M2)")


def site(cfg: dict) -> None:
    npm = shutil.which("npm")  # finds npm.cmd on Windows
    if npm is None:
        sys.exit("npm not found on PATH")
    web = ROOT / "web"
    subprocess.run([npm, "ci"], cwd=web, check=True)
    subprocess.run([npm, "run", "build"], cwd=web, check=True)


# `all` runs stages 1-8; `site` is separate because it needs Node.
PIPELINE = [data, models, forecast, policy, exceptions, brief, export]
STAGES = {f.__name__: f for f in [ingest, simulate, *PIPELINE, site]}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stages", nargs="+", choices=[*STAGES, "all"])
    parser.add_argument("--config", type=Path, default=None, help="config file (default pipeline/config.yaml)")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    stages = [s for name in args.stages for s in (PIPELINE if name == "all" else [STAGES[name]])]
    for stage in stages:
        start = time.perf_counter()
        print(f"== {stage.__name__}", flush=True)
        stage(cfg)
        print(f"== {stage.__name__} done in {time.perf_counter() - start:.1f} s", flush=True)


if __name__ == "__main__":
    main()
