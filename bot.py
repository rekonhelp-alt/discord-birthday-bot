import os
import json
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timedelta
from contextlib import suppress
import pytz
from keep_alive import keep_alive

# Таймзона
MSK = pytz.timezone("Europe/Moscow")

# === НАСТРОЙКИ ===
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ROLE_ID = int(os.getenv("ROLE_ID"))

BIRTHDAYS_FILE = "birthdays.json"
MESSAGE_FILE = "message.txt"


# === ФУНКЦИИ ===
def load_birthdays() -> dict:
    if not os.path.exists(BIRTHDAYS_FILE):
        return {}
    with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_birthdays(data: dict):
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_message() -> str:
    if not os.path.exists(MESSAGE_FILE):
        return "Поздравляем {user} с Днём Рождения! 🎉"
    with open(MESSAGE_FILE, "r", encoding="utf-8") as f:
        return f.read()


# === BOT ===
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


# === КОМАНДЫ ===
@bot.tree.command(name="add_birthday", description="🎂 Добавить день рождения")
async def add_birthday(interaction: discord.Interaction, user: discord.User, date: str):
    birthdays = load_birthdays()
    birthdays[str(user.id)] = date
    save_birthdays(birthdays)
    await interaction.response.send_message(f"✅ ДР для {user.mention} установлен: {date}")


@bot.tree.command(name="remove_birthday", description="❌ Удалить день рождения")
async def remove_birthday(interaction: discord.Interaction, user: discord.User):
    birthdays = load_birthdays()
    if str(user.id) in birthdays:
        del birthdays[str(user.id)]
        save_birthdays(birthdays)
        await interaction.response.send_message(f"✅ ДР для {user.mention} удалён.")
    else:
        await interaction.response.send_message("⚠️ ДР для этого пользователя не найден.")


@bot.tree.command(name="set_message", description="✏ Изменить текст поздравления")
async def set_message(interaction: discord.Interaction, text: str):
    with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
        f.write(text)
    await interaction.response.send_message("✅ Сообщение обновлено.")


@bot.tree.command(name="list_birthdays", description="📅 Показать список дней рождения")
async def list_birthdays(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("⚠️ Список дней рождений пуст.")
        return

    today = datetime.now(MSK)
    current_year = today.year

    def to_date(date_str: str) -> datetime:
        day, month = map(int, date_str.split("/"))
        date = datetime(current_year, month, day, tzinfo=MSK)
        if date < today:
            date = date.replace(year=current_year + 1)
        return date

    sorted_birthdays = sorted(birthdays.items(), key=lambda x: to_date(x[1]))

    pages = []
    embed = discord.Embed(title="🎉 Список дней рождения", color=discord.Color.blue())

    for i, (user_id, date_str) in enumerate(sorted_birthdays, 1):
        member = interaction.guild.get_member(int(user_id))
        name = member.mention if member else f"ID {user_id}"
        embed.add_field(name=f"{i}. {date_str}", value=name, inline=False)

        # если превысили лимит 25 — создаём новую страницу
        if len(embed.fields) == 25:
            pages.append(embed)
            embed = discord.Embed(
                title="🎉 Список дней рождения (продолжение)",
                color=discord.Color.blue()
            )

    if len(embed.fields) > 0:
        pages.append(embed)

    await interaction.response.send_message(embed=pages[0])
    for page in pages[1:]:
        await interaction.followup.send(embed=page)


# === ТАСКИ ===
@tasks.loop(hours=24)
async def check_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    today = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    role = guild.get_role(ROLE_ID)
    message_template = load_message()

    for user_id, date in birthdays.items():
        if date == today:
            member = guild.get_member(int(user_id))
            if member and role:
                with suppress(discord.Forbidden):
                    await member.add_roles(role)

                text = message_template.replace("{user}", member.mention)
                embed = discord.Embed(
                    title="🎂 День Рождения!",
                    description=text,
                    color=discord.Color.gold(),
                )
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
    if not isinstance(channel, discord.TextChannel):
        return

    role = guild.get_role(ROLE_ID)
    if not role:
        return

    for user_id, date in birthdays.items():
        if date == tomorrow:
            member = guild.get_member(int(user_id))
            if member:
                embed = discord.Embed(
                    title="⏰ Напоминание!",
                    description=(
                        f"Завтра день рождения у {member.mention}! "
                        f"{role.mention}, готовьте подарки 🎁🥳"
                    ),
                    color=discord.Color.purple(),
                )
                await channel.send(embed=embed)


# === START ===
@bot.event
async def on_ready():
    try:
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        print("✅ Команды синхронизированы.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

    check_birthdays.start()
    clear_roles.start()
    remind_birthdays.start()
    print(f"✅ Бот {bot.user} запущен!")


keep_alive()
bot.run(TOKEN)
