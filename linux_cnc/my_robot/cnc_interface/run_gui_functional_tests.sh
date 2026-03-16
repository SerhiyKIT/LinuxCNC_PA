#!/bin/bash

# 1. Налаштування абсолютних шляхів
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_ROOT"

# 2. Експорт змінних оточення
# Додаємо корінь та папку logic
export PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/logic:$PYTHONPATH"
# Додаємо шлях до локально встановлених пакетів (~/.local), де лежить pytest-qt
export PYTHONPATH="$PYTHONPATH:$HOME/.local/lib/python3.12/site-packages"

# Вказуємо версію API для pytest-qt
export PYTEST_QT_API=pyqt5

# Опціонально: якщо ви хочете запускати GUI тести у "фоні" (без відкриття вікон на екрані),
# розкоментуйте наступний рядок. Але для налагодження краще бачити вікна.
# export QT_QPA_PLATFORM=offscreen

echo "=========================================================="
echo "🚀 ЗАПУСК ГРАФІЧНИХ ТЕСТІВ (GUI)"
echo "📂 Корінь проекту: $PROJECT_ROOT"
echo "🐍 Python: $(python3 --version)"
echo "=========================================================="

# 3. Визначаємо ціль запуску
# За замовчуванням шукаємо в tests/gui_functional
TARGET_DIR="tests/gui_functional"
TARGET=${1:-$TARGET_DIR}

if [ ! -d "$TARGET" ] && [ ! -f "$TARGET" ]; then
    echo "❌ ПОМИЛКА: Ціль '$TARGET' не знайдена."
    exit 1
fi

echo "🎯 Ціль: $TARGET"

# 4. Запуск pytest
# Використовуємо системний python3 -m pytest для стабільності
python3 -m pytest "$TARGET" -v -s --tb=short

# 5. Перевірка статусу виходу
RESULT=$?
echo -e "\n----------------------------------------------------------"
if [ $RESULT -eq 0 ]; then
    echo "✅ Всі GUI тести пройшли успішно!"
    exit 0
else
    echo "❌ Деякі GUI тести провалено."
    exit 1
fi
echo "----------------------------------------------------------"