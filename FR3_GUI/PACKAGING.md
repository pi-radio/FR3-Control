# Packaging FR3 Board Control for Distribution

This describes how to build a standalone executable for Windows, Linux, and
macOS that end users can run without installing Python or any dependencies.

## How it works

We use [PyInstaller](https://pyinstaller.org/) with the spec file
`fr3_gui.spec` in this directory. PyInstaller **does not cross-compile** -
a build only runs on the OS it was built on, so a Windows build must
actually run on Windows, a Linux build on Linux, and a macOS build on
macOS. The spec produces a one-directory build on every platform (a folder
you zip up and share), and additionally wraps it as a proper `.app` bundle
on macOS.

Because of the "must build on the target OS" requirement, this repo
includes a GitHub Actions workflow (`.github/workflows/build.yml`) that
builds all three platforms automatically in the cloud every time you push -
that's the recommended way to produce all three, rather than needing a
Windows, a Linux, and a Mac machine yourself.

## Before your first build: two things needed fixing (already done)

Two files used to compute their storage location from `__file__` (i.e.
"next to the source code") - `local_settings.py` and `logging_setup.py`.
That breaks once packaged: a one-file build's `__file__` resolves inside a
fresh temp directory that's wiped after every run, and even a one-directory
install may sit somewhere the current user can't write to. Both now use
`fr3_gui/paths.py`, which asks the `platformdirs` library for the correct
persistent, per-user, always-writable location instead (`%LOCALAPPDATA%` on
Windows, `~/Library/Application Support` on macOS, `~/.local/share` on
Linux). No further action needed here - just don't reintroduce a
`__file__`-relative path for anything the app writes to.

## Building locally (whichever OS you're on right now)

```
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt -r requirements-build.txt
pyinstaller --noconfirm --clean fr3_gui.spec
```

**On Debian/Ubuntu, `python3 -m venv venv` can silently create a broken
venv** - one with `python`/`python3` under `venv/bin/` but no `activate`
and no `pip`, if the system's venv support isn't installed (Debian splits
this out from the base Python package). Fix: `sudo apt install
python3.10-venv` (match the version to your `python3 --version`), delete
the broken `venv/` folder, and recreate it.

Output:
- **Windows:** `dist/FR3 Board Control/FR3 Board Control.exe` (zip the whole
  `FR3 Board Control` folder to share it - the `.exe` alone is not enough,
  it needs the `_internal` folder next to it).
- **Linux:** `dist/FR3 Board Control/FR3 Board Control` (same - zip the
  whole folder).
- **macOS:** `dist/FR3 Board Control.app` (a proper double-clickable app
  bundle - zip it, or use `ditto -c -k` to make a distributable `.zip` that
  preserves the bundle structure correctly).

## Building all three platforms via GitHub Actions

Once this project is pushed to a GitHub repo (`.github/workflows/build.yml`
is already included), every push to `main`, every pull request, and every
push of a `v*` tag (e.g. `v1.0.0`) automatically:
1. Runs the test suite headlessly on Linux.
2. Builds the packaged app on Windows, Linux, and macOS in parallel.
3. Uploads each as a downloadable zip under that workflow run's
   **Artifacts** section (Actions tab -> the run -> Artifacts, near the
   bottom of the run's summary page).

You can also trigger it manually with no code change: go to the **Actions**
tab -> **Build** workflow -> **Run workflow**.

**If this repo is (or becomes) private:** the Artifacts described above are
only downloadable by people who already have access to this repo - GitHub
doesn't offer a way to make just the Actions artifacts or Releases of a
private repo public. To share the executables publicly while keeping the
source private, download the three zips from the Actions run (Actions tab
-> the run -> Artifacts) and copy them over yourself to wherever you're
distributing them publicly (e.g. a separate public repo's Releases) -
that hand-off is a manual step, not automated by this workflow.

## Platform-specific notes

### Windows
Works as built, no extra steps. If antivirus software flags the `.exe`
(more common with PyInstaller **one-file** builds than the one-directory
build used here, but still possible), that's a false positive common to
PyInstaller apps in general - code-signing the executable (a paid
certificate) is the real fix if this becomes a recurring problem for your
users.

### Linux (different distributions, and CPU architectures)
CI builds **two separate Linux binaries** - `FR3-Board-Control-Linux-x86_64`
(on `ubuntu-22.04`) and `FR3-Board-Control-Linux-arm64` (on
`ubuntu-22.04-arm`, e.g. for Jetson-class ARM boards). These are not
interchangeable - give a user the one matching their machine's CPU, not
just its OS. The arm64 job is new and its GitHub-hosted runner
availability hasn't been exercised yet in this workflow - if it fails to
even start, GitHub may not offer that runner label for this account/repo
yet, worth checking the Actions run directly.

The build is done on Ubuntu 22.04 in CI specifically because **a binary
linked against a newer glibc than the end user has installed will refuse
to run at all**, while an older-glibc binary runs fine on newer distros
too. Ubuntu 22.04 is the oldest Ubuntu GitHub still offers a hosted runner
for; if you need to support distros meaningfully older than that (e.g.
Debian 10, CentOS 7, old Fedora), the next step is building inside a
[manylinux](https://github.com/pypa/manylinux) Docker container instead
(`quay.io/pypa/manylinux2014_x86_64`, glibc 2.17, runs on nearly anything
from the last ~10 years) - ask if you want this added to the workflow.

Some minimal Linux installs are missing a system library Qt6 needs at
runtime (most commonly `libxcb-cursor0`). If a user reports the app
won't start with an error mentioning `xcb` or a missing `.so`, the fix is
one line for them to run once, e.g. on Ubuntu/Debian:
`sudo apt install libxcb-cursor0`, or on Fedora: `sudo dnf install
xcb-util-cursor`. This can't be bundled into the app itself.

**"Permission denied" opening `/dev/ttyACM0`** (or any `/dev/ttyACM*`) the
first time a board is plugged in - normal on a fresh Linux install, not a
bug. Serial devices are owned by the `dialout` group by default, and a
user account isn't in it until added:
```
sudo usermod -a -G dialout $USER
```
then either log out and back in, or run `newgrp dialout` in the current
terminal to pick it up immediately without a full logout. This is a
one-time-per-machine setup step, same category as the `libxcb-cursor0`
fix above - can't be bundled into the app either.

For a nicer double-click experience than "unzip and run a binary" (no
terminal needed, works across distros with even less fuss), consider
wrapping this same build as an [AppImage](https://appimage.org/) later -
it's an additional packaging step on top of the PyInstaller output, not a
replacement for it.

### macOS
The `.app` this produces is **unsigned and not notarized**. On a Mac that
downloaded it from the internet (browser, email, Slack, etc.), Gatekeeper
will refuse to open it with an "Apple could not verify" message.
Recipients need to either right-click -> Open (and confirm) the first
time, or you can tell them to run once in Terminal:
`xattr -cr "/path/to/FR3 Board Control.app"`. Proper code signing
requires an active Apple Developer Program membership ($99/year) and is
worth doing once this tool has real external users - ask if/when you want
that set up.

## Bumping the version / adding an icon

- The GUI's version number lives in one place, `fr3_gui/version.py` - the
  window title and the macOS bundle's `CFBundleShortVersionString` (in
  `fr3_gui.spec`) both read from it automatically, so bumping it there is
  enough. Keep it matching the firmware's own `FIRMWARE_VERSION`
  (`board_config.h` in the firmware repo) whenever either changes.
- The app icon (the Pi-Radio logo) is set in two independent places, both
  generated from the same source image
  (`fr3_gui/resources/icon.png`, 1600x1600 RGBA):
  - **The running window/taskbar icon** - set at runtime in `main.py` via
    `app.setWindowIcon(...)`, reading `fr3_gui/resources/icon.png`
    directly. This works identically whether run from source or packaged
    (it's bundled as a data file - see `datas` in `fr3_gui.spec`), and
    updating it is as simple as replacing that one PNG.
  - **The packaged executable's own file icon** - `app.ico` (Windows) and
    `app.icns` (macOS) at the project root, next to `fr3_gui.spec`, picked
    up automatically by PyInstaller if present. These are a different
    format from the runtime PNG (a `.ico`/`.icns` bundles several
    resolutions in one file) and won't update just by replacing the PNG -
    regenerate both from a new source image with Pillow:
    ```python
    from PIL import Image
    img = Image.open("new_logo.png").convert("RGBA")
    img.save("app.ico", format="ICO", sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    img.save("app.icns", format="ICNS")
    ```
  Linux has no single standard for this at the packaging-format level; an
  icon matters there only if you later add a `.desktop` file or AppImage.
