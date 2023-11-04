# Feel free to DM me with any questions or concerns at dc___ (#0000) on discord.
# If you want to contribute (code or hosting), also please DM me as I am not going to be checking git until I release a major update.
import json
import logging
import os
import re
from datetime import datetime, timedelta

import discord
import requests
from discord import option
from discord.ext import commands, tasks

UUID_LENGTH = 32
PROFIT_FACTOR = .022
profit_weight = 1
hour_weight = 4
reaction_time_weight = 0.2
inconsistent_time_pattern_weight = 0.2

MAX_FLIPPING_HOURS = 168

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

logging.basicConfig(level=logging.INFO)


class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.command_prefix = "!"


bot = Bot(intents=intents)

TOKEN = 'nice try lmao'


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")



class MyView(discord.ui.View): 
    @discord.ui.button(label="Click for More Information", style=discord.ButtonStyle.primary, emoji="😎")
    async def button_callback(self, button, interaction):
        await interaction.response.send_message("This command checks if a player might be macroing flips based on various factors, yet only a few are shown, such as profit, flipping hours, reaction time, and more. Other features are hidden as they either are not weighed or they are too complicated to be shown, such as the work in progress of the Machine Learning. The explanation for the features can be seen below:\n\n\n"
                            "- **Profit:** Calculates the total profit made in the last 7 days.\n"
                            "- **Profit (IRL Trading Value):** Converts profit to an estimated real-world trading value using standard rates.\n"
                            "- **Total Flipping Hours:** Counts the total hours spent flipping items, calculated using multiple factors.\n"
                            "- **Inconsistent Time Pattern:** Detects if there are patterns of inconsistent flipping times, calculated using multiple factors.\n"
                            "- **Average Reaction Time:** Measures the average time between buying and selling items. (Beta Feature)\n"
                            "- **Account Age:** Checks if the Minecraft account is older than 30 days (Beta Feature).\n\n", ephemeral=True) 


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
    off_hours = set([22, 23, 0, 1, 2, 3, 4, 5])
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



HYPIXEL_API_KEY = "i no leaky"
HYPIXEL_API_BASE_URL = 'https://api.hypixel.net'  # I'm lazy, no bully

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


def format_datetime_iso(api_datetime):
    api_datetime = api_datetime.rstrip('Z')
    if '.' not in api_datetime:
        api_datetime += '.000'
    elif len(api_datetime.split('.')[1]) < 3:
        api_datetime += '0' * (3 - len(api_datetime.split('.')[1]))
    return datetime.fromisoformat(api_datetime)

@bot.slash_command(description="Check if a player is macroing flips.")
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

        macroing_percentage = 0  

        total_reaction_time = 0
        valid_reaction_times = []

        for flip in flips:
            sell_time = format_datetime_iso(flip["sellTime"])
            buy_time = format_datetime_iso(flip["buyTime"])
            reaction_time = (sell_time - buy_time).total_seconds() / 60

            if reaction_time <= 5:
                total_reaction_time += reaction_time
                valid_reaction_times.append(reaction_time)

        if valid_reaction_times:
            average_reaction_time = total_reaction_time / len(valid_reaction_times)
        else:
            average_reaction_time = 0

        reaction_time_flag = ""

        if average_reaction_time < 2:
            reaction_time_flag = " (:x: Flagged as a low reaction time, this is a beta feature and very inaccurate. :x:)"
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

        has_inconsistent_time_patterns = check_inconsistent_time_patterns(flips)

        inconsistent_time_pattern_percentage = 10 if has_inconsistent_time_patterns else 0
        total_flipping_hours = min(sum(1 for count in flipping_hours.values() if count >= 2), MAX_FLIPPING_HOURS)
        profit_score = min((total_profit / 150000000) * 100, 100)
        hour_score = min((total_flipping_hours / 90) * 100, 100)
        average_reaction_time_percentage = min((10 - average_reaction_time) / 10 * 10, 10)
        inconsistent_time_pattern_percentage = 10 if has_inconsistent_time_patterns else 0
        macroing_percentage = (
                (profit_score * profit_weight + hour_score * hour_weight + average_reaction_time_percentage * reaction_time_weight +
                 inconsistent_time_pattern_percentage * inconsistent_time_pattern_weight) / (
                        profit_weight + hour_weight + reaction_time_weight + inconsistent_time_pattern_weight)
        )
        
        
        embed = discord.Embed(
            title=f'Macro-Check Results for {player} (Last 7 Days)',
            color=discord.Color.red() if macroing_percentage >= 50 else discord.Color.green()
        )
        embed.add_field(name="Profit", value=f"${int(total_profit):,}", inline=False)
        embed.add_field(name="Profit (IRL Trading Value)", value=f'${trading_value:.2f}', inline=False)
        embed.add_field(name="Total Flipping Hours", value=f"{total_flipping_hours} hours", inline=False)
        embed.add_field(name="Inconsistent Time Pattern",
                        value="Detected" if has_inconsistent_time_patterns else "Not Detected", inline=False)
        embed.add_field(name="Average Reaction Time (**BETA FEATURE**)",
                        value=f"{average_reaction_time:.2f} minutes{reaction_time_flag}", inline=False)
        embed.add_field(name="Account Age (**BETA FEATURE**)", value=account_age, inline=False)

        embed.set_footer(
            text="Disclaimer: These results are not definitive proof of macroing. They are an indication based on available data.")

        macroing_embed = discord.Embed(
            title="Macroing Percentage",
            description=f"**{macroing_percentage:.2f}%**",
            color=discord.Color.red() if macroing_percentage >= 50 else discord.Color.green()
        )
        macroing_embed.set_footer(
            text="Macroing percentage is an indication based on a multitude of factors, all may/can produce inaccurate results. DO NOT base this information on a report as it is just an estimation.\n"
        "\n"
        "Made with <3 by dc!")
 

        
        await ctx.respond(embed=embed)
        await ctx.send(embed=macroing_embed, view=MyView())
                    
    except Exception as e:
        logging.error(f'Error: {str(e)}')
        await ctx.respond('An error occurred while processing your request.')


@bot.slash_command(name="help", description="Display information about available commands and credits.")
async def help(ctx):
    embed = discord.Embed(
        title="Bot Commands",
        color=discord.Color.blue()
    )

    commands_list = [
        ("`/flipstats <player>`", "Sends information of a flipper."),
        ("`/macrocheck <player>`", "Check if a player is macroing flips."),
        ("`/webhookdelete <url>`", "Deletes a webhook, we hate ratters!"),
    ]

    credits = (
        "This bot uses data from Mojang API, Coflsky API, and Hypixel API to provide information.\n"
        "Mojang API: https://api.mojang.com/\n"
        "Coflsky API: https://sky.coflnet.com/\n"
        "Hypixel API: https://api.hypixel.net/\n\n"
        "Made with <3 by dc!"
    )

    for cmd, description in commands_list:
        embed.add_field(name=cmd, value=description, inline=False)

    embed.set_footer(text=credits)

    await ctx.respond(embed=embed)


# Useless commands (just utility stuff)

@bot.slash_command(
    name="ping",
    description="Ping the server and returns latency."
)
async def ping(ctx):
    latency = round(bot.latency * 1000)

    await ctx.respond(
        embed=discord.Embed(
            description=f"Latency: {latency}ms"
        ).set_author(name="Pong!")
        .set_footer(text="Made with <3 by dc!")
    )

    print(f"Bot pinged. Latency: {latency}ms")


@bot.slash_command(
    name="membercount",
    description="Membercount of the server"
)
async def membercount(ctx):
    await ctx.respond(
        embed=discord.Embed(
            description=f"Membercount: {ctx.guild.member_count}"
        ).set_author(name=f"Membercount of {ctx.guild.name}")
        .set_footer(text="Made with <3 by dc!")
    )


@bot.slash_command(name="invite", description="Get the bot's server invite link.")
async def help(ctx):
    embed = discord.Embed(
        title="Invite Link",
        description="The Invite link for the bot with ADMINISTRATOR Permissions is [here.](https://discord.com/api/oauth2/authorize?client_id=1151049092659683328&permissions=8&scope=bot) \n"
        "You may also invite the bot with the minimum permissions [here](https://discord.com/api/oauth2/authorize?client_id=1151049092659683328&permissions=964220542016&scope=bot), but features may be limited and/or not work. ",
        color=discord.Color.blue()
    )

    embed.set_footer(text="The Support Server for this bot is currently RatFlipper Guild, a skyblock guild for all flippers with a companion in-game guild.\n"
                          "The link is discord.gg/neVyFgjMrp. \n"
                          " \n"
                          "Made with <3 by dc!")

    await ctx.respond(embed=embed)

@bot.slash_command(name="servercount", description="Show the number of servers the bot is in and the largest server.")
async def servercount(ctx):
    server_count = len(bot.guilds)
    
    largest_server = None
    largest_member_count = 0
    for guild in bot.guilds:
        if guild.member_count > largest_member_count:
            largest_member_count = guild.member_count
            largest_server = guild
    
    largest_server_info = f"Largest Server: {largest_server.name} (Members: {largest_member_count})" if largest_server else "No servers found."
    
    await ctx.respond(
        embed=discord.Embed(
            description=f"I am currently in {server_count} servers.\n{largest_server_info}"
        ).set_author(name="Server Count")
        .set_footer(text="Made with <3 by dc!")
    ) 
    
LOG_WEBHOOK_URL = 'https://discord.com/api/webhooks/nicertrylmao' 

def delete_webhook(webhook_url):
    requests.delete(webhook_url)
    check = requests.get(webhook_url)
    if check.status_code == 404:
        return True 
    elif check.status_code == 200:
        return False  

@bot.slash_command(name="webhookdeleter", description="Deletes a webhook. (This is an Advanced Command!))")
async def webhookdeleter(ctx, webhook_url):
    is_deleted = delete_webhook(webhook_url)
    if is_deleted:
        await ctx.respond('Webhook deleted successfully.')
    else:
        await ctx.respond('Failed to delete the webhook.')

        
@bot.slash_command(description="Get player's auction data")
async def auctions(ctx, player):
    try:
        uuid = get_uuid_from_ign(player)
        if uuid is None:
            await ctx.respond('Unable to retrieve UUID for the provided IGN.')
            return
       
        hypixel_api_url = f'https://api.hypixel.net/skyblock/auction?key={HYPIXEL_API_KEY}&player={uuid}'
        response = requests.get(hypixel_api_url)
        data = response.json()
        
        if not data.get('success', False):
            cause = data.get('cause', 'Unknown')
            print(f'API Error Cause: {cause}')
            await ctx.respond('Failed to retrieve auction data from the Hypixel API. This is because the bot does not have a Hypixel Production API Key. This command will be released in the future.')
            return
        
        auctions = data.get('auctions', [])
        
        formatted_auctions = []
        for auction in auctions:
            formatted_auction = {
                "Item Name": auction.get('item_name', 'Unknown'),
                "Category": auction.get('category', 'Unknown'),
                "Tier": auction.get('tier', 'Unknown'),
                "Starting Bid": auction.get('starting_bid', 0),
                "Highest Bid Amount": auction.get('highest_bid_amount', 0),
            }
            formatted_auctions.append(formatted_auction)
        
        if formatted_auctions:
            response_message = "Auction Data:\n\n"
            for i, auction in enumerate(formatted_auctions, start=1):
                response_message += f"**Auction {i}:**\n"
                for key, value in auction.items():
                    response_message += f"{key}: {value}\n"
                response_message += "\n"
            await ctx.respond(response_message)
        else:
            await ctx.respond('No auction data available for this player.')
    
    except Exception as e:
        await ctx.respond(f'An error occurred while processing your request: {str(e)}')

        
@bot.slash_command(description="Provide feedback to the bot developers.")
async def feedback(ctx):
    feedback_link = "https://docs.google.com/forms/d/e/1FAIpQLSe8LURaXbwUzzXMgjR92R90VPoRlSbtqt6HHRwOQtJ9U_pf5w/viewform?usp=sf_link"
    
    feedback_embed = discord.Embed(
        title="Google Form Link",
        description="We appreciate your feedback! Please provide your ideas and thoughts through the following link:",
        color=discord.Color.blue()
    )
    feedback_embed.add_field(name="Google Forms Link", value=feedback_link)
    
    await ctx.respond(embed=feedback_embed)
    
bot.run(TOKEN)
