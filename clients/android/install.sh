#!/bin/bash
# Встановлення мобільного веб-додатка CNC-Robot (сервіс cnc-web). Ідемпотентний.
# Додаток роздається прямо з цього каталогу репозиторію, тож git pull одразу оновлює його.
#
# На Raspberry Pi:
#   sudo bash ~/linuxcnc/configs/LinuxCNC_PA/clients/android/install.sh
# На ПК з вставленою карткою (офлайн):
#   sudo bash install.sh --root /media/$USER/rootfs
set -euo pipefail

ROOT=""
PORT=8780
while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT="${2%/}"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        *) echo "Невідомий параметр: $1"; exit 1 ;;
    esac
done
[ "$(id -u)" -eq 0 ] || { echo "Запустіть через sudo"; exit 1; }
[ -d "$ROOT/etc/systemd/system" ] || { echo "Не знайдено $ROOT/etc/systemd/system"; exit 1; }
[ -x "$ROOT/usr/bin/websockify" ] || { echo "Немає websockify: sudo apt install websockify"; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
WEB_DIR="${SRC#"$ROOT"}"                  # шлях, яким його бачитиме Pi
sed -e "s#__WEB_DIR__#$WEB_DIR#" -e "s#__PORT__#$PORT#" "$SRC/cnc-web.service" \
    > "$ROOT/etc/systemd/system/cnc-web.service"
chmod 644 "$ROOT/etc/systemd/system/cnc-web.service"
echo "Сервіс cnc-web: $WEB_DIR на порту $PORT"

if [ -n "$ROOT" ]; then
    systemctl --root="$ROOT" enable cnc-web.service
else
    systemctl daemon-reload
    systemctl enable cnc-web.service
    systemctl restart cnc-web.service
    systemctl --no-pager status cnc-web.service | head -n 8 || true
fi
# Скинути дані на картку: якщо її вийняти одразу, файли можуть лишитися порожніми
sync
echo "Готово. На телефоні: http://<IP Raspberry Pi>:$PORT/"
