import json
import os
import sys
from contextlib import suppress
from datetime import datetime, timedelta

import discord
import pytz
from discord.ext import commands, tasks

from keep_alive import keep_alive  # оставил, т.к. ты деплоишь на Render

# ==================== Конфиг ====================
TOKEN = os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ROLE_ID = os.getenv("ROLE_ID")

if not TOKEN or not GUILD_ID or not CHANNEL_ID or not ROLE_ID:
    raise ValueError(
        "❌ Переменные окружения не установлены! "
        "Задай TOKEN, GUILD_ID, CHANNEL_ID, ROLE_ID в Render Secrets."
    )

GUILD_ID = int(GUILD_ID)
CHANNEL_ID = int(CHANNEL_ID)
ROLE_ID = int(ROLE_ID)

BIRTHDAYS_FILE = "birthdays.json"
MESSAGE_FILE = "message.json"

MSK = pytz.timezone("Europe/Moscow")

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ==================== Файлы ====================
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
        # сохраняем без года, используем 1900 чтобы strptime прошел
        return datetime.strptime(date_str, "%d/%m")
    except ValueError:
        return None


def normalize_ddmm(s: str) -> str:
    """Вернёт дату строго в формате ДД/ММ с ведущими нулями."""
    dt = parse_date(s)
    return dt.strftime("%d/%m") if dt else s


# ==================== События ====================
@bot.event
async def on_ready():
    try:
        guild_obj = discord.Object(id=GUILD_ID)

        # Синхронизируем ТОЛЬКО на нужном сервере (чтобы не было дублей глобальных)
        synced = await bot.tree.sync(guild=guild_obj)
        print(f"✅ Синхронизировано {len(synced)} команд на сервере {GUILD_ID}:")
        for c in synced:
            print(f"  /{c.name} — {c.description}")

        # Старт фоновых задач
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
        print(f"❌ Ошибка при запуске: {e}")
        sys.exit(1)


# ==================== Таски ====================
@tasks.loop(hours=24)
async def check_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    today_ddmm = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    role = guild.get_role(ROLE_ID)
    message_template = load_message()

    for user_id, ddmm in birthdays.items():
        if ddmm == today_ddmm:
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

    today_ddmm = datetime.now(MSK).strftime("%d/%m")
    birthdays = load_birthdays()
    role = guild.get_role(ROLE_ID)
    if not role:
        return

    for user_id, ddmm in birthdays.items():
        if ddmm != today_ddmm:
            member = guild.get_member(int(user_id))
            if member and role in member.roles:
                with suppress(discord.Forbidden):
                    await member.remove_roles(role)


@tasks.loop(hours=24)
async def remind_birthdays():
    guild = bot.get_guild(GUILD_ID)
    if not guild:
        return

    tomorrow_ddmm = (datetime.now(MSK) + timedelta(days=1)).strftime("%d/%m")
    birthdays = load_birthdays()
    channel = bot.get_channel(CHANNEL_ID)
    if not isinstance(channel, discord.TextChannel):
        return

    ping_role = discord.utils.get(guild.roles, name="Madison")
    for user_id, ddmm in birthdays.items():
        if ddmm == tomorrow_ddmm:
            member = guild.get_member(int(user_id))
            if member:
                mention_txt = (
                    f"{ping_role.mention}, " if ping_role else ""
                )
                embed = discord.Embed(
                    title="⏰ Напоминание!",
                    description=(
                        f"Завтра день рождения у {member.mention}! "
                        f"{mention_txt}готовьте подарки 🎁🥳"
                    ),
                    color=discord.Color.purple(),
                )
                await channel.send(embed=embed)


# ==================== Команды ====================
GUILD_SCOPE = discord.Object(id=GUILD_ID)


@bot.tree.command(
    name="add_birthday",
    description="Добавить/изменить день рождения участнику (ДД/ММ)",
    guild=GUILD_SCOPE,
)
async def add_birthday(
    interaction: discord.Interaction,
    member: discord.Member,
    date: str,
):
    """Правит ДР ИМЕННО выбранного участника."""
    parsed = parse_date(date)
    if not parsed:
        await interaction.response.send_message(
            "❌ Неверный формат. Используй ДД/ММ (например, 05/09).",
            ephemeral=True,
        )
        return

    bdays = load_birthdays()
    bdays[str(member.id)] = normalize_ddmm(date)
    save_birthdays(bdays)

    await interaction.response.send_message(
        f"✅ День рождения для {member.mention} установлен как "
        f"{bdays[str(member.id)]}",
        ephemeral=True,
    )


@bot.tree.command(
    name="my_birthday",
    description="Установить свой день рождения (ДД/ММ)",
    guild=GUILD_SCOPE,
)
async def my_birthday(interaction: discord.Interaction, date: str):
    parsed = parse_date(date)
    if not parsed:
        await interaction.response.send_message(
            "❌ Неверный формат. Используй ДД/ММ (например, 05/09).",
            ephemeral=True,
        )
        return

    bdays = load_birthdays()
    bdays[str(interaction.user.id)] = normalize_ddmm(date)
    save_birthdays(bdays)

    await interaction.response.send_message(
        f"✅ Твой день рождения установлен как {bdays[str(interaction.user.id)]}",
        ephemeral=True,
    )


@bot.tree.command(
    name="remove_birthday",
    description="Удалить ДР участника (если не указать — удалит твой)",
    guild=GUILD_SCOPE,
)
async def remove_birthday(
    interaction: discord.Interaction,
    member: discord.Member | None = None,
):
    target = member or interaction.user
    bdays = load_birthdays()

    if str(target.id) in bdays:
        del bdays[str(target.id)]
        save_birthdays(bdays)
        await interaction.response.send_message(
            f"🗑 ДР для {target.mention} удалён.",
            ephemeral=True,
        )
    else:
        await interaction.response.send_message(
            "❌ У этого участника нет сохранённого ДР.",
            ephemeral=True,
        )


@bot.tree.command(
    name="set_message",
    description="Задать текст поздравления (используй {user})",
    guild=GUILD_SCOPE,
)
async def set_message(interaction: discord.Interaction, *, text: str):
    save_message(text)
    await interaction.response.send_message(
        "✅ Текст поздравления обновлён.",
        ephemeral=True,
    )


@bot.tree.command(
    name="list_birthdays",
    description="Список всех ДР по ближайшей дате",
    guild=GUILD_SCOPE,
)
async def list_birthdays(interaction: discord.Interaction):
    bdays = load_birthdays()
    if not bdays:
        await interaction.response.send_message("❌ Список пуст.")
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        await interaction.response.send_message("❌ Сервер не найден.")
        return

    today = datetime.now(MSK)
    upcoming: list[tuple[datetime, discord.Member, str]] = []

    for user_id, ddmm in bdays.items():
        parsed = parse_date(ddmm)
        if not parsed:
            continue

        # candidate — aware datetime в текущем или следующем году
        candidate = parsed.replace(year=today.year).replace(tzinfo=MSK)
        if candidate < today:
            candidate = candidate.replace(year=today.year + 1)

        member = guild.get_member(int(user_id))
        if member:
            upcoming.append((candidate, member, normalize_ddmm(ddmm)))

    if not upcoming:
        await interaction.response.send_message("❌ Нет корректных дат.")
        return

    # сортировка по ближайшей дате
    upcoming.sort(key=lambda x: x[0])

    # Discord ограничивает эмбед 25 полями → шлём батчами
    CHUNK = 25
    chunks = [upcoming[i : i + CHUNK] for i in range(0, len(upcoming), CHUNK)]

    embeds: list[discord.Embed] = []
    for idx, chunk in enumerate(chunks, start=1):
        embed = discord.Embed(
            title="📅 Список дней рождения" + (f" — страница {idx}" if len(chunks) > 1 else ""),
            color=discord.Color.blue(),
        )
        for _, member, ddmm in chunk:
            embed.add_field(name=member.display_name, value=f"🎂 {ddmm}", inline=False)
        embeds.append(embed)

    # если одна страница — шлём один эмбед, иначе — все
    if len(embeds) == 1:
        await interaction.response.send_message(embed=embeds[0])
    else:
        await interaction.response.send_message(embeds=embeds)


@bot.tree.command(
    name="next_birthday",
    description="Показать ближайший ДР",
    guild=GUILD_SCOPE,
)
async def next_birthday(interaction: discord.Interaction):
    bdays = load_birthdays()
    if not bdays:
        await interaction.response.send_message("❌ Список пуст.")
        return

    guild = bot.get_guild(GUILD_ID)
    if not guild:
        await interaction.response.send_message("❌ Сервер не найден.")
        return

    today = datetime.now(MSK)
    candidates: list[tuple[datetime, discord.Member, str]] = []

    for user_id, ddmm in bdays.items():
        parsed = parse_date(ddmm)
        if not parsed:
            continue
        candidate = parsed.replace(year=today.year).replace(tzinfo=MSK)
        if candidate < today:
            candidate = candidate.replace(year=today.year + 1)
        member = guild.get_member(int(user_id))
        if member:
            candidates.append((candidate, member, normalize_ddmm(ddmm)))

    if not candidates:
        await interaction.response.send_message("❌ Нет корректных дат.")
        return

    nearest = min(candidates, key=lambda x: x[0])
    _, member, ddmm = nearest
    await interaction.response.send_message(
        f"🎂 Ближайший день рождения у {member.mention}: {ddmm}"
    )


# ==================== Запуск ====================
keep_alive()
bot.run(TOKEN)
