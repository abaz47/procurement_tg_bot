"""Telegram бот для отправки заявок на закупку."""

from configparser import ConfigParser
from datetime import datetime
from enum import Enum, auto
from logging import INFO, basicConfig as logger_config, getLogger
from os import getenv
from sys import exit as sys_exit
from typing import Optional, Set

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters
)

from messages import (
    COMMAND_MESSAGES,
    DEPARTMENTS,
    ERROR_MESSAGES,
    GENERAL_MESSAGES,
    INFO_MESSAGES,
    ORDER_TEMPLATE,
    PRIORITIES,
    WARNING_MESSAGES,
)

logger_config(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=INFO
)
logger = getLogger(__name__)


class OrderState(Enum):
    """Состояния диалога создания заявки."""
    SELECTING_DEPARTMENT = auto()
    ENTERING_PRODUCT = auto()
    ENTERING_QUANTITY = auto()
    SELECTING_PRIORITY = auto()


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
                            WARNING_MESSAGES['invalid_admin_id'].format(
                                key=key
                            )
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
                            WARNING_MESSAGES['invalid_user_id'].format(key=key)
                        )
            self.admins = admins
            self.allowed_users = allowed_users | admins
            logger.info(
                INFO_MESSAGES['users_loaded'].format(
                    admins_count=len(admins),
                    users_count=len(allowed_users)
                )
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
        order_handler = ConversationHandler(
            entry_points=[CommandHandler("order", self.order)],
            states={
                OrderState.SELECTING_DEPARTMENT: [
                    CallbackQueryHandler(
                        self.department_callback,
                        pattern="^department_"
                    )
                ],
                OrderState.ENTERING_PRODUCT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.product_callback
                    )
                ],
                OrderState.ENTERING_QUANTITY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.quantity_callback
                    )
                ],
                OrderState.SELECTING_PRIORITY: [
                    CallbackQueryHandler(
                        self.priority_callback,
                        pattern="^priority_"
                    )
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_order),
                CommandHandler("order", self.order_in_progress),
                CommandHandler("help", self.help_command)
            ]
        )
        self.application.add_handler(
            CommandHandler("start", self.start)
        )
        self.application.add_handler(
            CommandHandler("help", self.help_command)
        )
        self.application.add_handler(
            CommandHandler("reload_users", self.reload_users)
        )
        self.application.add_handler(order_handler)
        self.application.add_handler(
            CommandHandler("cancel", self.cancel_not_available)
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

    async def order(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> OrderState:
        """Обработчик команды /order."""
        user_id = update.effective_user.id
        if not self.user_manager.is_allowed(user_id):
            await update.message.reply_text(
                GENERAL_MESSAGES['access_denied']
            )
            return ConversationHandler.END
        keyboard = []
        for dept_id, dept_name in DEPARTMENTS.items():
            keyboard.append([
                InlineKeyboardButton(
                    dept_name,
                    callback_data=f"department_{dept_id}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            COMMAND_MESSAGES['order']['select_department'],
            reply_markup=reply_markup
        )
        return OrderState.SELECTING_DEPARTMENT

    async def department_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> OrderState:
        """Обработчик выбора отдела."""
        query = update.callback_query
        await query.answer()

        if not self.user_manager.is_allowed(query.from_user.id):
            await query.edit_message_text(
                GENERAL_MESSAGES['access_denied']
            )
            return ConversationHandler.END
        dept_id = query.data.split('_')[1]
        dept_name = DEPARTMENTS[dept_id]
        context.user_data['department'] = {
            'id': dept_id,
            'name': dept_name
        }
        await query.edit_message_text(
            f"Выбран отдел: {dept_name}\n\n"
            f"{COMMAND_MESSAGES['order']['enter_product']}"
        )
        return OrderState.ENTERING_PRODUCT

    async def product_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> OrderState:
        """Обработчик ввода информации о товаре."""
        product_info = update.message.text
        context.user_data['product'] = product_info
        await update.message.reply_text(
            COMMAND_MESSAGES['order']['enter_quantity']
        )
        return OrderState.ENTERING_QUANTITY

    async def quantity_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> OrderState:
        """Обработчик ввода количества товара."""
        quantity = update.message.text
        context.user_data['quantity'] = quantity
        keyboard = []
        for priority_id, priority_text in PRIORITIES.items():
            keyboard.append([
                InlineKeyboardButton(
                    priority_text,
                    callback_data=f"priority_{priority_id}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            COMMAND_MESSAGES['order']['select_priority'],
            reply_markup=reply_markup
        )
        return OrderState.SELECTING_PRIORITY

    async def priority_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> OrderState:
        """Обработчик выбора приоритета."""
        query = update.callback_query
        await query.answer()
        priority_id = query.data.split('_')[1]
        priority_text = PRIORITIES[priority_id]
        context.user_data['priority'] = {
            'id': priority_id,
            'text': priority_text
        }
        # Собираем данные заявки
        user = query.from_user
        dept_name = context.user_data['department']['name']
        product_info = context.user_data['product']
        quantity = context.user_data['quantity']
        current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
        # Формируем сообщение для пользователя
        user_message = (
            f"{INFO_MESSAGES['order_sent_successfully']}\n\n"
            f"Отдел: {dept_name}\n"
            f"Товар: {product_info}\n"
            f"Количество: {quantity}\n"
            f"Приоритет: {priority_text}"
        )
        # Формируем сообщение для администраторов
        order_message = ORDER_TEMPLATE.format(
            user_name=user.full_name,
            username=user.username or "не указан",
            department=dept_name,
            product=product_info,
            quantity=quantity,
            priority=priority_text,
            date=current_date
        )
        # Отправляем заявку администраторам
        await self._send_order_to_admins(order_message)
        await query.edit_message_text(user_message)
        return ConversationHandler.END

    async def _send_order_to_admins(self, message: str) -> None:
        """Отправляет заявку всем администраторам."""
        for admin_id in self.user_manager.admins:
            try:
                await self.application.bot.send_message(
                    chat_id=admin_id,
                    text=message,
                    parse_mode='HTML'
                )
            except Exception as e:
                logger.error(
                    ERROR_MESSAGES['order_send_error'].format(
                        admin_id=admin_id,
                        error=e
                    )
                )

    async def cancel_order(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> OrderState:
        """Отмена создания заявки."""
        await update.message.reply_text(
            COMMAND_MESSAGES['order']['cancel']
        )
        return ConversationHandler.END

    async def order_in_progress(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /order во время создания заявки."""
        await update.message.reply_text(
            COMMAND_MESSAGES['order']['already_in_progress']
        )
        # Возвращаем None, чтобы остаться в текущем состоянии
        return None

    async def cancel_not_available(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /cancel вне создания заявки."""
        await update.message.reply_text(
            GENERAL_MESSAGES['cancel_not_available']
        )

    async def run_async(self) -> None:
        """Асинхронный запуск бота."""
        async with self.application:
            await self.application.start()
            await self.application.updater.start_polling()
            logger.info("Бот запущен. Нажмите Ctrl+C для остановки.")
            await self.application.updater.idle()

    def run(self) -> None:
        """Запускает бота."""
        import asyncio
        asyncio.run(self.run_async())


def main() -> None:
    """Запуск бота."""
    load_dotenv()
    token = getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error(ERROR_MESSAGES['no_token'])
        sys_exit(1)
    try:
        bot = Bot(token)
        bot.run()
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"{ERROR_MESSAGES['bot_start_error'].format(error=e)}")
        sys_exit(1)


if __name__ == '__main__':
    main()
