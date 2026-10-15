# Налаштування Wi-Fi через Bluetooth

Raspberry Pi постійно транслює BLE-пристрій **CNC-Setup**. З телефона можна
підключитись до нього, ввести PIN і налаштувати Wi-Fi текстовими командами.
Потім підключатись до верстата через VNC або SSH за IP-адресою, яку покаже `status`.

## Встановлення

На Raspberry Pi:

    sudo bash ~/linuxcnc/configs/LinuxCNC_PA/system/bt-wifi-setup/install.sh

Або на ПК, вставивши картку пам'яті:

    sudo bash install.sh --root /media/$USER/rootfs --boot /media/$USER/bootfs

Інсталятор створить `bt-wifi-setup.txt` на розділі bootfs із випадковим PIN і
виведе його на екран. Назву і PIN можна змінити в цьому файлі з будь-якого ПК.

## Використання з телефона

* Android: **Serial Bluetooth Terminal**, вкладка Devices, далі Bluetooth LE.
* iPhone: **Bluefruit Connect**, режим UART (або **nRF Toolbox**, режим UART).

Підключіться до `CNC-Setup` і введіть:

    pin 123456
    scan
    wifi "Назва мережі" "пароль"
    status

Якщо в назві або паролі є лапки чи особливі символи, використовуйте дві окремі команди:

    ssid Назва мережі
    pass пароль

Мережу можна зберегти заздалегідь, навіть коли вона поза зоною досяжності.
Pi підключиться до неї автоматично, щойно мережа з'явиться.

| Команда | Дія |
|---|---|
| `status` | стан, IP, адреси VNC і SSH |
| `scan` | список мереж поблизу |
| `saved` | збережені мережі |
| `forget Назва` | видалити мережу |
| `open` | підключитись до відкритої мережі (після `ssid`) |

## Діагностика

    systemctl status bt-wifi-setup
    journalctl -u bt-wifi-setup -f
