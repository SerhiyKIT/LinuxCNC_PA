#!/bin/bash

# 1. Налаштування абсолютних шляхів
# Визначаємо директорію, де лежить скрипт (корінь проекту)
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$PROJECT_ROOT"

# 2. Експорт змінних оточення
# Додаємо корінь та папку logic, щоб Python бачив усі менеджери та core
export PYTHONPATH="$PROJECT_ROOT:$PROJECT_ROOT/logic"
# Offscreen режим для Qt (щоб тести не намагалися відкрити вікна)
export QT_QPA_PLATFORM=offscreen
# Вимикаємо створення __pycache__ під час тестів (опціонально, для чистоти)
export PYTHONDONTWRITEBYTECODE=1

echo "=========================================================="
echo "🚀 Запуск всіх тестів LinuxCNC Interface"
echo "📂 Корінь проекту: $PROJECT_ROOT"
echo "🐍 PYTHONPATH: $PYTHONPATH"
echo "=========================================================="

# 3. Визначаємо ціль запуску
# Якщо ти передаєш аргумент (наприклад, ./run.sh logic/tests/test_logger.py), 
# то запуститься він. Якщо ні — запустяться всі тести в logic/tests/
TARGET=${1:-"tests/unit"}

echo "🎯 Ціль: $TARGET"

# Запуск pytest з ціллю
python3 -m pytest "$TARGET" -v -s --tb=short

# 4. Перевірка статусу виходу
if [ $? -eq 0 ]; then
    echo -e "\n✅ Всі тести пройшли успішно!"
else
    echo -e "\n❌ Деякі тести провалено. Перегляньте звіт вище."
    exit 1
fi