#!/bin/bash

# 1. Налаштування середовища
PROJECT_ROOT=$(pwd)
export PYTHONPATH=$PROJECT_ROOT:$PROJECT_ROOT/logic:$PYTHONPATH
export PATH=$(echo $PATH | sed -e 's/:\/snap\/bin//g')

# Визначаємо цільову директорію
TARGET_DIR="tests/integration"

echo "=========================================================="
echo "🚀 ЗАПУСК ІНТЕГРАЦІЙНИХ ТЕСТІВ (REAL CNC)"
echo "=========================================================="

# 2. Перевірка LinuxCNC
if ! pgrep -x "linuxcnc" > /dev/null
then
    echo "❌ ПОМИЛКА: LinuxCNC не запущений! Тести вимагають активного сервера."
    exit 1
fi

# 3. Визначення списку файлів для запуску
# Якщо аргумент передано, використовуємо його, інакше шукаємо всі тести в директорії
if [ -n "$1" ]; then
    if [ -f "$1" ]; then
        TEST_FILES="$1"
        echo "🎯 Цільовий тест: $1"
    elif [ -f "$TARGET_DIR/$1" ]; then
        TEST_FILES="$TARGET_DIR/$1"
        echo "🎯 Цільовий тест: $TARGET_DIR/$1"
    else
        echo "❌ ПОМИЛКА: Файл '$1' не знайдено."
        exit 1
    fi
else
    TEST_FILES=$(find "$TARGET_DIR" -name "test_*.py" | sort)
    echo "📂 Запуск усіх тестів з $TARGET_DIR..."
fi

# 4. Цикл виконання тестів
FAILED_TESTS=()

for file in $TEST_FILES; do
    echo -e "\n----------------------------------------------------------"
    echo "🏃 Виконання: $file"
    echo "----------------------------------------------------------"
    
    # Використовуємо системний python3
    /usr/bin/python3 "$file"
    
    if [ $? -ne 0 ]; then
        echo "❌ Тест $file завершився з помилкою."
        FAILED_TESTS+=("$file")
    else
        echo "✅ Тест $file пройдено успішно."
    fi
done

# 5. Підсумок
echo -e "\n=========================================================="
if [ ${#FAILED_TESTS[@]} -eq 0 ]; then
    echo "🎉 Усі тести завершені успішно!"
    exit 0
else
    echo "⚠️  ЗАВЕРШЕНО З ПОМИЛКАМИ В ТЕСТАХ:"
    for failed in "${FAILED_TESTS[@]}"; do
        echo "   - $failed"
    done
    exit 1
fi
echo "=========================================================="