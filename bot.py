import os
import sys
import psycopg2
from contextlib import suppress
from datetime import datetime, timedelta
import discord
from discord.ext import commands, tasks
import pytz
from keep_alive import keep_alive

# ================== Конфиг ==================
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ROLE_ID = int(os.getenv("ROLE_ID"))
DATABASE_URL = os.getenv("DATABASE_URL")

if not all([TOKEN, GUILD_ID, CHANNEL_ID, ROLE_ID, DATABASE_URL]):
    raise ValueError("❌ Не заданы переменные окружения (TOKEN, GUILD_ID, CHANNEL_ID, ROLE_ID, DATABASE_URL)")

# Часовой пояс
MSK = pytz.timezone("Europe/Moscow")

# ================== DB ==================
def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS birthdays (
            user_id BIGINT PRIMARY KEY,
            date TEXT NOT NULL
        );
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS message_template (
            id SERIAL PRIMARY KEY,
            text TEXT NOT NULL
        );
        """)
        conn.commit()

def save_birthday(user_id: int, date: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO birthdays (user_id, date)
            VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET date = EXCLUDED.date;
        """, (user_id, date))
        conn.commit()

def remove_birthday(user_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM birthdays WHERE user_id = %s;", (user_id,))
        conn.commit()

def load_birthdays():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT user_id, date FROM birthdays;")
        return {str(uid): date for uid, date in cur.fetchall()}

def save_message(text: str):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM message_template;")
        cur.execute("INSERT INTO message_template (text) VALUES (%s);", (text,))
        conn.commit()

def load_message():
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT text FROM message_template ORDER BY id DESC LIMIT 1;")
        row = cur.fetchone()
        return row[0] if row else "🎉 С днём рождения, {user}!"

# ================== Бот ==================
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------- СЛЭШ-КОМАНДЫ ----------------
@bot.tree.command(name="add_birthday", description="Добавить день рождения (формат: ДД/ММ)")
async def add_birthday(interaction: discord.Interaction, date: str):
    try:
        datetime.strptime(date, "%d/%m")
    except ValueError:
        await interaction.response.send_message("❌ Неверный формат. Используй ДД/ММ.", ephemeral=True)
        return
    save_birthday(interaction.user.id, date)
    await interaction.response.send_message(f"✅ День рождения {interaction.user.mention} сохранён: {date}")

@bot.tree.command(name="my_birthday", description="Показать твой день рождения")
async def my_birthday(interaction: discord.Interaction):
    birthdays = load_birthdays()
    bday = birthdays.get(str(interaction.user.id))
    if bday:
        await interaction.response.send_message(f"🎂 Твой день рождения: {bday}")
    else:
        await interaction.response.send_message("❌ Ты ещё не добавил свой день рождения.")

@bot.tree.command(name="remove_birthday", description="Удалить свой день рождения")
async def remove_birthday_cmd(interaction: discord.Interaction):
    remove_birthday(interaction.user.id)
    await interaction.response.send_message("🗑️ День рождения удалён.")

@bot.tree.command(name="list_birthdays", description="Список всех дней рождения")
async def list_birthdays(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("❌ Список пуст.")
        return

    # сортировка по дате от ближайшей
    today = datetime.now(MSK)
    sorted_birthdays = sorted(
        birthdays.items(),
        key=lambda x: (datetime.strptime(x[1], "%d/%m").replace(year=today.year) - today).days % 365
    )

    chunks = [sorted_birthdays[i:i + 25] for i in range(0, len(sorted_birthdays), 25)]
    embeds = []
    for chunk in chunks:
        embed = discord.Embed(title="📅 Дни рождения", color=discord.Color.blurple())
        for user_id, date in chunk:
            user = interaction.guild.get_member(int(user_id))
            if user:
                embed.add_field(name=user.display_name, value=date, inline=False)
        embeds.append(embed)

    for embed in embeds:
        await interaction.response.send_message(embed=embeds[0])
        for extra in embeds[1:]:
            await interaction.followup.send(embed=extra)

@bot.tree.command(name="next_birthday", description="Ближайший день рождения")
async def next_birthday(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("❌ Список пуст.")
        return

    today = datetime.now(MSK)
    next_user, next_date = min(
        birthdays.items(),
        key=lambda x: (datetime.strptime(x[1], "%d/%m").replace(year=today.year) - today).days % 365
    )

    member = interaction.guild.get_member(int(next_user))
    if member:
        await interaction.response.send_message(f"🎉 Ближайший ДР у {member.mention} ({next_date})")

@bot.tree.command(name="set_message", description="Установить текст поздравления (используй {user})")
async def set_message(interaction: discord.Interaction, text: str):
    save_message(text)
    await interaction.response.send_message("✅ Текст поздравления обновлён.")

# ---------------- ТАСКИ ----------------
@tasks.loop(hours=24)
async def check_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    role = guild.get_role(ROLE_ID)
    message_template = load_message()

    for user_id, date in birthdays.items():
        if date == today:
            member = guild.get_member(int(user_id))
            if member and role:
                with suppress(discord.Forbidden):
                    await member.add_roles(role)

                text = message_template.replace("{user}", member.mention)
                embed = discord.Embed(title="🎂 День Рождения!", description=text, color=discord.Color.gold())
                await channel.send(embed=embed)

@tasks.loop(hours=24)
async def clear_roles():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
    role = guild.get_role(ROLE_ID)
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
    birthdays = load_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    role = guild.get_role(ROLE_ID)

    for user_id, date in birthdays.items():
        if date == tomorrow:
            member = guild.get_member(int(user_id))
            if member:
                embed = discord.Embed(
                    title="⏰ Напоминание!",
                    description=f"Завтра день рождения у {member.mention}! {role.mention}, готовьте подарки 🎁🥳",
                    color=discord.Color.purple(),
                )
                await channel.send(embed=embed)

# ---------------- ЗАПУСК ----------------
@bot.event
async def on_ready():
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        if not check_birthdays.is_running():
            check_birthdays.start()
        if not clear_roles.is_running():
            clear_roles.start()
        if not remind_birthdays.is_running():
            remind_birthdays.start()
        print(f"✅ Бот {bot.user} успешно запущен!")
    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        sys.exit(1)

if __name__ == "__main__":
    init_db()
    keep_alive()
    bot.run(TOKEN)
