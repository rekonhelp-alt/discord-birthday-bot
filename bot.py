import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
import pytz
import psycopg2
from psycopg2.extras import DictCursor
from contextlib import suppress
from keep_alive import keep_alive

# --- Константы
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ROLE_ID = int(os.getenv("ROLE_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

MSK = pytz.timezone("Europe/Moscow")

# --- Бот
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- Работа с БД
def db_connect():
    return psycopg2.connect(DATABASE_URL, sslmode="require", cursor_factory=DictCursor)

def init_db():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS birthdays (
                    user_id BIGINT PRIMARY KEY,
                    birthday VARCHAR(5) NOT NULL
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id SERIAL PRIMARY KEY,
                    template TEXT NOT NULL
                );
            """)
            conn.commit()

def add_birthday(user_id: int, date: str):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO birthdays (user_id, birthday)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET birthday = EXCLUDED.birthday;
            """, (user_id, date))
            conn.commit()

def get_birthday(user_id: int):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT birthday FROM birthdays WHERE user_id = %s;", (user_id,))
            row = cur.fetchone()
            return row["birthday"] if row else None

def remove_birthday(user_id: int):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM birthdays WHERE user_id = %s;", (user_id,))
            conn.commit()

def get_all_birthdays():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT user_id, birthday FROM birthdays;")
            rows = cur.fetchall()
            return {str(r["user_id"]): r["birthday"] for r in rows}

def set_message_template(template: str):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM messages;")
            cur.execute("INSERT INTO messages (template) VALUES (%s);", (template,))
            conn.commit()

def load_message():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT template FROM messages ORDER BY id DESC LIMIT 1;")
            row = cur.fetchone()
            return row["template"] if row else "Поздравляем {user} 🎉"

# --- События
@bot.event
async def on_ready():
    init_db()
    try:
        synced = await bot.tree.sync()
        print(f"✅ Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"Ошибка sync: {e}")
    check_birthdays.start()
    clear_roles.start()
    remind_birthdays.start()
    print(f"Бот {bot.user} готов!")

# --- Slash-команды
@bot.tree.command(name="add_birthday", description="Добавить или изменить день рождения")
async def add_birthday_cmd(interaction: discord.Interaction, member: discord.Member, date: str):
    add_birthday(member.id, date)
    await interaction.response.send_message(f"✅ День рождения для {member.mention} установлен: {date}")

@bot.tree.command(name="my_birthday", description="Посмотреть свой день рождения")
async def my_birthday(interaction: discord.Interaction):
    date = get_birthday(interaction.user.id)
    if date:
        await interaction.response.send_message(f"📅 Ваш день рождения: {date}")
    else:
        await interaction.response.send_message("❌ У вас не установлен день рождения.")

@bot.tree.command(name="remove_birthday", description="Удалить день рождения")
async def remove_birthday_cmd(interaction: discord.Interaction):
    remove_birthday(interaction.user.id)
    await interaction.response.send_message("🗑 День рождения удалён!")

@bot.tree.command(name="list_birthdays", description="Список всех дней рождения")
async def list_birthdays(interaction: discord.Interaction):
    birthdays = get_all_birthdays()
    if not birthdays:
        await interaction.response.send_message("❌ Список пуст.")
        return

    today = datetime.now(MSK).date()
    parsed = []
    for uid, d in birthdays.items():
        day, month = map(int, d.split("/"))
        year = today.year
        bday = datetime(year, month, day).date()
        if bday < today:
            bday = datetime(year + 1, month, day).date()
        parsed.append((uid, d, (bday - today).days))

    parsed.sort(key=lambda x: x[2])

    chunks = [parsed[i:i+25] for i in range(0, len(parsed), 25)]
    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title="🎂 Список дней рождения" + (f" (стр. {i+1})" if len(chunks) > 1 else ""),
            color=discord.Color.blue()
        )
        for uid, d, days_left in chunk:
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else f"UID {uid}"
            embed.add_field(
                name=name,
                value=f"{d} (через {days_left} дн.)",
                inline=False
            )
        await interaction.response.send_message(embed=embed) if i == 0 else await interaction.followup.send(embed=embed)

@bot.tree.command(name="set_message", description="Задать шаблон поздравления")
async def set_message(interaction: discord.Interaction, text: str):
    set_message_template(text)
    await interaction.response.send_message("✅ Шаблон сохранён!")

# --- Tasks
@tasks.loop(hours=24)
async def check_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = get_all_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    role = guild.get_role(ROLE_ID)
    template = load_message()
    for uid, date in birthdays.items():
        if date == today:
            member = guild.get_member(int(uid))
            if member and role:
                with suppress(discord.Forbidden):
                    await member.add_roles(role)
                embed = discord.Embed(
                    title="🎉 День Рождения!",
                    description=template.replace("{user}", member.mention),
                    color=discord.Color.gold()
                )
                await channel.send(embed=embed)

@tasks.loop(hours=24)
async def clear_roles():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = get_all_birthdays()
    role = guild.get_role(ROLE_ID)
    if not role:
        return
    for uid, date in birthdays.items():
        if date != today:
            member = guild.get_member(int(uid))
            if member and role in member.roles:
                with suppress(discord.Forbidden):
                    await member.remove_roles(role)

@tasks.loop(hours=24)
async def remind_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    tomorrow = (datetime.now(MSK) + timedelta(days=1)).strftime("%d/%m")
    birthdays = get_all_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    role = guild.get_role(ROLE_ID)
    for uid, date in birthdays.items():
        if date == tomorrow:
            member = guild.get_member(int(uid))
            if member:
                embed = discord.Embed(
                    title="⏰ Напоминание!",
                    description=f"Завтра день рождения у {member.mention}! {role.mention}, готовьтесь 🎁🥳",
                    color=discord.Color.purple()
                )
                await channel.send(embed=embed)

# --- Запуск
keep_alive()
bot.run(TOKEN)
