#!/usr/bin/env python3
"""
Improved setup script (uses Python 3.10 if available)
- If Python 3.10 exists on the system, install packages using that interpreter.
- If not found, falls back to the current Python interpreter (with a clear warning).
- Cleaner, colored (optional) output, concise pip logs, safe Arduino spoofing with backups.
- CLI flags: --spoof, --no-spoof, --yes, --verbose, --dry-run
"""

from __future__ import annotations
import argparse
import subprocess
import sys
import os
import shutil
import tempfile
import time
import re
from typing import List, Tuple, Optional

# ---------------------
# Configuration
# ---------------------
REQUIRED_PACKAGES = [
    "PyQt6",
    "cryptography",
    "requests",
    "urllib3",
    "psutil",
    "torch",
    "ultralytics",
    "opencv-python",
    "numpy",
    "mss",
    # pywin32 is windows-only; pip accepts environment markers but our installed-check uses the name only
    "pywin32; platform_system=='Windows'",
    "pyserial",
    "onnxruntime",
    "pyarmor",
]

# ---------------------
# Color helpers (optional)
# ---------------------
class _Color:
    GREEN = ''
    YELLOW = ''
    RED = ''
    CYAN = ''
    RESET = ''
try:
    from termcolor import colored  # type: ignore
    _Color.GREEN = lambda s: colored(s, 'green')
    _Color.YELLOW = lambda s: colored(s, 'yellow')
    _Color.RED = lambda s: colored(s, 'red')
    _Color.CYAN = lambda s: colored(s, 'cyan')
    _Color.RESET = lambda s: s
except Exception:
    _Color.GREEN = lambda s: s
    _Color.YELLOW = lambda s: s
    _Color.RED = lambda s: s
    _Color.CYAN = lambda s: s
    _Color.RESET = lambda s: s

def log_ok(msg: str):
    print(_Color.GREEN(f"✓ {msg}"))

def log_warn(msg: str):
    print(_Color.YELLOW(f"⚠ {msg}"))

def log_err(msg: str):
    print(_Color.RED(f"✗ {msg}"))

def log_info(msg: str):
    print(_Color.CYAN(f"> {msg}"))

# ---------------------
# Subprocess helpers
# ---------------------
def run_subprocess(cmd: List[str], capture: bool = True, timeout: int = 900) -> Tuple[int, str, str]:
    """
    Run subprocess. Returns (returncode, stdout, stderr).
    """
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            text=True,
            timeout=timeout,
            check=False
        )
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        return proc.returncode, stdout, stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Process timed out after {timeout}s"

# ---------------------
# Python 3.10 discovery
# ---------------------
def find_python310_windows_paths() -> Optional[str]:
    """
    Look in common Windows install locations for python.exe that says Python 3.10 in --version.
    """
    user_home = os.path.expanduser("~")
    candidates = [
        r"C:\Python310",
        r"C:\Python\Python310",
        r"C:\Program Files\Python310",
        r"C:\Program Files (x86)\Python310",
        os.path.join(user_home, "AppData", "Local", "Programs", "Python", "Python310"),
        os.path.join(user_home, "AppData", "Local", "Programs", "Python", "Python3.10"),
    ]
    for base in candidates:
        exe = os.path.join(base, "python.exe")
        if os.path.exists(exe):
            try:
                code, out, err = run_subprocess([exe, "--version"], capture=True, timeout=5)
                combined = (out + err).strip()
                if "Python 3.10" in combined:
                    return exe
            except Exception:
                continue
    return None

def find_python310_via_py_launcher() -> Optional[str]:
    """
    On Windows, the 'py' launcher can select versions: 'py -3.10 -c "import sys;print(sys.executable)"'
    """
    try:
        code, out, err = run_subprocess(["py", "-3.10", "-c", "import sys;print(sys.executable)"], capture=True, timeout=5)
        if code == 0:
            path = out.strip()
            if path and os.path.exists(path):
                # verify version string
                c2, o2, e2 = run_subprocess([path, "--version"], capture=True, timeout=5)
                if "Python 3.10" in (o2 + e2):
                    return path
    except Exception:
        pass
    return None

def find_python310_on_path() -> Optional[str]:
    """
    Try calling 'python3.10' on PATH.
    """
    try:
        code, out, err = run_subprocess(["python3.10", "--version"], capture=True, timeout=5)
        combined = (out + err).strip()
        if code == 0 and "Python 3.10" in combined:
            # return 'python3.10' so it will be run via PATH
            return "python3.10"
    except Exception:
        pass
    return None

def find_python310() -> Optional[str]:
    """
    Try multiple strategies to locate a Python 3.10 interpreter. Return an executable path
    or a command (e.g., 'python3.10' on PATH). Return None if not found.
    """
    # 1) If current interpreter is already Python 3.10, return it
    try:
        if sys.version_info.major == 3 and sys.version_info.minor == 10:
            return sys.executable
    except Exception:
        pass

    # 2) Try Windows common paths
    if os.name == "nt":
        win_path = find_python310_windows_paths()
        if win_path:
            return win_path
        # 3) Try py launcher
        py_path = find_python310_via_py_launcher()
        if py_path:
            return py_path

    # 4) Try python3.10 on PATH (POSIX or Windows if installed to PATH)
    path_cmd = find_python310_on_path()
    if path_cmd:
        return path_cmd

    # Not found
    return None

# ---------------------
# pip helpers that use TARGET_PYTHON
# ---------------------
TARGET_PYTHON: str = sys.executable  # will be overridden in main() if 3.10 found

def pip_run(args: List[str], capture: bool = True) -> Tuple[int, str, str]:
    """
    Run TARGET_PYTHON -m <args...>
    """
    cmd = [TARGET_PYTHON, "-m"] + args
    return run_subprocess(cmd, capture=capture)

def pip_show_installed(package_name: str) -> bool:
    code, out, _ = pip_run(["pip", "show", package_name], capture=True)
    return code == 0 and bool(out.strip())

def pip_install(package_spec: str, verbose: bool = False, dry_run: bool = False) -> bool:
    """
    Install a package using TARGET_PYTHON -m pip install ...
    """
    if dry_run:
        log_info(f"[dry-run] Would install: {package_spec} (using {TARGET_PYTHON})")
        return True

    log_info(f"Installing {package_spec} using {TARGET_PYTHON} ...")
    code, out, err = pip_run(["pip", "install", package_spec], capture=True)
    if code == 0:
        log_ok(f"Installed: {package_spec}")
        if verbose and (out.strip() or err.strip()):
            if out.strip():
                print(out.strip())
            if err.strip():
                print(err.strip())
        return True
    else:
        log_err(f"Failed to install: {package_spec} (exit {code})")
        if out.strip():
            print("=== pip stdout ===")
            print(out.strip())
        if err.strip():
            print("=== pip stderr ===")
            print(err.strip())
        return False

# ---------------------
# Arduino spoofing helpers (unchanged)
# ---------------------
def find_arduino_avr_base() -> Optional[str]:
    user_home = os.path.expanduser("~")
    if os.name == "nt":
        candidates = [
            os.path.join(user_home, "AppData", "Local", "Arduino15", "packages", "arduino", "hardware", "avr")
        ]
    else:
        candidates = [
            os.path.join(user_home, ".arduino15", "packages", "arduino", "hardware", "avr"),
            os.path.join("/usr", "local", "share", "arduino", "packages", "arduino", "hardware", "avr"),
        ]
    for path in candidates:
        if os.path.isdir(path):
            return path
    # respect env override
    env = os.environ.get("ARDUINO_AVR_BASE")
    if env and os.path.isdir(env):
        return env
    return None

def backup_file(path: str) -> Optional[str]:
    try:
        backup_dir = os.path.join(tempfile.gettempdir(), "ghostsight_backups")
        os.makedirs(backup_dir, exist_ok=True)
        base = os.path.basename(path)
        backup_path = os.path.join(backup_dir, f"{base}.{int(time.time())}.bak")
        shutil.copy2(path, backup_path)
        return backup_path
    except Exception as e:
        log_warn(f"Could not create backup for {path}: {e}")
        return None

def spoof_boards_txt(path: str, make_backup: bool = True) -> Tuple[bool, str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return False, f"Cannot read {path}: {e}"

    new_content = content
    replacements_made = 0
    patterns = {
        r"(?m)^leonardo\.build\.usb_product=.*$": 'leonardo.build.usb_product="Logitech USB Receiver"',
        r"(?m)^leonardo\.build\.vid=.*$": 'leonardo.build.vid=0x046d',
        r"(?m)^leonardo\.build\.pid=.*$": 'leonardo.build.pid=0xc53f',
    }

    for pat, repl in patterns.items():
        new_content, n = re.subn(pat, repl, new_content)
        replacements_made += n

    if replacements_made == 0:
        return False, "No leonardo build entries found to replace."

    if make_backup:
        bak = backup_file(path)
        if bak:
            log_info(f"Backup created: {bak}")

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return True, f"Updated {path} ({replacements_made} replacements)."
    except Exception as e:
        return False, f"Failed to write {path}: {e}"

# ---------------------
# Package install orchestration
# ---------------------
def install_packages(packages: List[str], verbose: bool = False, dry_run: bool = False) -> Tuple[int, int]:
    success = 0
    failed = 0
    for pkg in packages:
        name_for_check = pkg.split(";")[0].strip()
        already = pip_show_installed(name_for_check)
        if already:
            log_ok(f"{name_for_check} already installed (in {TARGET_PYTHON})")
            success += 1
            continue
        ok = pip_install(pkg, verbose=verbose, dry_run=dry_run)
        if ok:
            success += 1
        else:
            failed += 1
    return success, failed

# ---------------------
# Main flow
# ---------------------
def main(argv=None):
    global TARGET_PYTHON
    parser = argparse.ArgumentParser(description="Improved setup script (use Python 3.10 if available).")
    parser.add_argument("--spoof", action="store_true", help="Attempt Arduino spoof (modifies boards.txt).")
    parser.add_argument("--no-spoof", action="store_true", help="Skip Arduino spoof step.")
    parser.add_argument("--yes", "-y", action="store_true", help="Answer yes to prompts (use carefully).")
    parser.add_argument("--verbose", action="store_true", help="Show pip logs and verbose output.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done but do not change anything.")
    args = parser.parse_args(argv)

    # 1) Discover Python 3.10
    found_py310 = find_python310()
    if found_py310 and found_py310 != sys.executable:
        TARGET_PYTHON = found_py310
        log_info(f"Using Python 3.10 interpreter for installs: {TARGET_PYTHON}")
    elif found_py310 and found_py310 == sys.executable:
        TARGET_PYTHON = sys.executable
        log_info(f"Current interpreter is Python 3.10: {TARGET_PYTHON}")
    else:
        TARGET_PYTHON = sys.executable
        log_warn("Python 3.10 not found on this system. Using current interpreter for installs.")
        log_info(f"Current interpreter: {TARGET_PYTHON} ({sys.version.split()[0]})")

    log_info(f"Platform: {os.name}, {sys.platform}")
    if args.dry_run:
        log_warn("Running in dry-run mode. No changes will be made.")

    # 2) Ensure termcolor if available (optional; installed into TARGET_PYTHON)
    try:
        import termcolor  # type: ignore
    except Exception:
        if not args.dry_run:
            log_info("Attempting to install 'termcolor' into target Python for colored output (optional).")
            pip_install("termcolor", verbose=args.verbose, dry_run=args.dry_run)

    # 3) Install required packages using TARGET_PYTHON
    log_info("Installing required packages (concise).")
    success, failed = install_packages(REQUIRED_PACKAGES, verbose=args.verbose, dry_run=args.dry_run)

    print()
    log_info("Installation summary:")
    log_ok(f"Packages installed or already present: {success}")
    if failed:
        log_err(f"Packages failed to install: {failed}")
        log_warn("If a package failed, re-run with --verbose to see pip output (or manually run pip using the chosen interpreter).")

    # 4) Arduino spoof logic (same UX as before)
    do_spoof = args.spoof and not args.no_spoof
    if args.no_spoof:
        log_info("Arduino spoof step skipped by --no-spoof.")
    elif not do_spoof:
        if args.dry_run:
            log_info("[dry-run] Would prompt for Arduino spoof.")
        elif args.yes:
            do_spoof = True
        else:
            try:
                resp = input("Do you want to attempt Arduino spoofing (safe backup will be made)? [y/N]: ").strip().lower()
                do_spoof = resp in ("y", "yes")
            except KeyboardInterrupt:
                print()
                log_warn("User cancelled input; skipping Arduino spoof.")
                do_spoof = False

    if do_spoof:
        base = find_arduino_avr_base()
        if not base:
            log_err("Could not locate Arduino AVR hardware package directory. Arduino may not be installed or path differs.")
            log_info("If you have Arduino installed in a custom place, set environment variable ARDUINO_AVR_BASE.")
        if base and os.path.isdir(base):
            log_info(f"Scanning AVR base: {base}")
            version_folders = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))]
            if not version_folders:
                log_warn("No versioned AVR folders found under base path.")
            else:
                changed_any = False
                for ver in version_folders:
                    boards_path = os.path.join(base, ver, "boards.txt")
                    if not os.path.isfile(boards_path):
                        log_warn(f"No boards.txt in {ver}; skipping.")
                        continue
                    ok, msg = spoof_boards_txt(boards_path, make_backup=not args.dry_run)
                    if ok:
                        log_ok(f"{ver}: {msg}")
                        changed_any = True
                    else:
                        log_warn(f"{ver}: {msg}")
                if changed_any:
                    log_ok("Spoofing completed on at least one AVR version.")
                else:
                    log_warn("Spoofing did not modify any files. Check messages above.")
        else:
            log_err("Skipping spoof because AVR base folder was not determined.")
    else:
        log_info("Arduino spoof not requested; skipping.")

    print()
    log_info("All done.")
    if args.dry_run:
        log_warn("Dry-run mode: no files were changed and no packages were really installed.")
    if failed:
        log_warn("Some packages failed to install. Consider re-running with --verbose or inspect pip output.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
