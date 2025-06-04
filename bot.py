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
    CONFIRMING_ORDER = auto()


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
                            WARNING_MESSAGES['invalid_user_id'].format(
                                key=key
                            )
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
            logger.error(
                f"{ERROR_MESSAGES['config_error'].format(error=e)}"
            )
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

    def get_admin_ids(self) -> Set[int]:
        """Возвращает множество ID администраторов."""
        return self.admins.copy()


class Bot:
    """Класс бота."""

    def __init__(self, token: str):
        self.user_manager = UserManager()
        logger.info("Создание Application...")
        # Увеличенные таймауты для нестабильной сети
        self.application = (
            Application.builder()
            .token(token)
            .connect_timeout(30)  # Увеличено для медленного соединения
            .read_timeout(30)     # Время ожидания ответа
            .write_timeout(30)    # Время отправки данных
            .pool_timeout(30)     # Таймаут пула соединений
            .get_updates_connect_timeout(30)
            .get_updates_read_timeout(30)
            .get_updates_write_timeout(30)
            .get_updates_pool_timeout(30)
            .build()
        )
        logger.info("Настройка обработчиков...")
        self._setup_handlers()
        self._setup_error_handler()
        logger.info("Бот инициализирован")

    def _setup_handlers(self) -> None:
        """Настраивает обработчики команд."""
        order_handler = ConversationHandler(
            entry_points=[CommandHandler("order", self.order_command)],
            states={
                OrderState.SELECTING_DEPARTMENT: [
                    CallbackQueryHandler(
                        self.department_selected,
                        pattern="^dept_"
                    )
                ],
                OrderState.ENTERING_PRODUCT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.product_entered
                    )
                ],
                OrderState.ENTERING_QUANTITY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.quantity_entered
                    )
                ],
                OrderState.SELECTING_PRIORITY: [
                    CallbackQueryHandler(
                        self.priority_selected,
                        pattern="^priority_"
                    )
                ],
                OrderState.CONFIRMING_ORDER: [
                    CallbackQueryHandler(
                        self.confirm_order,
                        pattern="^confirm_"
                    )
                ]
            },
            fallbacks=[
                CommandHandler("cancel", self.cancel_command)
            ],
            per_message=False
        )
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(
            CommandHandler("reload_users", self.reload_users)
        )
        self.application.add_handler(order_handler)
        self.application.add_handler(
            CommandHandler("order", self.order_in_progress)
        )
        self.application.add_handler(
            CommandHandler("cancel", self.cancel_not_available)
        )

    async def start(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /start."""
        if not self.user_manager.is_allowed(update.effective_user.id):
            await self._send_message_with_retry(
                update.effective_chat.id,
                GENERAL_MESSAGES['access_denied']
            )
            return

        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['start']['allowed']
        )

    async def help_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /help."""
        if not self.user_manager.is_allowed(update.effective_user.id):
            await self._send_message_with_retry(
                update.effective_chat.id,
                GENERAL_MESSAGES['access_denied']
            )
            return

        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['help']['commands']
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
            logger.info(
                f"Пользователи перезагружены администратором {user_id}"
            )
            await update.message.reply_text(
                COMMAND_MESSAGES['reload_users']['success']
            )
        except Exception as e:
            logger.error(
                f"{ERROR_MESSAGES['reload_error'].format(error=e)}"
            )
            await update.message.reply_text(
                COMMAND_MESSAGES['reload_users']['error']
            )

    async def order_command(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> OrderState:
        """Обработчик команды /order."""
        if not self.user_manager.is_allowed(update.effective_user.id):
            await self._send_message_with_retry(
                update.effective_chat.id,
                GENERAL_MESSAGES['access_denied']
            )
            return ConversationHandler.END

        # Проверяем, есть ли уже активный заказ
        if context.user_data.get('order_in_progress'):
            await self._send_message_with_retry(
                update.effective_chat.id,
                COMMAND_MESSAGES['order']['already_in_progress']
            )
            return ConversationHandler.END
        # Отмечаем, что заказ начат
        context.user_data['order_in_progress'] = True
        # Создаем клавиатуру с отделами
        keyboard = []
        for dept_id, dept_name in DEPARTMENTS.items():
            keyboard.append([
                InlineKeyboardButton(
                    dept_name,
                    callback_data=f"dept_{dept_id}"
                )
            ])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['order']['select_department'],
            reply_markup=reply_markup
        )
        return OrderState.SELECTING_DEPARTMENT

    async def department_selected(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Обработчик выбора отдела."""
        query = update.callback_query
        await query.answer()
        dept_id = query.data.replace("dept_", "")
        context.user_data['department'] = dept_id
        await self._send_message_with_retry(
            query.message.chat_id,
            COMMAND_MESSAGES['order']['enter_product']
        )
        return OrderState.ENTERING_PRODUCT

    async def product_entered(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Обработчик ввода товара."""
        product = update.message.text.strip()
        context.user_data['product'] = product

        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['order']['enter_quantity']
        )
        return OrderState.ENTERING_QUANTITY

    async def quantity_entered(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Обработчик ввода количества."""
        quantity = update.message.text.strip()
        context.user_data['quantity'] = quantity

        # Создаем клавиатуру с приоритетами
        keyboard = [
            [InlineKeyboardButton(name, callback_data=f"priority_{key}")]
            for key, name in PRIORITIES.items()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['order']['select_priority'],
            reply_markup=reply_markup
        )
        return OrderState.SELECTING_PRIORITY

    async def priority_selected(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Обработчик выбора приоритета."""
        query = update.callback_query
        await query.answer()
        priority_key = query.data.replace("priority_", "")
        context.user_data['priority'] = priority_key
        order_data = context.user_data
        confirmation_text = COMMAND_MESSAGES['order']['confirmation'].format(
            department=DEPARTMENTS[order_data['department']],
            product=order_data['product'],
            quantity=order_data['quantity'],
            priority=PRIORITIES[order_data['priority']]
        )
        keyboard = [
            [
                InlineKeyboardButton(
                    "Подтвердить", callback_data="confirm_yes"
                ),
                InlineKeyboardButton(
                    "Отменить", callback_data="confirm_no"
                )
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await self._send_message_with_retry(
            query.message.chat_id,
            confirmation_text,
            reply_markup=reply_markup
        )
        return OrderState.CONFIRMING_ORDER

    async def confirm_order(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Обработчик подтверждения заказа."""
        query = update.callback_query
        await query.answer()
        if query.data == "confirm_yes":
            user = query.from_user
            order_data = context.user_data
            current_date = datetime.now().strftime("%d.%m.%Y %H:%M")
            order_message = ORDER_TEMPLATE.format(
                user_name=user.full_name,
                username=user.username or "не указан",
                department=DEPARTMENTS[order_data['department']],
                product=order_data['product'],
                quantity=order_data['quantity'],
                priority=PRIORITIES[order_data['priority']],
                date=current_date
            )
            await self._send_order_to_admins(order_message)
            await self._send_message_with_retry(
                query.message.chat_id,
                COMMAND_MESSAGES['order']['success']
            )
        else:
            await self._send_message_with_retry(
                query.message.chat_id,
                COMMAND_MESSAGES['order']['cancelled']
            )
        context.user_data.clear()
        return ConversationHandler.END

    async def cancel_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Обработчик команды /cancel."""
        if not self.user_manager.is_allowed(update.effective_user.id):
            await self._send_message_with_retry(
                update.effective_chat.id,
                GENERAL_MESSAGES['access_denied']
            )
            return ConversationHandler.END
        if not context.user_data.get('order_in_progress'):
            await self._send_message_with_retry(
                update.effective_chat.id,
                COMMAND_MESSAGES['cancel']['not_available']
            )
            return ConversationHandler.END
        context.user_data.clear()
        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['cancel']['success']
        )
        return ConversationHandler.END

    async def _send_order_to_admins(self, message: str) -> None:
        """Отправляет заявку всем администраторам."""
        admin_ids = self.user_manager.get_admin_ids()
        for admin_id in admin_ids:
            try:
                await self._send_message_with_retry(admin_id, message)
                logger.info(f"Заявка отправлена администратору {admin_id}")
            except Exception as e:
                logger.error(
                    f"Ошибка отправки заявки администратору {admin_id}: {e}"
                )

    async def order_in_progress(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /order во время создания заявки."""
        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['order']['already_in_progress']
        )

    async def cancel_not_available(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик команды /cancel вне создания заявки."""
        await self._send_message_with_retry(
            update.effective_chat.id,
            COMMAND_MESSAGES['cancel']['not_available']
        )

    def _setup_error_handler(self) -> None:
        """Настраивает обработчик ошибок."""
        self.application.add_error_handler(self.error_handler)

    async def error_handler(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Обработчик ошибок с retry механизмом."""
        from telegram.error import TimedOut, NetworkError, RetryAfter
        error = context.error
        # Обработка различных типов ошибок
        if isinstance(error, RetryAfter):
            logger.warning(f"Rate limit: ждем {error.retry_after} секунд")
            return
        if isinstance(error, (TimedOut, NetworkError)):
            logger.warning(f"Сетевая ошибка: {error}")
            return
        # Логируем неизвестные ошибки
        logger.error(f"Необработанная ошибка: {error}")
        # Пытаемся уведомить пользователя только при критических ошибках
        if (
            update
            and hasattr(update, 'effective_chat')
            and update.effective_chat
            and not isinstance(error, (TimedOut, NetworkError, RetryAfter))
        ):
            try:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=GENERAL_MESSAGES['error_occurred']
                )
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение об ошибке: {e}")

    async def _send_message_with_retry(
        self,
        chat_id: int,
        text: str,
        reply_markup=None,
        max_retries: int = 3
    ):
        """Отправляет сообщение с повторными попытками при ошибках."""
        from telegram.error import TimedOut, NetworkError, RetryAfter
        import asyncio

        for attempt in range(max_retries):
            try:
                if reply_markup:
                    return await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup
                    )
                else:
                    return await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=text
                    )
            except RetryAfter as e:
                logger.warning(f"Rate limit, ждем {e.retry_after} секунд")
                await asyncio.sleep(e.retry_after)
                continue
            except (TimedOut, NetworkError) as e:
                logger.warning(
                    f"Сетевая ошибка при отправке сообщения "
                    f"(попытка {attempt + 1}/{max_retries}): {e}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    logger.error(
                        f"Не удалось отправить сообщение "
                        f"после {max_retries} попыток"
                    )
                    raise
            except Exception as e:
                logger.error(f"Неожиданная ошибка при отправке сообщения: {e}")
                raise

    def run(self) -> None:
        """Запускает бота с оптимизированными настройками для нестабильной
        сети."""
        logger.info("Запуск бота...")
        # Настройки для нестабильной сети
        self.application.run_polling(
            drop_pending_updates=True,    # Сбрасываем старые обновления
            poll_interval=2.0,            # Увеличенный интервал polling
            timeout=30,                   # Увеличенный timeout для getUpdates
            bootstrap_retries=5           # Больше попыток подключения
        )


def main() -> None:
    """Запуск бота."""
    load_dotenv()
    token = getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error(ERROR_MESSAGES['no_token'])
        sys_exit(1)

    logger.info("Инициализация бота...")
    try:
        bot = Bot(token)
        logger.info("Запуск polling...")
        bot.run()
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"{ERROR_MESSAGES['bot_start_error'].format(error=e)}")
        sys_exit(1)


if __name__ == '__main__':
    main()
