import os
import json
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from contextlib import suppress
import pytz

# ─── keep_alive (можешь убрать, если не используешь) ─────────
try:
    from keep_alive import keep_alive
except Exception:
    def keep_alive():
        pass

# ─── Настройки ────────────────────────────────────────────────
TOKEN = os.getenv("TOKEN")  # можно вставить строкой для локального теста
GUILD_ID = int(os.getenv("GUILD_ID", "0"))  # укажи ID сервера для мгновенной синхронизации
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ROLE_ID = int(os.getenv("ROLE_ID", "0"))

MSK = pytz.timezone("Europe/Moscow")

# Всегда сохраняем файлы рядом с bot.py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BIRTHDAYS_FILE = os.path.join(BASE_DIR, "birthdays.json")
MESSAGE_FILE   = os.path.join(BASE_DIR, "message.txt")
BUDGET_FILE    = os.path.join(BASE_DIR, "budget.json")

# ─── Инициализация файлов ────────────────────────────────────
def ensure_files():
    if not os.path.exists(BIRTHDAYS_FILE):
        with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=4)
    if not os.path.exists(MESSAGE_FILE):
        with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
            f.write("{user}, поздравляем с Днём Рождения! 🎉")
    if not os.path.exists(BUDGET_FILE):
        with open(BUDGET_FILE, "w", encoding="utf-8") as f:
            json.dump({"balance": 0}, f, ensure_ascii=False, indent=4)

# ─── Работа с файлами ─────────────────────────────────────────
def load_birthdays():
    try:
        with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_birthdays(data):
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def load_message():
    try:
        with open(MESSAGE_FILE, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return "{user}, поздравляем с Днём Рождения! 🎉"

def save_message(text):
    with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
        f.write(text)

def load_budget():
    try:
        with open(BUDGET_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"balance": 0}

def save_budget(data):
    with open(BUDGET_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ─── Бот ─────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True  # не забудь включить "Server Members Intent" в портале Discord (если нужно)
bot = commands.Bot(command_prefix="!", intents=intents)

# Утилита форматирования денег
def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "$"

# ─── Синхронизация команд ────────────────────────────────────
async def sync_commands_here():
    """
    Быстрая синхронизация слеш-команд на конкретной гильдии (без глобальной задержки).
    Если GUILD_ID не задан — синхронизируем глобально.
    """
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
            print(f"🔗 Синхронизировано {len(synced)} команд на гильдии {GUILD_ID}")
        else:
            synced = await bot.tree.sync()
            print(f"🔗 Синхронизировано {len(synced)} глобальных команд")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

@bot.event
async def on_ready():
    print(f"✅ Вошёл как {bot.user}")
    ensure_files()
    await sync_commands_here()

    # Старт планировщиков
    check_birthdays.start()
    clear_roles.start()
    remind_birthdays.start()

# Команда ручной синхронизации (только для админов сервера)
@bot.tree.command(name="sync_commands", description="Пересинхронизировать команды на этом сервере (админам)")
async def sync_commands_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Нужны права администратора.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    await sync_commands_here()
    await interaction.followup.send("✅ Команды пересинхронизированы.", ephemeral=True)

# ─── Slash-команды: Дни рождения ─────────────────────────────
@bot.tree.command(name="add_birthday", description="Добавить день рождения участнику")
@app_commands.describe(user="Участник", date="Дата в формате ДД/ММ")
async def add_birthday(interaction: discord.Interaction, user: discord.Member, date: str):
    try:
        # Базовая валидация формата ДД/ММ
        d, m = map(int, date.split("/"))
        assert 1 <= d <= 31 and 1 <= m <= 12
    except Exception:
        await interaction.response.send_message("❌ Формат даты должен быть ДД/ММ, например 05/11", ephemeral=True)
        return

    birthdays = load_birthdays()
    birthdays[str(user.id)] = f"{d:02d}/{m:02d}"
    save_birthdays(birthdays)
    await interaction.response.send_message(f"✅ ДР для {user.mention} установлен: {d:02d}/{m:02d}", ephemeral=True)

@bot.tree.command(name="my_birthday", description="Показать твой день рождения")
async def my_birthday(interaction: discord.Interaction):
    birthdays = load_birthdays()
    date = birthdays.get(str(interaction.user.id))
    if date:
        await interaction.response.send_message(f"🎂 Твой ДР: {date}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Ты ещё не добавил ДР", ephemeral=True)

@bot.tree.command(name="remove_birthday", description="Удалить день рождения участника")
@app_commands.describe(user="Участник")
async def remove_birthday(interaction: discord.Interaction, user: discord.Member):
    birthdays = load_birthdays()
    if str(user.id) in birthdays:
        birthdays.pop(str(user.id))
        save_birthdays(birthdays)
        await interaction.response.send_message(f"🗑 ДР {user.mention} удалён", ephemeral=True)
    else:
        await interaction.response.send_message("❌ У пользователя нет сохранённого ДР", ephemeral=True)

# Реальный обработчик списка (общая логика)
async def _send_birthdays_list(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)  # важно, чтобы не было «приложение не отвечает»
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.followup.send("📭 Список пуст", ephemeral=True)
        return

    today = datetime.now(MSK)
    parsed = []
    for user_id, date in birthdays.items():
        try:
            d, m = map(int, date.split("/"))
            this_year = datetime(today.year, m, d, tzinfo=MSK)
            if this_year < today:
                this_year = this_year.replace(year=today.year + 1)
            parsed.append((this_year, user_id, f"{d:02d}/{m:02d}"))
        except Exception:
            continue

    parsed.sort(key=lambda x: x[0])

    # Разбиваем на страницы по 20
    pages, chunk = [], []
    for _, user_id, date in parsed:
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"ID:{user_id}"
        chunk.append(f"**{name}** — {date}")
        if len(chunk) == 20:
            pages.append("\n".join(chunk))
            chunk = []
    if chunk:
        pages.append("\n".join(chunk))

    # Отправляем страницы
    for page in pages:
        embed = discord.Embed(title="🎂 Дни рождения", description=page, color=discord.Color.gold())
        await interaction.followup.send(embed=embed, ephemeral=True)

# Вариант с названием /list_birthdays
@bot.tree.command(name="list_birthdays", description="Показать все дни рождения")
async def list_birthdays(interaction: discord.Interaction):
    await _send_birthdays_list(interaction)

# Дополнительный алиас под старое имя /list_birthday
@bot.tree.command(name="list_birthday", description="Показать все дни рождения (алиас)")
async def list_birthday(interaction: discord.Interaction):
    await _send_birthdays_list(interaction)

@bot.tree.command(name="set_message", description="Задать шаблон поздравления ({user} = упоминание)")
async def set_message(interaction: discord.Interaction, text: str):
    save_message(text)
    await interaction.response.send_message("✅ Шаблон обновлён", ephemeral=True)

# ─── Slash-команды: Финансы ──────────────────────────────────
@bot.tree.command(name="add_money", description="Добавить деньги на счёт организации")
async def add_money(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Сумма должна быть больше 0", ephemeral=True)
        return
    budget = load_budget()
    budget["balance"] = int(budget.get("balance", 0)) + int(amount)
    save_budget(budget)
    await interaction.response.send_message(
        f"✅ Добавлено {format_money(amount)}. Новый баланс: {format_money(budget['balance'])}",
        ephemeral=True
    )

@bot.tree.command(name="remove_money", description="Снять деньги со счёта организации")
async def remove_money(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Сумма должна быть больше 0", ephemeral=True)
        return
    budget = load_budget()
    balance = int(budget.get("balance", 0))
    if amount > balance:
        await interaction.response.send_message("❌ Недостаточно средств на счёте!", ephemeral=True)
        return
    budget["balance"] = balance - int(amount)
    save_budget(budget)
    await interaction.response.send_message(
        f"💸 Снято {format_money(amount)}. Новый баланс: {format_money(budget['balance'])}",
        ephemeral=True
    )

@bot.tree.command(name="balance", description="Посмотреть баланс организации")
async def show_balance(interaction: discord.Interaction):
    budget = load_budget()
    await interaction.response.send_message(
        f"🏦 На балансе организации: {format_money(int(budget.get('balance', 0)))}",
        ephemeral=True
    )

# ─── Планировщики ────────────────────────────────────────────
@tasks.loop(hours=24)
async def check_birthdays():
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    if not guild:
        return

    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
    channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    role = guild.get_role(ROLE_ID) if ROLE_ID else None
    if not channel or not role:
        return

    for user_id, date in birthdays.items():
        if date == today:
            member = guild.get_member(int(user_id))
            if member:
                with suppress(discord.Forbidden):
                    await member.add_roles(role)
                msg = load_message().replace("{user}", member.mention)
                embed = discord.Embed(title="🎉 Поздравляем!", description=msg, color=discord.Color.gold())
                await channel.send(embed=embed)

@tasks.loop(hours=24)
async def clear_roles():
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    if not guild:
        return

    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
    role = guild.get_role(ROLE_ID) if ROLE_ID else None
    if not role:
        return

    for user_id, date in birthdays.items():
        if date != today:
            member = guild.get_member(int(user_id))
            if member and role in member.roles:
                with suppress(discord.Forbidden):
                    await member.remove_roles(role)

@tasks.loop(hours=24)
async def remind_birthdays():
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    if not guild:
        return

    tomorrow = (datetime.now(MSK) + timedelta(days=1)).strftime("%d/%m")
    birthdays = load_birthdays()
    channel = bot.get_channel(CHANNEL_ID) if CHANNEL_ID else None
    role = guild.get_role(ROLE_ID) if ROLE_ID else None
    if not channel or not role:
        return

    for user_id, date in birthdays.items():
        if date == tomorrow:
            member = guild.get_member(int(user_id))
            if member:
                embed = discord.Embed(
                    title="⏰ Напоминание",
                    description=f"Завтра у {member.mention} день рождения! {role.mention}, готовьте подарки 🎁",
                    color=discord.Color.purple(),
                )
                await channel.send(embed=embed)

# ─── Запуск ───────────────────────────────────────────────────
keep_alive()
bot.run(TOKEN)
