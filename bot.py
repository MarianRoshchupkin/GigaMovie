import logging
import os
import uuid
import urllib3
import requests

from datetime import datetime
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from telegram.constants import ParseMode

from models import SessionLocal, User, Genre, init_db

# Отключаем предупреждения для незащищённых запросов (verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Загружаем переменные окружения из .env-файла
load_dotenv()

# --- Environment Variables ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")      # Токен Telegram-бота из .env
GIGACHAT_AUTHORIZATION_KEY = os.getenv("GIGACHAT_AUTHORIZATION_KEY")  # Ключ для авторизации в GigaChat API
GIGACHAT_CLIENT_ID = os.getenv("GIGACHAT_CLIENT_ID")      # ID клиента для GigaChat API

# Настройка логирования: формат и уровень (INFO)
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)  # Создаём логгер с именем текущего модуля


# ---------------------
#   GigaChat API
# ---------------------
class GigaChatAPI:
    """
    Класс-обёртка для работы с GigaChat API:
    1) Получение/обновление токена доступа;
    2) Генерация ответа от модели.
    """
    def __init__(self, authorization_key):
        self.authorization_key = authorization_key  # Сохраняем ключ для базовой авторизации
        self.access_token = None                    # Поле для хранения полученного access_token
        self.token_expiry = datetime.utcnow()       # Время, до которого токен действителен

    def get_access_token(self):
        """
        Получаем действительный токен:
        - Если его нет или он просрочен, запрашиваем заново.
        - Возвращаем имеющийся или новый токен.
        """
        if not self.access_token or datetime.utcnow() >= self.token_expiry:
            self.request_access_token()
        return self.access_token

    def request_access_token(self):
        """
        Запрашиваем новый токен по URL, используя Basic Auth (authorization_key).
        Сохраняем token и время его истечения.
        """
        url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Authorization": f"Basic {self.authorization_key}",
            "RqUID": str(uuid.uuid4())  # Уникальный идентификатор запроса
        }
        data = {"scope": "GIGACHAT_API_PERS"}  # Параметры запроса для получения нужного scope
        try:
            # Делаем POST-запрос к GigaChat OAuth-эндпоинту
            response = requests.post(url, headers=headers, data=data, verify=False)
            response.raise_for_status()  # Если ответ не 2xx, выбрасываем ошибку
            token_info = response.json()
            self.access_token = token_info["access_token"]
            # 'expires_at' приходит в миллисекундах — делим на 1000 и преобразуем
            self.token_expiry = datetime.utcfromtimestamp(token_info["expires_at"] / 1000)
            logger.info("GigaChat access token получен.")
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при получении токена GigaChat: {e}")
            raise

    def generate_recipe(self, user_message: str):
        """
        Генерируем ответ (рекомендацию фильма) через GigaChat API.
        Передаём user_message как вход пользователя.
        """
        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_access_token()}",  # Подставляем текущий токен
            "Content-Type": "application/json",
            "X-Client-ID": GIGACHAT_CLIENT_ID,
            "X-Request-ID": str(uuid.uuid4()),
            "X-Session-ID": str(uuid.uuid4())
        }
        payload = {
            "model": "GigaChat",
            "messages": [
                {"role": "system", "content": "Ты — помощник по фильмам."},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 500,    # Максимальное количество возвращаемых токенов
            "temperature": 0.7    # Параметр творческого разнообразия
        }

        try:
            # Делаем POST-запрос к GigaChat с нужными заголовками и данными
            response = requests.post(url, headers=headers, json=payload, verify=False)
            response.raise_for_status()
            response_data = response.json()
            # Возвращаем текстовое содержимое первого варианта ответа
            return response_data["choices"][0]["message"]["content"].strip()
        except requests.exceptions.RequestException as e:
            logger.error(f"Ошибка при обращении к GigaChat API: {e}")
            return "Извините, я не смог обработать ваш запрос в данный момент."


# Создаём экземпляр GigaChatAPI для дальнейшего использования
giga_chat_api = GigaChatAPI(GIGACHAT_AUTHORIZATION_KEY)


# ---------------------
#   Utility Functions
# ---------------------
def get_main_menu():
    """
    Главное меню (ReplyKeyboard). Возвращает клавиатуру,
    которая будет постоянно отображаться в чате.
    """
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("/setgenres"), KeyboardButton("/getgenres")],
            [KeyboardButton("/getfilm")],
            [KeyboardButton("/help")]
        ],
        resize_keyboard=True,      # Клавиатура будет адаптироваться под размер экрана
        one_time_keyboard=False    # Клавиатура не исчезает после нажатия
    )

def get_or_create_user(update: Update):
    """
    Получаем пользователя из БД по Telegram ID, или создаём, если не существует.
    Возвращает объект User или None в случае ошибки.
    """
    db = SessionLocal()   # Открываем сессию с базой данных
    user = None
    try:
        tgid = update.effective_user.id       # Telegram ID пользователя
        username = update.effective_user.username
        # Ищем пользователя по его Telegram ID
        user = db.query(User).filter(User.telegram_id == tgid).first()
        if not user:
            # Если не найден, создаём новую запись в таблице users
            user = User(telegram_id=tgid, username=username)
            db.add(user)
            db.commit()
    except Exception as e:
        logger.error(f"Ошибка при получении/создании пользователя: {e}")
    finally:
        db.close()  # Закрываем сессию
    return user


# ---------------------
#   Handlers (функции-обработчики команд и сообщений)
# ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка команды /start. Приветствие и вывод главного меню.
    """
    user = get_or_create_user(update)
    if user:
        await update.message.reply_text(
            "Добро пожаловать к GigaMovie!\n"
            "Наберите /help, чтобы увидеть список команд.",
            reply_markup=get_main_menu()
        )
    else:
        # Если пользователь не создался — сообщаем об ошибке
        await update.message.reply_text(
            "Ошибка при регистрации пользователя.",
            reply_markup=ReplyKeyboardRemove()
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка команды /help. Выводит список доступных команд.
    """
    help_text = (
        "Доступные команды:\n"
        "/start - Начать работу\n"
        "/help - Показать это сообщение\n"
        "/setgenres - Выбрать/переустановить любимые жанры\n"
        "/getgenres - Показать выбранные жанры\n"
        "/getfilm - Получить рекомендацию через GigaChat\n"
    )
    await update.message.reply_text(help_text, reply_markup=get_main_menu())


# 1) /setgenres -> Inline keyboard of genres
AVAILABLE_GENRES = [
    "Драма", "Комедия", "Боевик", "Триллер", "Ужасы",
    "Фантастика", "Фэнтези", "Романтика", "Документальное кино", "Мультфильмы/Анимация"
]

async def set_genres_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка команды /setgenres. Удаляем все старые жанры пользователя,
    предлагаем выбрать новые через InlineKeyboard.
    """
    user = get_or_create_user(update)
    if not user:
        await update.message.reply_text("Ошибка: пользователь не найден.")
        return

    # Удаляем все старые жанры для этого пользователя
    db = SessionLocal()
    try:
        db.query(Genre).filter(Genre.user_id == user.id).delete()
        db.commit()
        logger.info(f"Старые жанры для пользователя {user.id} удалены.")
    except Exception as e:
        logger.error(f"Ошибка при удалении жанров: {e}")
    finally:
        db.close()

    # Формируем Inline-клавиатуру со списком жанров
    keyboard = []
    for g in AVAILABLE_GENRES:
        # Каждая кнопка будет иметь callback_data, начинающуюся с "genre_"
        keyboard.append([InlineKeyboardButton(g, callback_data=f"genre_{g}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Выберите жанры заново (можно нажать несколько раз).",
        reply_markup=reply_markup
    )

async def genre_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик нажатия на кнопку выбора жанра (callback_data).
    """
    query = update.callback_query
    await query.answer()  # Отвечаем на запрос, чтобы убрать "загрузка..."
    data = query.data  # например, "genre_Боевик"
    chosen_genre = data.split("_", 1)[1]  # Извлекаем название жанра

    user = get_or_create_user(update)
    if not user:
        await query.edit_message_text("Ошибка: пользователь не найден.")
        return

    db = SessionLocal()
    try:
        # Проверяем, нет ли уже такого жанра
        existing = db.query(Genre).filter(
            Genre.user_id == user.id,
            Genre.genre_name == chosen_genre
        ).first()

        if existing:
            await query.edit_message_text(f"Жанр {chosen_genre} уже был добавлен ранее.")
        else:
            # Создаём новую запись с выбранным жанром
            new_genre = Genre(user_id=user.id, genre_name=chosen_genre)
            db.add(new_genre)
            db.commit()
            await query.edit_message_text(f"Жанр {chosen_genre} добавлен!")
    except Exception as e:
        logger.error(f"Ошибка при добавлении жанра: {e}")
        await query.edit_message_text("Произошла ошибка при добавлении жанра.")
    finally:
        db.close()


# 2) /getgenres -> Display user's chosen genres
async def get_genres(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка команды /getgenres. Выводит список выбранных пользователем жанров.
    """
    user = get_or_create_user(update)
    if not user:
        await update.message.reply_text("Ошибка: пользователь не найден.")
        return

    db = SessionLocal()
    try:
        # Запрашиваем все жанры, привязанные к пользователю
        user_genres = db.query(Genre).filter(Genre.user_id == user.id).all()
        if user_genres:
            # Выводим список жанров построчно
            genres_list = "\n".join(f"- {g.genre_name}" for g in user_genres)
            await update.message.reply_text(f"Выбранные жанры:\n{genres_list}")
        else:
            await update.message.reply_text("У вас пока нет выбранных жанров.")
    except Exception as e:
        logger.error(f"Ошибка при получении жанров: {e}")
        await update.message.reply_text("Произошла ошибка при получении жанров.")
    finally:
        db.close()


# 3) /getfilm -> GigaChat recommendation
async def get_film(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка команды /getfilm. Запрашивает у GigaChat рекомендацию фильма
    на основе выбранных жанров (или случайную, если жанры не выбраны).
    """
    user = get_or_create_user(update)
    if not user:
        await update.message.reply_text("Ошибка: пользователь не найден.")
        return

    db = SessionLocal()
    try:
        user_genres = db.query(Genre).filter(Genre.user_id == user.id).all()
        db.close()

        if user_genres:
            genres_str = ", ".join(g.genre_name for g in user_genres)
        else:
            genres_str = "нет (пока не выбрано)"

        # Формируем запрос (prompt) для GigaChat
        prompt = (
            "Пользователь выбрал следующие жанры:\n"
            f"{genres_str}\n\n"
            "Пожалуйста, предложи интересный фильм в соответствии с этими жанрами, "
            "или порекомендуй любой случайный вариант, если жанров нет."
        )

        # Получаем ответ (рекомендацию) от GigaChat
        film_suggestion = giga_chat_api.generate_recipe(prompt)
        await update.message.reply_text(film_suggestion, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Ошибка в /getfilm: {e}")
        await update.message.reply_text("Произошла ошибка при получении рекомендации.")


# 4) Fallback text
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатываем произвольный текст, который не является командой.
    """
    await update.message.reply_text(
        "Извините, я не понял сообщение. Наберите /help, чтобы увидеть список команд."
    )


def main():
    """
    Точка входа в приложение. Инициализируем БД, создаём объект Application,
    регистрируем обработчики и запускаем бота в режиме polling.
    """
    init_db()  # Убедимся, что таблицы созданы, если их ещё нет

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Регистрация команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

    application.add_handler(CommandHandler("setgenres", set_genres_command))
    application.add_handler(CallbackQueryHandler(genre_callback, pattern="^genre_"))

    application.add_handler(CommandHandler("getgenres", get_genres))
    application.add_handler(CommandHandler("getfilm", get_film))

    # Обработка обычного текста (любые сообщения без команды)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )

    application.run_polling()  # Запускаем бота на постоянный опрос событий


if __name__ == "__main__":
    main()