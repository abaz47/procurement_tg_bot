#!/bin/bash

# Скрипт для управления пользователями бота

CONFIG_FILE="users.cfg"

show_help() {
    echo "Управление пользователями Telegram бота"
    echo ""
    echo "Использование: $0 [команда] [параметры]"
    echo ""
    echo "Команды:"
    echo "  list                    - Показать всех пользователей"
    echo "  add-admin <id> [имя]    - Добавить администратора"
    echo "  add-user <id> [имя]     - Добавить пользователя"
    echo "  remove <id>             - Удалить пользователя"
    echo "  edit                    - Открыть файл в редакторе"
    echo "  reload                  - Перезагрузить конфигурацию в боте"
    echo "  backup                  - Создать резервную копию"
    echo ""
    echo "Примеры:"
    echo "  $0 add-admin 123456789 \"Иван Иванов\""
    echo "  $0 add-user 987654321 \"Петр Петров\""
    echo "  $0 remove 123456789"
}

check_config() {
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "Файл $CONFIG_FILE не найден!"
        echo "Создаю базовый файл конфигурации..."
        cat > "$CONFIG_FILE" << EOF
[ADMINS]
# ID администраторов (получают заявки)
# Формат: ID  # Комментарий

[USERS]
# ID пользователей (могут создавать заявки)
# Формат: ID  # Комментарий
EOF
        echo "Создан файл $CONFIG_FILE"
    fi
}

list_users() {
    echo "Список пользователей:"
    echo ""
    if [ -f "$CONFIG_FILE" ]; then
        echo "Администраторы:"
        grep -A 100 "^\[ADMINS\]" "$CONFIG_FILE" | grep -B 100 "^\[" | grep -v "^\[" | grep -v "^#" | grep -v "^$" | sed 's/^/  /'
        echo ""
        echo "Пользователи:"
        grep -A 100 "^\[USERS\]" "$CONFIG_FILE" | grep -v "^\[" | grep -v "^#" | grep -v "^$" | sed 's/^/  /'
    else
        echo "Файл конфигурации не найден"
    fi
}

add_admin() {
    local user_id="$1"
    local user_name="$2"
    
    if [ -z "$user_id" ]; then
        echo "Не указан ID пользователя"
        return 1
    fi
    
    check_config
    
    # Проверяем, не существует ли уже
    if grep -q "^$user_id" "$CONFIG_FILE"; then
        echo "Пользователь $user_id уже существует"
        return 1
    fi
    
    # Добавляем в секцию ADMINS
    if [ -n "$user_name" ]; then
        sed -i "/^\[ADMINS\]/a $user_id  # $user_name" "$CONFIG_FILE"
    else
        sed -i "/^\[ADMINS\]/a $user_id" "$CONFIG_FILE"
    fi
    
    echo "Администратор $user_id добавлен"
}

add_user() {
    local user_id="$1"
    local user_name="$2"
    
    if [ -z "$user_id" ]; then
        echo "Не указан ID пользователя"
        return 1
    fi
    
    check_config
    
    # Проверяем, не существует ли уже
    if grep -q "^$user_id" "$CONFIG_FILE"; then
        echo "Пользователь $user_id уже существует"
        return 1
    fi
    
    # Добавляем в секцию USERS
    if [ -n "$user_name" ]; then
        sed -i "/^\[USERS\]/a $user_id  # $user_name" "$CONFIG_FILE"
    else
        sed -i "/^\[USERS\]/a $user_id" "$CONFIG_FILE"
    fi
    
    echo "Пользователь $user_id добавлен"
}

remove_user() {
    local user_id="$1"
    
    if [ -z "$user_id" ]; then
        echo "Не указан ID пользователя"
        return 1
    fi
    
    if grep -q "^$user_id" "$CONFIG_FILE"; then
        sed -i "/^$user_id/d" "$CONFIG_FILE"
        echo "Пользователь $user_id удален"
    else
        echo "Пользователь $user_id не найден"
    fi
}

edit_config() {
    if command -v nano &> /dev/null; then
        nano "$CONFIG_FILE"
    elif command -v vim &> /dev/null; then
        vim "$CONFIG_FILE"
    elif command -v vi &> /dev/null; then
        vi "$CONFIG_FILE"
    else
        echo "Не найден текстовый редактор (nano, vim, vi)"
        return 1
    fi
}

reload_bot() {
    echo "Для перезагрузки конфигурации:"
    echo "1. Отправьте команду /reload_users администратором в Telegram"
    echo "2. Или перезапустите контейнер: docker-compose restart"
}

backup_config() {
    local backup_file="users.cfg.backup.$(date +%Y%m%d_%H%M%S)"
    cp "$CONFIG_FILE" "$backup_file"
    echo "Резервная копия создана: $backup_file"
}

# Основная логика
case "$1" in
    "list")
        list_users
        ;;
    "add-admin")
        add_admin "$2" "$3"
        ;;
    "add-user")
        add_user "$2" "$3"
        ;;
    "remove")
        remove_user "$2"
        ;;
    "edit")
        edit_config
        ;;
    "reload")
        reload_bot
        ;;
    "backup")
        backup_config
        ;;
    *)
        show_help
        ;;
esac
