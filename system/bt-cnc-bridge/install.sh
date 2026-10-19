#!/bin/bash
# Встановлення BLE-мосту керування роботом (bt-cnc-bridge). Ідемпотентний.
#
# На самому Raspberry Pi:
#   sudo bash ~/linuxcnc/configs/LinuxCNC_PA/system/bt-cnc-bridge/install.sh
# На ПК з вставленою карткою (офлайн):
#   sudo bash install.sh --root /media/$USER/rootfs --boot /media/$USER/bootfs
set -euo pipefail

ROOT=""
BOOT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --root) ROOT="${2%/}"; shift 2 ;;
        --boot) BOOT="${2%/}"; shift 2 ;;
        *) echo "Невідомий параметр: $1"; exit 1 ;;
    esac
done
[ -z "$BOOT" ] && BOOT="$ROOT/boot/firmware"
[ "$(id -u)" -eq 0 ] || { echo "Запустіть через sudo"; exit 1; }
[ -d "$ROOT/etc/systemd/system" ] || { echo "Не знайдено $ROOT/etc/systemd/system"; exit 1; }
[ -d "$BOOT" ] || { echo "Не знайдено boot-розділ $BOOT"; exit 1; }

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$ROOT/usr/local/lib/bt-cnc-bridge"

# Лише модулі мосту, без тестів
install -d -m 755 "$DEST"
for f in bt_cnc_bridge.py ble_gatt.py tcp_server.py protocol.py cnc_backend.py safety.py bridge_constants.py; do
    install -m 644 "$SRC/$f" "$DEST/$f"
done
chmod 755 "$DEST/bt_cnc_bridge.py"
install -m 644 "$SRC/bt-cnc-bridge.service" "$ROOT/etc/systemd/system/bt-cnc-bridge.service"

CONF="$BOOT/bt-cnc-bridge.txt"
if [ -f "$CONF" ]; then
    echo "Конфіг $CONF вже існує — залишаю без змін"
else
    PIN=$(printf '%06d' $(( $(od -An -N4 -tu4 /dev/urandom) % 1000000 )))
    sed "s/__PIN__/$PIN/" "$SRC/bt-cnc-bridge.txt" > "$CONF"
    echo "Створено $CONF, PIN: $PIN"
fi

if [ -n "$ROOT" ]; then
    systemctl --root="$ROOT" enable bt-cnc-bridge.service
else
    systemctl daemon-reload
    systemctl enable bt-cnc-bridge.service
    systemctl restart bt-cnc-bridge.service
    systemctl --no-pager status bt-cnc-bridge.service | head -n 12 || true
fi
# Скинути дані на картку: якщо її вийняти одразу, файли можуть лишитися порожніми
sync
echo "Готово."
