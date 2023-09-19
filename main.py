# Import statements and setup

import logging
import os
import re
import json
from datetime import datetime, timedelta

import discord
import requests
from discord.ext import commands, tasks

import keep_alive

# Constants
UUID_LENGTH = 32
PROFIT_FACTOR = 0.04
MAX_FLIPPING_HOURS = 168

# Intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

logging.basicConfig(level=logging.INFO)

class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_prefix = "!"

bot = Bot(intents=intents)

# Event handling

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

# Utility functions

def get_uuid_from_ign(ign):
    try:
        url = f'https://api.mojang.com/users/profiles/minecraft/{ign}'
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get('id')
    except requests.exceptions.RequestException as e:
        logging.error(f'Error getting UUID for IGN {ign}: {str(e)}')
        return None

def remove_color_symbols(text):
    return re.sub(r'§.', '', text)

def get_flip_data(uuid, days):
    try:
        url = f'https://sky.coflnet.com/api/flip/stats/player/{uuid}?days={days}&offset=0'
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f'Error fetching flip data for UUID {uuid}: {str(e)}')
        return None

def create_flipstats_embed(player, data, days):
    flips = data['flips']

    for flip in flips:
        flip["itemName"] = remove_color_symbols(flip["itemName"])
        flip["tier"] = remove_color_symbols(flip["tier"])

    top_5_flips = sorted(flips, key=lambda flip: flip["profit"], reverse=True)[:5]

    embed = discord.Embed(
        title=f'Flip Statistics for {player} (Last {days} Days)',
        color=discord.Color.blue()
    )
    embed.add_field(name="Total Profit", value=f'${int(data["totalProfit"]):,}', inline=False)

    for idx, flip in enumerate(top_5_flips, 1):
        item_name = flip["itemName"]
        tier = flip["tier"]
        profit = flip["profit"]

        formatted_profit = f'${int(profit):,}'

        field_name = f'Flip {idx}'
        field_value = f'Item: {item_name}\nTier: {tier}\nProfit: {formatted_profit}'

        embed.add_field(name=field_name, value=field_value, inline=True)

    return embed

def check_inconsistent_time_patterns(flips):
    off_hours = set([22, 23, 0, 1, 2, 3, 4, 5])  # 10 pm to 5 am EST

    purchase_count_per_night = {}

    for flip in flips:
        buy_time = format_datetime_iso(flip["buyTime"])
        hour = buy_time.hour

        if hour in off_hours:
            date_key = buy_time.date()

            if date_key in purchase_count_per_night:
                purchase_count_per_night[date_key] += 1
            else:
                purchase_count_per_night[date_key] = 1

    inconsistent_night_count = sum(1 for count in purchase_count_per_night.values() if count >= 3)

    return inconsistent_night_count >= 4

# API and configuration

HYPIXEL_API_KEY = os.environ['TEMP_API_KEY'] #hypixel hasnt approve my api key yet :(
HYPIXEL_API_BASE_URL = 'https://api.hypixel.net' # I'm lazy, no bully

# Commands

#Flipstats command
############################################################################################

@bot.slash_command(description="Sends information of a flipper!")
async def flipstats(ctx, player, days: int = 7):
    try:
        if days <= 0 or days > 7:
            await ctx.respond('Sorry, the bot can only retrieve flip data for up to 7 days due to API limitations.')
            return

        uuid = get_uuid_from_ign(player)

        if uuid is None:
            await ctx.respond('Unable to retrieve UUID for the provided IGN.')
            return

        data = get_flip_data(uuid, days)
        if data is None:
            await ctx.respond('An error occurred while fetching flip data.')
            return

        embed = create_flipstats_embed(player, data, days)
        await ctx.respond(embed=embed)

    except Exception as e:
        logging.error(f'Error: {str(e)}')
        await ctx.respond('An error occurred while processing your request.')

#Macrocheck command
############################################################################################

def format_datetime_iso(api_datetime):
    api_datetime = api_datetime.rstrip('Z')
    if '.' not in api_datetime:
        api_datetime += '.000'
    elif len(api_datetime.split('.')[1]) < 3:
        api_datetime += '0' * (3 - len(api_datetime.split('.')[1]))
    return datetime.fromisoformat(api_datetime)

@bot.slash_command(description="Check if a player is macroing flips.")
@commands.cooldown(1, 20, commands.BucketType.user)
async def macrocheck(ctx, player):
    try:
        days = 7

        uuid = get_uuid_from_ign(player)

        if uuid is None:
            await ctx.respond('Unable to retrieve UUID for the provided IGN.')
            return

        data = get_flip_data(uuid, days)
        if data is None:
            await ctx.respond('An error occurred while fetching flip data.')
            return

        flips = data['flips']
        total_profit = data['totalProfit']

        flipping_hours = {}

        for flip in flips:
            buy_time = format_datetime_iso(flip["buyTime"])
            hour_key = buy_time.strftime('%Y-%m-%d %H:00:00')

            if hour_key in flipping_hours:
                flipping_hours[hour_key] += 1
            else:
                flipping_hours[hour_key] = 1

        total_flipping_hours = min(sum(1 for count in flipping_hours.values() if count >= 2), MAX_FLIPPING_HOURS)
        profit_score = min((total_profit / 150000000) * 100, 100)
        hour_score = min((total_flipping_hours / 90) * 100, 100)

        macroing_percentage = (profit_score * 0.5 + hour_score * 0.5)

        total_reaction_time = 0
        valid_reaction_times = []

        for flip in flips:
            sell_time = format_datetime_iso(flip["sellTime"])
            buy_time = format_datetime_iso(flip["buyTime"])
            reaction_time = (sell_time - buy_time).total_seconds() / 60

            if reaction_time <= 10:
                total_reaction_time += reaction_time
                valid_reaction_times.append(reaction_time)

        if valid_reaction_times:
            average_reaction_time = total_reaction_time / len(valid_reaction_times)
        else:
            average_reaction_time = 0

        reaction_time_flag = ""

        if average_reaction_time < 5:
            reaction_time_flag = " (:x: Flagged: less than 5 minutes, High chance of Macroing :x:)"
        if average_reaction_time == 0:
            reaction_time_flag = " (No information)"

        trading_value = total_profit * PROFIT_FACTOR / 1000000

        one_month_ago = datetime.utcnow() - timedelta(days=30)
        one_month_ago_timestamp = int(one_month_ago.timestamp())

        url = f'https://api.mojang.com/users/profiles/minecraft/{player}?at={one_month_ago_timestamp}'
        response = requests.get(url)

        if response.status_code == 200:
            account_age = "older than 30 days"
        elif response.status_code == 204:
            account_age = "new account"
        else:
            account_age = "unknown"

       # Check for inconsistent time patterns
        has_inconsistent_time_patterns = check_inconsistent_time_patterns(flips)

        embed = discord.Embed(
            title=f'Macro-Check Results for {player} (Last 7 Days)',
            color=discord.Color.red() if macroing_percentage >= 50 else discord.Color.green()
        )
        embed.add_field(name="Profit", value=f"${int(total_profit):,}", inline=False)
        embed.add_field(name="Profit (IRL Trading Value)", value=f'${trading_value:.2f}', inline=False)
        embed.add_field(name="Total Flipping Hours", value=f"{total_flipping_hours} hours", inline=False)
        embed.add_field(name="Average Reaction Time (**BETA FEATURE**)", value=f"{average_reaction_time:.2f} minutes{reaction_time_flag}", inline=False)
        embed.add_field(name="Inconsistent Time Pattern (**BETA FEATURE**)", value="Detected" if has_inconsistent_time_patterns else "Not Detected", inline=False)
        embed.add_field(name="Account Age (**BETA FEATURE**)", value=account_age, inline=False)
        
        embed.set_footer(text="Disclaimer: These results are not definitive proof of macroing. They are an indication based on available data.")

        macroing_embed = discord.Embed(
            title="Macroing Percentage",
            description=f"**{macroing_percentage:.2f}%**",
            color=discord.Color.red() if macroing_percentage >= 50 else discord.Color.green()
        )
        macroing_embed.set_footer(text="Macroing percentage is an indication based on a multitude of factors, all may/can produce inaccurate results. DO NOT base this information on a report as it is just an estimation.")

        await ctx.respond(embed=embed)
        await ctx.send(embed=macroing_embed)

    except Exception as e:
        logging.error(f'Error: {str(e)}')
        await ctx.respond('An error occurred while processing your request.')

#Help command
############################################################################################

@bot.slash_command(description="Display information about available commands and credits.")
async def help(ctx):
    embed = discord.Embed(
        title="Bot Commands",
        color=discord.Color.blue()
    )

    # List of commands and their descriptions
    commands_list = [
        ("`/flipstats <player>`", "Sends information of a flipper."),
        ("`/macrocheck <player>`", "Check if a player is macroing flips."),
    ]

    # Credits for APIs and bot creator (im such a good person!!!)
    credits = (
        "This bot uses data from Mojang API, Coflsky API, and Hypixel API to provide information.\n"
        "Mojang API: https://api.mojang.com/\n"
        "Coflsky API: https://sky.coflnet.com/\n"
        "Hypixel API: https://api.hypixel.net/\n\n"
        "Bot created with love by @dc___."
    )

    for cmd, description in commands_list:
        embed.add_field(name=cmd, value=description, inline=False)

    embed.set_footer(text=credits)

    await ctx.respond(embed=embed)

#replit moment :skull: 
keep_alive.keep_alive()
bot.run(os.environ['BOT_TOKEN'])
