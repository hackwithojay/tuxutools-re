#!/usr/bin/env bash
# Install the TuxuTools desktop entry for the current user.
#
# The committed .desktop file is path-agnostic (Exec=tuxutools-gui, resolved via
# $PATH).  Some desktop environments launch entries with a minimal environment
# where a virtualenv's bin/ is not on $PATH, so this script resolves the real
# executable and writes an absolute path into the installed copy.
#
# Usage:  bash packaging/install-desktop.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

gui="$(command -v tuxutools-gui || true)"
if [[ -z "$gui" && -x "$here/../.venv/bin/tuxutools-gui" ]]; then
    gui="$here/../.venv/bin/tuxutools-gui"
fi
if [[ -z "$gui" ]]; then
    echo "error: tuxutools-gui not found." >&2
    echo "Install it first, e.g.:  pip install -e '.[gui]'" >&2
    exit 1
fi

# Resolve via the script's interpreter so venv shebangs keep working.
gui="$(readlink -f "$gui")"
python="$(head -n1 "$gui" | sed 's/^#!//')"
exec_line="${python} -m tuxutools.gui.app"

apps_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$apps_dir"

sed "s|^Exec=.*|Exec=${exec_line}|; s|^TryExec=.*|TryExec=${python}|" \
    "$here/tuxutools.desktop" > "$apps_dir/tuxutools.desktop"
chmod +x "$apps_dir/tuxutools.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$apps_dir" >/dev/null 2>&1 || true
fi

echo "Installed $apps_dir/tuxutools.desktop"
echo "  Exec: $exec_line"
