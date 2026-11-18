#!/usr/bin/env bash
# Build an installable .deb from this checkout (Debian/Ubuntu).
# Usage: ./scripts/build_deb.sh          # output goes to dist/
#        OUTPUT_DIR=/tmp ./scripts/build_deb.sh
set -euo pipefail

NAME="linmon"
ARCH="$(dpkg --print-architecture)"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$SOURCE_DIR/pyproject.toml" | head -1)"
OUTPUT_DIR="${OUTPUT_DIR:-$SOURCE_DIR/dist}"
PYTHON="${PYTHON:-python3}"

if [[ -z "$VERSION" ]]; then
    echo "Could not read the version from pyproject.toml" >&2
    exit 1
fi
if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "dpkg-deb is required: sudo apt install dpkg-dev" >&2
    exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
PKG_DIR="$WORK_DIR/${NAME}_${VERSION}_${ARCH}"
mkdir -p "$PKG_DIR/DEBIAN" \
         "$PKG_DIR/usr/bin" \
         "$PKG_DIR/usr/lib/linmon/vendor" \
         "$PKG_DIR/usr/share/doc/linmon" \
         "$OUTPUT_DIR"

echo "Installing linmon and its dependencies into the package payload..."
"$PYTHON" -m pip install --quiet --no-compile --upgrade \
    --target "$PKG_DIR/usr/lib/linmon/vendor" "$SOURCE_DIR"

cat > "$PKG_DIR/usr/bin/linmon" <<'LAUNCHER'
#!/bin/sh
# Launcher for the Debian-packaged linmon.
PYTHONPATH="/usr/lib/linmon/vendor${PYTHONPATH:+:$PYTHONPATH}" \
    exec /usr/bin/python3 -m linmon "$@"
LAUNCHER
chmod 0755 "$PKG_DIR/usr/bin/linmon"

cat > "$PKG_DIR/DEBIAN/control" <<CONTROL
Package: $NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.10)
Maintainer: linmon contributors <linmon@example.com>
Description: command-line system monitor for Linux
 linmon shows CPU, RAM, disk, network and uptime snapshots, a live dashboard,
 top-process tables, CSV/JSON logging and configurable CPU/RAM alerts.
CONTROL
chmod 0644 "$PKG_DIR/DEBIAN/control"

cp "$SOURCE_DIR/LICENSE" "$PKG_DIR/usr/share/doc/linmon/copyright"
cp "$SOURCE_DIR/README.md" "$PKG_DIR/usr/share/doc/linmon/README.md"

DEB_FILE="$OUTPUT_DIR/${NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$PKG_DIR" "$DEB_FILE" >/dev/null
echo "Built $DEB_FILE"
echo "Install with: sudo apt install $DEB_FILE"
