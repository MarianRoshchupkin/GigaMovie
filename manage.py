import click
import sys
import subprocess
from dotenv import load_dotenv

from models import init_db, Base, engine

# Загружаем переменные окружения
load_dotenv()

@click.group()
def cli():
    """
    Группа CLI-команд, объединённых с помощью библиотеки click.
    """
    pass

@cli.command()
def initdb():
    """
    Команда для инициализации (создания) таблиц в базе данных.
    """
    click.echo("Инициализация базы данных...")
    try:
        init_db()
        click.echo("Таблицы успешно созданы!")
    except Exception as e:
        click.echo(f"Ошибка при создании таблиц: {e}")

@cli.command()
def runbot():
    """
    Команда для запуска Telegram-бота (скрипт bot.py).
    """
    click.echo("Запуск Telegram-бота...")
    try:
        subprocess.run([sys.executable, "bot.py"], check=True)
    except subprocess.CalledProcessError as e:
        click.echo(f"Ошибка при запуске бота: {e}")

@cli.command()
def resetdb():
    """
    Полный сброс (удаление) всех таблиц и пересоздание.
    Требует подтверждения от пользователя.
    """
    confirm = click.prompt(
        "Вы уверены, что хотите сбросить базу данных? Это действие необратимо. "
        "Введите 'yes' для продолжения",
        default="no"
    )
    if confirm.lower() == "yes":
        click.echo("Сброс базы данных...")
        try:
            # Удаляем все таблицы
            Base.metadata.drop_all(engine)
            click.echo("Все таблицы удалены.")
            # Создаём заново
            init_db()
            click.echo("База данных создана заново.")
        except Exception as e:
            click.echo(f"Ошибка при сбросе базы данных: {e}")
    else:
        click.echo("Сброс базы данных отменён.")

if __name__ == "__main__":
    # Точка входа для управления командами:
    #   python manage.py initdb
    #   python manage.py runbot
    #   python manage.py resetdb
    cli()