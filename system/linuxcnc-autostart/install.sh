#!/bin/bash
# Автозапуск LinuxCNC при старті Pi як користувацький сервіс cnc. Ідемпотентний.
# Запускати на Pi від cnc (БЕЗ sudo):
#   bash ~/linuxcnc/configs/LinuxCNC_PA/system/linuxcnc-autostart/install.sh
# Сервіс стартує разом із сесією cnc (autologin на tty1).
set -euo pipefail
[ "$(id -u)" -ne 0 ] || { echo "Запускайте від користувача cnc, без sudo"; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.config/systemd/user"
mkdir -p "$DEST"
install -m 644 "$SRC/linuxcnc.service" "$DEST/linuxcnc.service"
systemctl --user daemon-reload
systemctl --user enable linuxcnc.service

if pgrep -x milltask >/dev/null; then
    echo "LinuxCNC уже працює — сервіс підхопить його з наступного старту Pi"
else
    systemctl --user start linuxcnc.service
fi
systemctl --user --no-pager status linuxcnc.service | head -n 6 || true
echo "Готово. Вимкнути автозапуск: systemctl --user disable --now linuxcnc"
