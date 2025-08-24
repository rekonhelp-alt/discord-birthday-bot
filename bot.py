import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
from datetime import datetime, timedelta
import pytz
import os
from contextlib import suppress
from keep_alive import keep_alive

# ==== Настройки ====
TOKEN = os.getenv("TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
ROLE_ID = int(os.getenv("ROLE_ID"))
MSK = pytz.timezone("Europe/Moscow")

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


# ==== Работа с файлами ====
def load_birthdays():
    if not os.path.exists("birthdays.json"):
        return {}
    with open("birthdays.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_birthdays(data):
    with open("birthdays.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def load_message():
    if not os.path.exists("message.txt"):
        return "Сегодня день рождения у {user}! 🎉🥳"
    with open("message.txt", "r", encoding="utf-8") as f:
        return f.read()


# ==== События ====
@bot.event
async def on_ready():
    try:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=guild)   # чистим старые команды
        await bot.tree.sync(guild=guild)       # синхронизируем новые
        print("✅ Команды пересинхронизированы.")
    except Exception as e:
        print(f"Ошибка синхронизации: {e}")

    check_birthdays.start()
    clear_roles.start()
    remind_birthdays.start()
    print(f"✅ Бот {bot.user} запущен!")


# ==== Команды ====
@bot.tree.command(name="add_birthday", description="Добавить день рождения")
@app_commands.describe(date="Формат: ДД/ММ")
async def add_birthday(interaction: discord.Interaction, date: str):
    try:
        datetime.strptime(date, "%d/%m")
    except ValueError:
        await interaction.response.send_message("❌ Неверный формат. Используй ДД/ММ")
        return

    birthdays = load_birthdays()
    birthdays[str(interaction.user.id)] = date
    save_birthdays(birthdays)

    await interaction.response.send_message(f"✅ День рождения {date} сохранён!")


@bot.tree.command(name="list_birthdays", description="Показать список ДР")
async def list_birthdays(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("⚠️ Список пуст.")
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
    embed = discord.Embed(title="📅 Список дней рождения", color=discord.Color.blue())
    count = 0

    for user_id, date in sorted_birthdays:
        member = interaction.guild.get_member(int(user_id))
        name = member.display_name if member else f"ID {user_id}"
        embed.add_field(name=name, value=date, inline=False)
        count += 1
        if count == 25:
            pages.append(embed)
            embed = discord.Embed(title="📅 Список дней рождения (продолжение)", color=discord.Color.blue())
            count = 0

    if count > 0:
        pages.append(embed)

    for page in pages:
        await interaction.response.send_message(embed=page)
        interaction = await interaction.original_response()


@bot.tree.command(name="set_message", description="Изменить шаблон поздравления")
async def set_message(interaction: discord.Interaction, text: str):
    with open("message.txt", "w", encoding="utf-8") as f:
        f.write(text)
    await interaction.response.send_message("✅ Сообщение обновлено!")


@bot.tree.command(name="next_birthday", description="🎉 Показать ближайший день рождения")
async def next_birthday(interaction: discord.Interaction):
    birthdays = load_birthdays()
    if not birthdays:
        await interaction.response.send_message("⚠️ Список пуст.")
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
    user_id, date_str = sorted_birthdays[0]
    member = interaction.guild.get_member(int(user_id))
    name = member.mention if member else f"ID {user_id}"

    await interaction.response.send_message(f"🎂 Ближайший ДР: {name} — {date_str}")


# ==== Задачи ====
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

    role = discord.utils.get(guild.roles, name="Madison")
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


# ==== Запуск ====
keep_alive()
bot.run(TOKEN)
