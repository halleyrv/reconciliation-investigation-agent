"""Command line: `simulate` generates a run, `simulate-verify` checks one."""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from simulator.checks import explain, find_violations, validate_files
from simulator.config import ConfigError, load_config
from simulator.export import render, write
from simulator.generator import generate
from simulator.sim import GenerationError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simulate", description="Generate a synthetic financial dataset with ground truth."
    )
    parser.add_argument("--config", type=Path, required=True, help="YAML config file")
    parser.add_argument("--seed", type=int, required=True, help="random seed")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        files = render(generate(config, args.seed), config, args.seed)
    except (ConfigError, GenerationError) as error:
        print(f"simulate: error: {error}", file=sys.stderr)
        return 2
    write(files, args.out)
    print(f"wrote {len(files)} files to {args.out}")
    return 0


def verify_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="simulate-verify",
        description="Check schemas, CSV/JSON equality, invariants and ground-truth coverage.",
    )
    parser.add_argument("out", type=Path, help="directory written by `simulate`")
    args = parser.parse_args(argv)
    problems = validate_files(args.out) + explain(args.out)
    violations = find_violations(args.out)
    anomalies = json.loads((args.out / "ground_truth.json").read_text())["anomalies"]
    by_invariant = Counter(v.invariant for v in violations)
    print(f"anomalies in ground truth: {len(anomalies)}")
    print(f"invariant violations: {len(violations)} {dict(sorted(by_invariant.items()))}")
    for problem in problems:
        print(f"PROBLEM: {problem}")
    if problems:
        print(f"verification failed: {len(problems)} problems")
        return 1
    print("verification passed: every violation is explained by exactly one anomaly")
    return 0
