import json
import os
import sys
from contextlib import suppress
from datetime import datetime, timedelta

import discord
import pytz
from discord.ext import commands, tasks


# ==================== Конфиг ====================
TOKEN = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ROLE_ID = os.getenv("ROLE_ID")

if not TOKEN or not GUILD_ID or not CHANNEL_ID or not ROLE_ID:
    raise ValueError("❌ Укажи TOKEN, GUILD_ID, CHANNEL_ID, ROLE_ID в Replit Secrets.")

GUILD_ID = int(GUILD_ID)
CHANNEL_ID = int(CHANNEL_ID)
ROLE_ID = int(ROLE_ID)

BIRTHDAYS_FILE = "birthdays.json"
MESSAGE_FILE = "message.json"
MSK = pytz.timezone("Europe/Moscow")

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())


# ==================== Работа с файлами ====================
def load_birthdays() -> dict[str, str]:
    if not os.path.exists(BIRTHDAYS_FILE):
        return {}
    with open(BIRTHDAYS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_birthdays(birthdays: dict[str, str]) -> None:
    with open(BIRTHDAYS_FILE, "w", encoding="utf-8") as f:
        json.dump(birthdays, f, indent=4, ensure_ascii=False)


def load_message() -> str:
    if not os.path.exists(MESSAGE_FILE):
        return "🎉 Сегодня день рождения у {user}! Поздравляем 🥳"
    with open(MESSAGE_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get(
            "message", "🎉 Сегодня день рождения у {user}! Поздравляем 🥳"
        )


def save_message(msg: str) -> None:
    with open(MESSAGE_FILE, "w", encoding="utf-8") as f:
        json.dump({"message": msg}, f, indent=4, ensure_ascii=False)


def parse_date(date_str: str) -> datetime | None:
    try:
        return datetime.strptime(date_str, "%d/%m")
    except ValueError:
        return None


# ==================== Событие запуска ====================
@bot.event
async def on_ready():
    try:
        guild = discord.Object(id=GUILD_ID)
        cmds = await bot.tree.sync(guild=guild)

        print(f"✅ Синхронизировано {len(cmds)} команд:")
        for c in cmds:
            print(f"  /{c.name} — {c.description}")

        if not check_birthdays.is_running():
            check_birthdays.start()
        if not clear_roles.is_running():
            clear_roles.start()
        if not remind_birthdays.is_running():
            remind_birthdays.start()

        print("=====================================")
        print(f"✅ Бот {bot.user} успешно запущен!")
        print("=====================================")

    except Exception as e:
        print(f"❌ Ошибка запуска: {e}")
        sys.exit(1)


# ==================== Таски ====================
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


# ==================== Команды ====================
@bot.tree.command(
    name="add_birthday",
    description="Добавить ДР участнику (ДД/ММ)",
    guild=discord.Object(id=GUILD_ID),
)
async def add_birthday(
    interaction: discord.Interaction, member: discord.Member, date: str
):
    parsed = parse_date(date)
    if not parsed:
        await interaction.response.send_message("❌ Формат: ДД/ММ (например, 05/09).")
        return

    birthdays = load_birthdays()
    birthdays[str(member.id)] = date
    save_birthdays(birthdays)

    await interaction.response.send_message(
        f"✅ День рождения {member.mention} установлен как {date}"
    )


@bot.tree.command(
    name="my_birthday",
    description="Установить свой ДР (ДД/ММ)",
    guild=discord.Object(id=GUILD_ID),
)
async def my_birthday(interaction: discord.Interaction, date: str):
    parsed = parse_date(date)
    if not parsed:
        await interaction.response.send_message(
            "❌ Формат: ДД/ММ (например, 05/09).", ephemeral=True
        )
        return

    birthdays = load_birthdays()
    birthdays[str(interaction.user.id)] = date
    save_birthdays(birthdays)

    await interaction.response.send_message(
        f"✅ Твой ДР установлен как {date}", ephemeral=True
    )


@bot.tree.command(
    name="list_birthdays",
    description="Список всех ДР",
    guild=discord.Object(id=GUILD_ID),
)
async def list_birthdays(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("❌ Список пуст.")
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        await interaction.response.send_message("❌ Сервер не найден.")
        return

    today = datetime.now(MSK)
    upcoming = []

    for user_id, date_str in birthdays.items():
        parsed = parse_date(date_str)
        if not parsed:
            continue
        candidate = parsed.replace(year=today.year).replace(tzinfo=MSK)
        if candidate < today:
            candidate = candidate.replace(year=today.year + 1)
        member = guild.get_member(int(user_id))
        if member:
            upcoming.append((candidate, member, date_str))

    if not upcoming:
        await interaction.response.send_message("❌ Нет корректных дат.")
        return

    upcoming.sort(key=lambda x: x[0])

    embeds = []
    embed = discord.Embed(title="📅 Список ДР", color=discord.Color.blue())

    for i, (_, member, date_str) in enumerate(upcoming, start=1):
        embed.add_field(
            name=f"{i}. {member.display_name}",
            value=f"🎂 {date_str}",
            inline=False
        )

        if i % 25 == 0:
            embeds.append(embed)
            embed = discord.Embed(title="📅 Список ДР (продолжение)", color=discord.Color.blue()
)

    if embed.fields:
        embeds.append(embed)

    await interaction.response.send_message(embeds=embeds)


@bot.tree.command(
    name="next_birthday",
    description="Показать ближайший ДР",
    guild=discord.Object(id=GUILD_ID),
)
async def next_birthday(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("❌ Список пуст.")
        return

    today = datetime.now(MSK)
    upcoming = []

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        await interaction.response.send_message("❌ Сервер не найден.")
        return

    for user_id, date_str in birthdays.items():
        parsed = parse_date(date_str)
        if not parsed:
            continue
        candidate = parsed.replace(year=today.year).replace(tzinfo=MSK)
        if candidate < today:
            candidate = candidate.replace(year=today.year + 1)
        member = guild.get_member(int(user_id))
        if member:
            upcoming.append((candidate, member, date_str))

    if not upcoming:
        await interaction.response.send_message("❌ Нет корректных дат.")
        return

    nearest = min(upcoming, key=lambda x: x[0])
    _, member, date_str = nearest

    await interaction.response.send_message(
        f"🎂 Ближайший ДР у {member.mention}: {date_str}"
    )


@bot.tree.command(
    name="remove_birthday",
    description="Удалить ДР участника",
    guild=discord.Object(id=GUILD_ID),
)
async def remove_birthday(
    interaction: discord.Interaction, member: discord.Member
):
    birthdays = load_birthdays()
    if str(member.id) in birthdays:
        del birthdays[str(member.id)]
        save_birthdays(birthdays)
        await interaction.response.send_message(f"🗑 ДР {member.mention} удалён.")
    else:
        await interaction.response.send_message("❌ У этого участника нет ДР.")


@bot.tree.command(
    name="set_message",
    description="Установить текст поздравления (используй {user})",
    guild=discord.Object(id=GUILD_ID),
)
async def set_message(interaction: discord.Interaction, *, text: str):
    save_message(text)
    await interaction.response.send_message(f"✅ Текст поздравления обновлён.")


# ==================== Запуск ====================
bot.run(TOKEN)
