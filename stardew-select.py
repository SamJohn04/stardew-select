#!/usr/bin/env python3

"""
stardew-select.py — Stardew Valley mod profile switcher.
 
Copies mod profiles from a source directory into the Stardew Valley Mods folder.
Profiles are defined in profiles.json in the same directory as this script.
 
Usage:
    python stardew-select.py --help
    python stardew-select.py --list
    python stardew-select.py kawaii
    python stardew-select.py kawaii --dry-run
"""
 
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
 
 
# ---------------------------------------------------------------------------
# Default paths — override in config.json or via environment variables
# ---------------------------------------------------------------------------
 
DEFAULT_SRC_MODS_DIR  = Path(__file__).parent / "Mods"
DEFAULT_DEST_MODS_DIR = (
    Path.home()
    / ".local" / "share" / "Steam" / "steamapps"
    / "common" / "Stardew Valley" / "Mods"
)
 
# Alternate Steam library locations to auto-detect
ALTERNATE_STEAM_PATHS = [
    Path.home() / ".steam" / "steam" / "steamapps" / "common" / "Stardew Valley" / "Mods",
    Path("/mnt") / "steamlibrary" / "steamapps" / "common" / "Stardew Valley" / "Mods",
]
 
CONFIG_PATH   = Path(__file__).parent / "config.json"
PROFILES_PATH = Path(__file__).parent / "profiles.json"

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config() -> dict:
    """
    Load config.json if it exists, applying environment variable overrides.
    Falls back to defaults if the file doesn't exist.
    """
    config = {
        "src_mods_dir":  str(DEFAULT_SRC_MODS_DIR),
        "dest_mods_dir": str(DEFAULT_DEST_MODS_DIR),
    }
 
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                config.update(json.load(f))
        except json.JSONDecodeError as e:
            fatal(f"config.json is invalid JSON: {e}")
            sys.exit(1)
 
    # Environment variables take highest priority
    if "STARDEW_SRC_DIR" in os.environ:
        config["src_mods_dir"] = os.environ["STARDEW_SRC_DIR"]
    if "STARDEW_DEST_DIR" in os.environ:
        config["dest_mods_dir"] = os.environ["STARDEW_DEST_DIR"]
 
    return config
 
 
def load_profiles() -> dict:
    """Load profiles.json, exiting clearly if it's missing or malformed."""
    if not PROFILES_PATH.exists():
        fatal(
            f"profiles.json not found at {PROFILES_PATH}\n"
            "Create one based on profiles.example.json, or run with --help."
        )
        sys.exit(1)

    try:
        with PROFILES_PATH.open() as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        fatal(f"profiles.json is invalid JSON: {e}")
        sys.exit(1)
 
 
# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
 
def resolve_dest(config: dict) -> Path:
    """
    Resolve the destination Mods folder.
    Tries config value first, then auto-detects common Steam locations.
    """
    dest = Path(config["dest_mods_dir"]).expanduser()
    if dest.exists():
        return dest
 
    for alt in ALTERNATE_STEAM_PATHS:
        if alt.exists():
            print(f"[info] Configured destination not found; using detected path:\n   {alt}\n")
            return alt
 
    fatal(
        f"Stardew Valley Mods folder not found.\n"
        f"Tried: {dest}\n"
        f"Set the correct path in config.json or via the STARDEW_DEST_DIR environment variable."
    )
    sys.exit(1)
 
 
def resolve_src(config: dict) -> Path:
    """Resolve and validate the source mods directory."""
    src = Path(config["src_mods_dir"]).expanduser()
    if not src.exists():
        fatal(
            f"Source mods directory not found: {src}\n"
            "Set the correct path in config.json or via the STARDEW_SRC_DIR environment variable."
        )
        sys.exit(1)
    return src
 
 
# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------
 
def clear_dest(dest: Path, dry_run: bool, silent: bool = True) -> None:
    """Remove all contents of the destination Mods folder."""
    if not silent:
        print("[INFO] Clearing Mods folder...")
    if dry_run:
        if not silent:
            print(f"   [dry-run] Would delete all contents of {dest}")
        return
    for item in dest.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
    if not silent:
        print("   [SUCCESSFUL] Done\n")
 
 
def copy_mod(name: str, src: Path, dest: Path, dry_run: bool) -> bool:
    """
    Copy a single mod folder from src to dest.
    Returns True on success, False if the source folder doesn't exist.
    """
    src_path  = src  / name
    dest_path = dest / name
 
    if not src_path.exists():
        print(f"   [WARN]  Skipped '{name}': not found in {src}")
        return False
 
    if dry_run:
        print(f"   [dry-run] Would copy: {name}")
        return True
 
    if dest_path.exists():
        shutil.rmtree(dest_path)
 
    shutil.copytree(src_path, dest_path)
    print(f"   [SUCCESSFUL] {name}")
    return True
 
 
def activate_profile(
    profile_id: str,
    profiles: dict,
    src: Path,
    dest: Path,
    dry_run: bool,
) -> None:
    """Clear the destination and copy all mods for the given profile."""
    profile = profiles[profile_id]
    name    = profile.get("name", f"Profile {profile_id}")
    mods    = profile.get("mods", [])
 
    print(f"{'[DRY RUN] ' if dry_run else ''}Activating profile: {name}\n")
 
    # Confirm before destructive operation (skip in dry-run)
    if not dry_run:
        answer = input("[WARN]  This will delete all current mods. Continue? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            sys.exit(0)
        print()
 
    # Safe atomic copy: copy to temp dir, then swap
    if not dry_run:
        tmp_dir = Path(tempfile.mkdtemp(dir=dest.parent, prefix=".stardew-select-tmp-"))
        try:
            _do_copy(mods, src, tmp_dir, dry_run)
            # Swap: clear dest and move contents from tmp
            clear_dest(dest, dry_run=False, silent=True)
            for item in tmp_dir.iterdir():
                shutil.move(str(item), dest / item.name)
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
    else:
        _do_copy(mods, src, dest, dry_run)
 
 
def _do_copy(mod_list: list, src: Path, dest: Path, dry_run: bool) -> None:
    """Copy a list of mods, reporting results."""
    succeeded = 0
    skipped   = 0
 
    print("\n[INFO] Copying profile mods...")
    for mod in mod_list:
        ok = copy_mod(mod, src, dest, dry_run)
        if ok:
            succeeded += 1
        else:
            skipped += 1
 
    print(f"\n{'[dry-run] ' if dry_run else ''}Done. {succeeded} copied, {skipped} skipped.")
 
 
# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
 
def list_profiles(profiles: dict) -> None:
    """Print all available profiles."""
    print("Available profiles:\n")
    for pid, profile in profiles.items():
        name  = profile.get("name", f"Profile {pid}")
        desc  = profile.get("description", "")
        mods  = profile.get("mods", [])
        print(f"  {pid}) {name}")
        if desc:
            print(f"     {desc}")
        print(f"     {len(mods)} mods")
        print()
 
 
def fatal(message: str) -> None:
    """Print an error message"""
    print(f"\n[error]: {message}\n", file=sys.stderr)
 
 
# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stardew-select.py",
        description="Stardew Valley mod profile switcher.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Environment variables:\n"
            "  STARDEW_SRC_DIR   Override source mods directory\n"
            "  STARDEW_DEST_DIR  Override Stardew Valley Mods directory\n\n"
            "Examples:\n"
            "  python stardew-select.py --list\n"
            "  python stardew-select.py kawaii\n"
            "  python stardew-select.py kawaii --dry-run\n"
            "  STARDEW_SRC_DIR=~/mymods python stardew-select.py 2\n"
        ),
    )
 
    parser.add_argument(
        "profile",
        nargs="?",
        metavar="PROFILE",
        help=f"Profile ID to activate",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all available profiles and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without making any changes.",
    )
 
    return parser
 
 
def main() -> None:
    parser   = build_parser()
    args     = parser.parse_args()

    profiles = load_profiles()
    config   = load_config()

    if args.list:
        list_profiles(profiles)
        sys.exit(0)

    if not args.profile:
        parser.print_help()
        sys.exit(0)

    src  = resolve_src(config)
    dest = resolve_dest(config)

    if args.profile == "all" and "all" not in profiles:
        # Collect every unique mod across all profiles
        all_mods = []
        for profile in profiles.values():
            for mod in profile.get("mods", []):
                if mod not in all_mods:
                    all_mods.append(mod)
        # Fake a combined profile entry
        profiles["all"] = {"name": "All Mods", "mods": all_mods}

    if args.profile not in profiles:
        fatal(f"Unknown profile '{args.profile}'. Run --list to see available profiles.")
        sys.exit(1)

    activate_profile(args.profile, profiles, src, dest, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
