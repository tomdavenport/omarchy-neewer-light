#!/bin/bash
# Remove only this utility; retain preferences and local logs.
set -euo pipefail
systemctl --user disable --now neewer-light.service 2>/dev/null || true
rm -f -- "$HOME/.config/systemd/user/neewer-light.service" \
  "$HOME/.config/omarchy/hooks/theme-set.d/50-neewer-light" \
  "$HOME/.local/bin/neewer-light"
systemctl --user daemon-reload
rm -rf -- "$HOME/.local/share/neewer-omarchy"
printf '%s\n' 'Light helper removed. Your light preferences and logs were kept.' \
  'Now remove the widget: omarchy plugin remove io.github.tomdavenport.neewer'
