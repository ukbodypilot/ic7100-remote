#!/usr/bin/env bash
# ic7100ctl installer — Linux only.
# Installs the Python package, udev rule, and optional systemd user unit.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Installing ic7100ctl (user-local)"
pip install --user --upgrade "$HERE"

echo "==> Installing udev rule for /dev/ic7100 symlink"
sudo cp "$HERE/udev/99-ic7100.rules" /etc/udev/rules.d/
sudo udevadm control --reload
sudo udevadm trigger

echo "==> Installing systemd user unit (optional — enable with 'systemctl --user enable --now ic7100ctl')"
mkdir -p "$HOME/.config/systemd/user"
cp "$HERE/systemd/ic7100ctl.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload

cat <<EOF

Done. Next steps:
  1. Plug in the IC-7100 USB cable. Verify /dev/ic7100 exists.
  2. Test: ic7100ctl info
  3. Run: ic7100ctl serve
  4. Or enable the service: systemctl --user enable --now ic7100ctl
  5. Browse: http://localhost:8080/
EOF
