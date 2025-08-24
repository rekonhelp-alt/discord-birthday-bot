import os
import json
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta
from contextlib import suppress
import pytz
from keep_alive import keep_alive  # если не нужен, можешь убрать

# ─── Настройки ────────────────────────────────────────────────
TOKEN = os.getenv("TOKEN")  # вставь напрямую, если тестируешь локально
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))
ROLE_ID = int(os.getenv("ROLE_ID", "0"))

MSK = pytz.timezone("Europe/Moscow")

BIRTHDAYS_FILE = "birthdays.json"
MESSAGE_FILE = "message.txt"


# ─── Работа с файлами ─────────────────────────────────────────
def load_birthdays():
    if not os.path.exists(BIRTHDAYS_FILE):
        return {}
    with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_birthdays(data):
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_message():
    if not os.path.exists(MESSAGE_FILE):
        return "{user}, поздравляем с Днём Рождения! 🎉"
    with open(MESSAGE_FILE, "r", encoding="utf-8") as f:
        return f.read()


def save_message(text):
    with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
        f.write(text)


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


# ─── Slash-команды ───────────────────────────────────────────
@bot.tree.command(name="add_birthday", description="Добавить день рождения участнику")
@app_commands.describe(user="Участник", date="Дата в формате ДД/ММ")
async def add_birthday(interaction: discord.Interaction, user: discord.Member, date: str):
    birthdays = load_birthdays()
    birthdays[str(user.id)] = date
    save_birthdays(birthdays)
    await interaction.response.send_message(f"✅ ДР для {user.mention} установлен: {date}", ephemeral=True)


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


@bot.tree.command(name="list_birthdays", description="Показать все дни рождения")
async def list_birthdays(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("📭 Список пуст")
        return

    # сортировка по дате в году (с ближайших)
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

    pages = []
    chunk = []
    for _, user_id, date in parsed:
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"ID:{user_id}"
        chunk.append(f"**{name}** — {date}")
        if len(chunk) == 20:  # чтобы не было лимита
            pages.append("\n".join(chunk))
            chunk = []
    if chunk:
        pages.append("\n".join(chunk))

    for page in pages:
        embed = discord.Embed(title="🎂 Дни рождения", description=page, color=discord.Color.gold())
        await interaction.channel.send(embed=embed)


@bot.tree.command(name="set_message", description="Задать шаблон поздравления ({user} = упоминание)")
async def set_message(interaction: discord.Interaction, text: str):
    save_message(text)
    await interaction.response.send_message("✅ Шаблон обновлён", ephemeral=True)


# ─── Задачи ──────────────────────────────────────────────────
@tasks.loop(hours=24)
async def check_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
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
                msg = load_message().replace("{user}", member.mention)
                embed = discord.Embed(title="🎉 Поздравляем!", description=msg, color=discord.Color.gold())
                await channel.send(embed=embed)


@tasks.loop(hours=24)
async def clear_roles():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return
    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
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
    birthdays = load_birthdays()
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
keep_alive()  # если не нужен Render-хак, можешь закомментить
bot.run(TOKEN)
