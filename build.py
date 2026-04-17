#!/usr/bin/env python3
"""Interactive top-level build helper with persisted last configuration."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


ROOT = Path(__file__).resolve().parent
LAST_CONFIG_PATH = ROOT / ".build-last-config.json"
CONFIG_VERSION = 1

PLATFORMS: dict[str, str] = {
    "linux-x86_64": "mozconfig-linux-x86_64",
    "linux-aarch64": "mozconfig-linux-aarch64",
    "macos": "mozconfig-macos",
    "windows-x86_64": "mozconfig-windows-x86_64",
    "android-arm64": "mozconfig-android-aarch64",
    "android-x86_64": "mozconfig-android-x86_64",
}

RELEASE_TYPES = ("dev", "nightly", "beta", "release")
BUILD_MODES = ("full", "artifact")


@dataclass
class BuildFlags:
    debug: bool
    optimize: bool
    jobs: str
    runAfterBuild: bool


@dataclass
class BuildConfig:
    version: int
    platform: str
    releaseType: str
    buildMode: str
    flags: BuildFlags
    updatedAt: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["flags"] = asdict(self.flags)
        return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Interactive build entrypoint with saved last config."
    )
    parser.add_argument("--last", action="store_true", help="Build using saved config.")
    parser.add_argument(
        "--show-last", action="store_true", help="Print saved config and exit."
    )
    parser.add_argument(
        "--reset-last", action="store_true", help="Delete saved config and exit."
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without prompts; requires explicit option values.",
    )
    parser.add_argument("--platform", choices=tuple(PLATFORMS), help="Target platform.")
    parser.add_argument(
        "--release-type", choices=RELEASE_TYPES, help="Release channel/type."
    )
    parser.add_argument("--build-mode", choices=BUILD_MODES, help="Build mode.")
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=None,
        help="Enable debug mode.",
    )
    parser.add_argument(
        "--no-debug",
        dest="debug",
        action="store_false",
        help="Disable debug mode.",
    )
    parser.add_argument(
        "--optimize",
        dest="optimize",
        action="store_true",
        default=None,
        help="Enable optimization.",
    )
    parser.add_argument(
        "--no-optimize",
        dest="optimize",
        action="store_false",
        help="Disable optimization.",
    )
    parser.add_argument(
        "--jobs",
        default=None,
        help='Parallel jobs ("auto" or integer string).',
    )
    parser.add_argument(
        "--run-after-build",
        action="store_true",
        default=None,
        help="Run ./mach run after successful build.",
    )
    parser.add_argument(
        "--no-run-after-build",
        dest="run_after_build",
        action="store_false",
        help="Do not run ./mach run after build.",
    )
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="Print generated command and env, then exit.",
    )
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-build-", delete=False
    ) as tf:
        json.dump(payload, tf, indent=2, sort_keys=True)
        tf.write("\n")
        temp_name = tf.name
    os.replace(temp_name, path)


def read_last_config() -> BuildConfig | None:
    if not LAST_CONFIG_PATH.exists():
        return None
    raw = json.loads(LAST_CONFIG_PATH.read_text(encoding="utf-8"))
    flags = raw.get("flags", {})
    return BuildConfig(
        version=int(raw.get("version", 0)),
        platform=str(raw["platform"]),
        releaseType=str(raw["releaseType"]),
        buildMode=str(raw["buildMode"]),
        flags=BuildFlags(
            debug=bool(flags.get("debug", False)),
            optimize=bool(flags.get("optimize", True)),
            jobs=str(flags.get("jobs", "auto")),
            runAfterBuild=bool(flags.get("runAfterBuild", False)),
        ),
        updatedAt=str(raw.get("updatedAt", "")),
    )


def validate_jobs(value: str) -> str:
    if value == "auto":
        return value
    if value.isdigit() and int(value) > 0:
        return value
    raise ValueError('jobs must be "auto" or positive integer')


def validate_config(config: BuildConfig) -> None:
    if config.platform not in PLATFORMS:
        raise ValueError(f"unsupported platform: {config.platform}")
    if config.releaseType not in RELEASE_TYPES:
        raise ValueError(f"unsupported release type: {config.releaseType}")
    if config.buildMode not in BUILD_MODES:
        raise ValueError(f"unsupported build mode: {config.buildMode}")
    config.flags.jobs = validate_jobs(config.flags.jobs)

    is_android = config.platform.startswith("android-")
    if is_android and config.buildMode == "artifact":
        raise ValueError("artifact mode is currently only supported for desktop options")
    if is_android and config.flags.runAfterBuild:
        raise ValueError("run-after-build is only supported for desktop options")


def prompt_choice(label: str, options: list[str], default: str) -> str:
    print(f"\n{label}")
    for idx, value in enumerate(options, start=1):
        marker = " (default)" if value == default else ""
        print(f"  {idx}. {value}{marker}")
    while True:
        raw = input("> ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print("Invalid selection. Enter number or exact option.")


def prompt_bool(label: str, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{label} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("Enter y or n.")


def prompt_jobs(default: str) -> str:
    while True:
        raw = input(f'jobs [default: {default}; "auto" or positive integer]: ').strip()
        if not raw:
            return default
        try:
            return validate_jobs(raw)
        except ValueError as exc:
            print(str(exc))


def build_from_args(args: argparse.Namespace) -> BuildConfig:
    missing = []
    if args.platform is None:
        missing.append("--platform")
    if args.release_type is None:
        missing.append("--release-type")
    if args.build_mode is None:
        missing.append("--build-mode")
    if args.debug is None:
        missing.append("--debug/--no-debug")
    if args.optimize is None:
        missing.append("--optimize/--no-optimize")
    if args.jobs is None:
        missing.append("--jobs")
    if args.run_after_build is None:
        missing.append("--run-after-build/--no-run-after-build")
    if missing:
        raise ValueError(
            "non-interactive mode requires: " + ", ".join(missing)
        )

    config = BuildConfig(
        version=CONFIG_VERSION,
        platform=args.platform,
        releaseType=args.release_type,
        buildMode=args.build_mode,
        flags=BuildFlags(
            debug=args.debug,
            optimize=args.optimize,
            jobs=args.jobs,
            runAfterBuild=args.run_after_build,
        ),
        updatedAt=now_iso(),
    )
    validate_config(config)
    return config


def build_interactive(seed: BuildConfig | None) -> BuildConfig:
    default_platform = seed.platform if seed else "macos"
    default_release = seed.releaseType if seed else "dev"
    default_mode = seed.buildMode if seed else "full"
    default_debug = seed.flags.debug if seed else True
    default_optimize = seed.flags.optimize if seed else False
    default_jobs = seed.flags.jobs if seed else "auto"
    default_run_after = seed.flags.runAfterBuild if seed else False

    platform = prompt_choice("Select platform", list(PLATFORMS), default_platform)
    release_type = prompt_choice("Select release type", list(RELEASE_TYPES), default_release)
    mode = prompt_choice("Select build mode", list(BUILD_MODES), default_mode)
    debug = prompt_bool("Enable debug?", default_debug)
    optimize = prompt_bool("Enable optimize?", default_optimize)
    jobs = prompt_jobs(default_jobs)
    run_after = prompt_bool("Run after build?", default_run_after)

    config = BuildConfig(
        version=CONFIG_VERSION,
        platform=platform,
        releaseType=release_type,
        buildMode=mode,
        flags=BuildFlags(
            debug=debug,
            optimize=optimize,
            jobs=jobs,
            runAfterBuild=run_after,
        ),
        updatedAt=now_iso(),
    )
    validate_config(config)
    print("\nBuild summary:")
    print(json.dumps(config.to_dict(), indent=2))
    if not prompt_bool("Proceed?", True):
        raise KeyboardInterrupt("build cancelled by user")
    return config


def create_temp_mozconfig(base_mozconfig: Path, config: BuildConfig) -> Path:
    lines = [
        f". {base_mozconfig}",
        "",
        "# Generated by build.py",
        f"# releaseType: {config.releaseType}",
        f"# buildMode: {config.buildMode}",
    ]
    if config.buildMode == "artifact":
        lines.append("ac_add_options --enable-artifact-builds")
    if config.flags.debug:
        lines.append("ac_add_options --enable-debug")
    else:
        lines.append("ac_add_options --disable-debug")
    if config.flags.optimize:
        lines.append("ac_add_options --enable-optimize")
    else:
        lines.append("ac_add_options --disable-optimize")
    if config.flags.jobs != "auto":
        lines.append(f"mk_add_options MOZ_PARALLEL_BUILD={config.flags.jobs}")
    lines.append("")

    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=ROOT, prefix=".build-mozconfig-", delete=False
    ) as tf:
        tf.write("\n".join(lines))
        return Path(tf.name)


def resolve_commands(config: BuildConfig) -> tuple[dict[str, str], list[list[str]], Path]:
    base = ROOT / PLATFORMS[config.platform]
    if not base.exists():
        raise FileNotFoundError(f"missing base mozconfig: {base}")
    generated = create_temp_mozconfig(base, config)
    env = os.environ.copy()
    env["MOZCONFIG"] = str(generated)
    commands = [["./mach", "build"]]
    if config.flags.runAfterBuild:
        commands.append(["./mach", "run"])
    return env, commands, generated


def print_last_config(config: BuildConfig | None) -> int:
    if config is None:
        print("No saved config found.")
        return 1
    print(json.dumps(config.to_dict(), indent=2))
    return 0


def main() -> int:
    args = parse_args()

    if args.reset_last:
        if LAST_CONFIG_PATH.exists():
            LAST_CONFIG_PATH.unlink()
            print(f"Deleted {LAST_CONFIG_PATH.name}")
        else:
            print("No saved config to delete.")
        return 0

    last = read_last_config()
    if args.show_last:
        return print_last_config(last)

    try:
        if args.last:
            if last is None:
                print("No saved config. Run interactive first.", file=sys.stderr)
                return 2
            config = last
            config.updatedAt = now_iso()
            validate_config(config)
        elif args.non_interactive:
            config = build_from_args(args)
        else:
            config = build_interactive(last)
    except (ValueError, KeyboardInterrupt) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    atomic_write_json(LAST_CONFIG_PATH, config.to_dict())
    env, commands, generated_mozconfig = resolve_commands(config)

    if args.print_command:
        print(f"MOZCONFIG={generated_mozconfig}")
        for cmd in commands:
            print(" ".join(cmd))
        generated_mozconfig.unlink(missing_ok=True)
        return 0

    try:
        for cmd in commands:
            completed = subprocess.run(cmd, cwd=ROOT, env=env, check=False)
            if completed.returncode != 0:
                return completed.returncode
    finally:
        generated_mozconfig.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
