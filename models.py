# models.py
from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    ForeignKey,
    DateTime,
    text,
    create_engine
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

# Создаём базовый класс для декларативного стиля SQLAlchemy
Base = declarative_base()

class User(Base):
    """
    Модель таблицы 'users', хранящей информацию о пользователях бота.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)     # PK
    telegram_id = Column(BigInteger, unique=True, nullable=False)  # Уникальный Telegram ID
    username = Column(String(255), nullable=True)                  # Имя пользователя (может отсутствовать)
    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))  # Дата создания записи
    updated_at = Column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        onupdate=text("CURRENT_TIMESTAMP")
    )

    # Relationship с моделью Genre (один пользователь - много жанров)
    genres = relationship("Genre", back_populates="user", cascade="all, delete-orphan")

class Genre(Base):
    """
    Модель таблицы 'genres', где хранятся выбранные пользователем жанры.
    """
    __tablename__ = "genres"

    id = Column(Integer, primary_key=True, autoincrement=True)
    genre_name = Column(String(255), nullable=False)  # Название жанра

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # Ссылка на пользователя
    user = relationship("User", back_populates="genres")

    created_at = Column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

# ---------- DB setup ----------
# Создаём движок соединения с базой (SQLite), файл db.sqlite3
engine = create_engine("sqlite:///db.sqlite3", echo=False)

# Настраиваем SessionLocal для последующего использования
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """
    Создаём таблицы в базе, если их ещё нет.
    """
    Base.metadata.create_all(engine)

if __name__ == "__main__":
    # Если запустить файл напрямую, создадим базу
    init_db()