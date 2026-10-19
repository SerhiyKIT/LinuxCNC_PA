#!/bin/bash
# Встановлення Bluetooth-конфігуратора Wi-Fi.
#
# На самому Raspberry Pi:
#   sudo bash ~/linuxcnc/configs/LinuxCNC_PA/system/bt-wifi-setup/install.sh
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

install -D -m 755 "$SRC/bt_wifi_setup.py" "$ROOT/usr/local/lib/bt-wifi-setup/bt_wifi_setup.py"
install -m 644 "$SRC/bt-wifi-setup.service" "$ROOT/etc/systemd/system/bt-wifi-setup.service"

CONF="$BOOT/bt-wifi-setup.txt"
if [ -f "$CONF" ]; then
    echo "Конфіг $CONF вже існує — залишаю без змін"
else
    PIN=$(printf '%06d' $(( $(od -An -N4 -tu4 /dev/urandom) % 1000000 )))
    sed "s/__PIN__/$PIN/" "$SRC/bt-wifi-setup.txt" > "$CONF"
    echo "Створено $CONF, PIN: $PIN"
fi

# autohotspot і wayvnc видалені, але лишились зламані посилання автозапуску
for UNIT in autohotspot.service wayvnc.service; do
    LINK="$ROOT/etc/systemd/system/multi-user.target.wants/$UNIT"
    # readlink: посилання абсолютне, тому перевіряємо ціль всередині $ROOT
    if [ -L "$LINK" ] && [ ! -e "$ROOT$(readlink "$LINK")" ]; then
        rm -f "$LINK"
        echo "Видалено зламане посилання $UNIT"
    fi
done

if [ -n "$ROOT" ]; then
    systemctl --root="$ROOT" enable bt-wifi-setup.service
else
    systemctl daemon-reload
    systemctl enable --now bt-wifi-setup.service
    systemctl --no-pager status bt-wifi-setup.service | head -n 12 || true
fi
# Скинути дані на картку: якщо її вийняти одразу, файли можуть лишитися порожніми
sync
echo "Готово."
