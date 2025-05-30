"""Telegram бот для отправки заявок на закупку."""

from configparser import ConfigParser
from logging import INFO, basicConfig as logger_config, getLogger
from os import getenv
from typing import Optional, Set

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from messages import (
    COMMAND_MESSAGES,
    ERROR_MESSAGES,
    GENERAL_MESSAGES,
    INFO_MESSAGES,
    WARNING_MESSAGES,
)

logger_config(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=INFO
)
logger = getLogger(__name__)


class UserManager:
    """Класс для управления пользователями и их правами доступа."""

    def __init__(self):
        self.admins: Set[int] = set()
        self.allowed_users: Set[int] = set()
        self._load_users()

    def _parse_user_id(self, user_id_str: str) -> Optional[int]:
        """
        Парсит ID пользователя из строки, игнорируя комментарии.
        Возвращает None, если ID некорректный.
        """
        try:
            user_id_str = user_id_str.split('#')[0].strip()
            if not user_id_str:
                return None
            return int(user_id_str)
        except ValueError:
            return None

    def _load_users(self) -> None:
        """
        Загружает списки администраторов и пользователей из файла конфигурации.
        Администраторы автоматически добавляются в список пользователей.

        Raises:
            ValueError: Если не найден хотя бы один администратор
        """
        config = ConfigParser(allow_no_value=True)
        try:
            config.read('users.cfg', encoding='utf-8')
            admins = set()
            if 'ADMINS' in config:
                for key in config['ADMINS']:
                    user_id = self._parse_user_id(key)
                    if user_id is not None:
                        admins.add(user_id)
                    else:
                        logger.warning(
                            f"{WARNING_MESSAGES[
                                'invalid_admin_id'
                            ].format(key=key)}"
                        )
            if not admins:
                raise ValueError(ERROR_MESSAGES['no_admins'])
            allowed_users = set()
            if 'USERS' in config:
                for key in config['USERS']:
                    user_id = self._parse_user_id(key)
                    if user_id is not None:
                        allowed_users.add(user_id)
                    else:
                        logger.warning(
                            f"{WARNING_MESSAGES[
                                'invalid_user_id'
                            ].format(key=key)}"
                        )
            self.admins = admins
            self.allowed_users = allowed_users | admins
            logger.info(
                f"{INFO_MESSAGES[
                    'users_loaded'
                ].format(
                    admins_count=len(admins),
                    users_count=len(allowed_users)
                )}"
            )
        except Exception as e:
            logger.error(f"{ERROR_MESSAGES['config_error'].format(error=e)}")
            raise

    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором."""
        return user_id in self.admins

    def is_allowed(self, user_id: int) -> bool:
        """Проверяет, есть ли у пользователя доступ к боту."""
        return user_id in self.allowed_users

    def reload_users(self) -> None:
        """Перезагружает списки пользователей из файла конфигурации."""
        self._load_users()


class Bot:
    """Класс бота."""

    def __init__(self, token: str):
        self.user_manager = UserManager()
        self.application = Application.builder().token(token).build()
        self._setup_handlers()

    def _setup_handlers(self) -> None:
        """Настраивает обработчики команд."""
        self.application.add_handler(
            CommandHandler("start", self.start)
        )
        self.application.add_handler(
            CommandHandler("help", self.help_command)
        )
        self.application.add_handler(
            CommandHandler("reload_users", self.reload_users)
        )

    async def start(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /start."""
        user_id = update.effective_user.id
        if self.user_manager.is_allowed(user_id):
            await update.message.reply_text(
                COMMAND_MESSAGES['start']['allowed']
            )
        else:
            await update.message.reply_text(
                COMMAND_MESSAGES['start']['not_allowed']
            )

    async def help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /help."""
        user_id = update.effective_user.id
        if self.user_manager.is_allowed(user_id):
            await update.message.reply_text(
                COMMAND_MESSAGES['help']['commands']
            )
        else:
            await update.message.reply_text(
                GENERAL_MESSAGES['access_denied']
            )

    async def reload_users(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /reload_users."""
        user_id = update.effective_user.id
        if not self.user_manager.is_admin(user_id):
            await update.message.reply_text(
                COMMAND_MESSAGES['reload_users']['not_admin']
            )
            return
        try:
            self.user_manager.reload_users()
            await update.message.reply_text(
                COMMAND_MESSAGES['reload_users']['success']
            )
        except Exception as e:
            logger.error(f"{ERROR_MESSAGES['reload_error'].format(error=e)}")
            await update.message.reply_text(
                COMMAND_MESSAGES['reload_users']['error']
            )

    def run(self) -> None:
        """Запускает бота."""
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


def main() -> None:
    """Запуск бота."""
    load_dotenv()
    token = getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError(ERROR_MESSAGES['no_token'])
    try:
        bot = Bot(token)
        bot.run()
    except Exception as e:
        logger.error(f"{ERROR_MESSAGES['bot_start_error'].format(error=e)}")


if __name__ == '__main__':
    main()
