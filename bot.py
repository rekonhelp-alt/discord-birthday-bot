import os
import discord
import psycopg2
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from contextlib import suppress
import pytz

from keep_alive import keep_alive  # если не нужен, убери

# ─── Настройки ────────────────────────────────────────────────
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ROLE_ID = int(os.getenv("ROLE_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL")  # Render даст эту переменную

MSK = pytz.timezone("Europe/Moscow")

# ─── Подключение к БД ─────────────────────────────────────────
conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cur = conn.cursor()

# создаём таблицы, если их нет
cur.execute("""
CREATE TABLE IF NOT EXISTS birthdays (
    user_id TEXT PRIMARY KEY,
    date TEXT NOT NULL
);
""")
cur.execute("""
CREATE TABLE IF NOT EXISTS budget (
    id SERIAL PRIMARY KEY,
    balance INTEGER NOT NULL
);
""")
conn.commit()

# инициализация бюджета
cur.execute("SELECT COUNT(*) FROM budget;")
if cur.fetchone()[0] == 0:
    cur.execute("INSERT INTO budget (balance) VALUES (0);")
    conn.commit()

# ─── Функции работы с БД ─────────────────────────────────────
def get_birthdays():
    cur.execute("SELECT user_id, date FROM birthdays;")
    return dict(cur.fetchall())

def set_birthday(user_id: int, date: str):
    cur.execute(
        "INSERT INTO birthdays (user_id, date) VALUES (%s, %s) "
        "ON CONFLICT (user_id) DO UPDATE SET date = EXCLUDED.date;",
        (str(user_id), date)
    )
    conn.commit()

def remove_birthday_db(user_id: int):
    cur.execute("DELETE FROM birthdays WHERE user_id = %s;", (str(user_id),))
    conn.commit()

def get_balance():
    cur.execute("SELECT balance FROM budget ORDER BY id LIMIT 1;")
    return cur.fetchone()[0]

def update_balance(amount: int):
    cur.execute("UPDATE budget SET balance = balance + %s;", (amount,))
    conn.commit()

# ─── Бот ─────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Вошёл как {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔗 Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

    check_birthdays.start()
    clear_roles.start()
    remind_birthdays.start()

# ─── Slash-команды ДР ─────────────────────────────────────────
@bot.tree.command(name="add_birthday", description="Добавить день рождения участнику")
@app_commands.describe(user="Участник", date="Дата в формате ДД/ММ")
async def add_birthday(interaction: discord.Interaction, user: discord.Member, date: str):
    set_birthday(user.id, date)
    await interaction.response.send_message(f"✅ ДР для {user.mention} установлен: {date}")

@bot.tree.command(name="my_birthday", description="Показать твой день рождения")
async def my_birthday(interaction: discord.Interaction):
    birthdays = get_birthdays()
    date = birthdays.get(str(interaction.user.id))
    if date:
        await interaction.response.send_message(f"🎂 Твой ДР: {date}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Ты ещё не добавил ДР", ephemeral=True)

@bot.tree.command(name="remove_birthday", description="Удалить день рождения участника")
@app_commands.describe(user="Участник")
async def remove_birthday(interaction: discord.Interaction, user: discord.Member):
    birthdays = get_birthdays()
    if str(user.id) in birthdays:
        remove_birthday_db(user.id)
        await interaction.response.send_message(f"🗑 ДР {user.mention} удалён")
    else:
        await interaction.response.send_message("❌ У пользователя нет сохранённого ДР")

@bot.tree.command(name="list_birthdays", description="Показать все дни рождения")
async def list_birthdays(interaction: discord.Interaction):
    birthdays = get_birthdays()
    if not birthdays:
        await interaction.response.send_message("📭 Список пуст")
        return

    today = datetime.now(MSK)
    parsed = []
    for user_id, date in birthdays.items():
        try:
            d, m = map(int, date.split("/"))
            this_year = datetime(today.year, m, d, tzinfo=MSK)
            if this_year < today:
                this_year = this_year.replace(year=today.year + 1)
            parsed.append((this_year, user_id, date))
        except:
            continue
    parsed.sort(key=lambda x: x[0])

    text = []
    for _, user_id, date in parsed:
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"ID:{user_id}"
        text.append(f"**{name}** — {date}")

    embed = discord.Embed(title="🎂 Дни рождения", description="\n".join(text), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="next_birthday", description="Показать ближайший день рождения")
async def next_birthday(interaction: discord.Interaction):
    birthdays = get_birthdays()
    if not birthdays:
        await interaction.response.send_message("📭 Список пуст")
        return

    today = datetime.now(MSK)
    parsed = []
    for user_id, date in birthdays.items():
        try:
            d, m = map(int, date.split("/"))
            this_year = datetime(today.year, m, d, tzinfo=MSK)
            if this_year < today:
                this_year = this_year.replace(year=today.year + 1)
            parsed.append((this_year, user_id, date))
        except:
            continue
    if not parsed:
        await interaction.response.send_message("❌ Нет корректных дат")
        return

    parsed.sort(key=lambda x: x[0])
    next_date, user_id, date = parsed[0]
    member = interaction.guild.get_member(int(user_id))
    name = member.display_name if member else f"ID:{user_id}"

    embed = discord.Embed(
        title="🎉 Ближайший день рождения",
        description=f"**{name}** — {date} (через {(next_date - today).days} дней)",
        color=discord.Color.green(),
    )
    await interaction.response.send_message(embed=embed)

# ─── Команды бюджета ─────────────────────────────────────────
def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "$"

@bot.tree.command(name="balance", description="Посмотреть баланс организации")
async def show_balance(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"🏦 На балансе организации: {format_money(get_balance())}"
    )

@bot.tree.command(name="add_money", description="Добавить деньги на счёт организации")
async def add_money(interaction: discord.Interaction, amount: int):
    update_balance(amount)
    await interaction.response.send_message(
        f"✅ Добавлено {format_money(amount)}. Новый баланс: {format_money(get_balance())}"
    )

@bot.tree.command(name="remove_money", description="Снять деньги со счёта организации")
async def remove_money(interaction: discord.Interaction, amount: int):
    if amount > get_balance():
        await interaction.response.send_message("❌ Недостаточно средств на счёте!")
    else:
        update_balance(-amount)
        await interaction.response.send_message(
            f"💸 Снято {format_money(amount)}. Новый баланс: {format_money(get_balance())}"
        )

# ─── Задачи ──────────────────────────────────────────────────
@tasks.loop(hours=24)
async def check_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = get_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    role = guild.get_role(ROLE_ID)
    if not channel or not role:
        return

    for user_id, date in birthdays.items():
        if date == today:
            member = guild.get_member(int(user_id))
            if member:
                with suppress(discord.Forbidden):
                    await member.add_roles(role)
                embed = discord.Embed(
                    title="🎉 Поздравляем!",
                    description=f"{member.mention}, поздравляем с Днём Рождения! 🎉",
                    color=discord.Color.gold()
                )
                await channel.send(embed=embed)

@tasks.loop(hours=24)
async def clear_roles():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = get_birthdays()
    role = guild.get_role(ROLE_ID)
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
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    tomorrow = (datetime.now(MSK) + timedelta(days=1)).strftime("%d/%m")
    birthdays = get_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    role = guild.get_role(ROLE_ID)
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
