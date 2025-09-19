import discord
from discord import app_commands
import sqlite3
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import os

def init_db():
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id INTEGER PRIMARY KEY, user_id INTEGER, timestamp TEXT, entry REAL, sl REAL, tp REAL, exit REAL, 
                  profit REAL, rr REAL, is_win INTEGER, is_archived INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reset_stats
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, reset_date TEXT, wins INTEGER, 
                  losses INTEGER, total_profit REAL, avg_rr REAL)''')
    conn.commit()
    conn.close()

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        self.tree.sync()

client = MyClient(intents=discord.Intents.default())

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')

# Helper to get economic calendar
def get_economic_calendar():
    try:
        url = "https://www.investing.com/economic-calendar/"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.text, 'html.parser')
        events = []
        table = soup.find('table', id='economicCalendarData')
        if table:
            rows = table.find_all('tr', class_='js-event-item')
            for row in rows:
                time = row.find('td', class_='time').text.strip()
                currency = row.find('td', class_='flagCur').text.strip()
                impact = row.find('td', class_='sentiment').get('data-img_key', '').replace('bull', 'Impact ')
                event = row.find('td', class_='event').text.strip()
                events.append(f"{time} {currency} {impact}: {event}")
        return events[:10] if events else ["No events found."]
    except Exception:
        return ["Unable to fetch calendar at this time."]

# Command: /trade
@client.tree.command(name="trade", description="Log a completed trade with RR calculation")
@app_commands.describe(entry="Entry price", sl="Stop loss", tp="Take profit", exit="Exit price")
async def trade_command(interaction: discord.Interaction, entry: float, sl: float, tp: float, exit: float):
    if entry <= sl or tp <= entry:
        await interaction.response.send_message("Invalid trade parameters (assuming long position).")
        return
    rr = (tp - entry) / (entry - sl) if (entry - sl) != 0 else 0
    profit = exit - entry
    is_win = 1 if profit > 0 else 0
    timestamp = datetime.now().isoformat()
    user_id = interaction.user.id
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("INSERT INTO trades (user_id, timestamp, entry, sl, tp, exit, profit, rr, is_win) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
              (user_id, timestamp, entry, sl, tp, exit, profit, rr, is_win))
    conn.commit()
    conn.close()
    await interaction.response.send_message(f"Trade logged! RR: {rr:.2f}, Profit: {profit:.2f}, Win: {'Yes' if is_win else 'No'}")

# Command: /tradingjournal
@client.tree.command(name="tradingjournal", description="View your recent trades")
async def tradingjournal(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT timestamp, entry, exit, profit, rr FROM trades WHERE user_id=? ORDER BY timestamp DESC LIMIT 10", (user_id,))
    trades = c.fetchall()
    conn.close()
    if not trades:
        await interaction.response.send_message("No trades found.")
        return
    response = "Recent Trades:\n" + "\n".join([f"{t[0]}: Entry {t[1]}, Exit {t[2]}, Profit {t[3]:.2f}, RR {t[4]:.2f}" for t in trades])
    await interaction.response.send_message(response)

# Command: /besttrade
@client.tree.command(name="besttrade", description="View your best trade by profit")
async def besttrade(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT timestamp, entry, exit, profit, rr FROM trades WHERE user_id=? ORDER BY profit DESC LIMIT 1", (user_id,))
    trade = c.fetchone()
    conn.close()
    if not trade:
        await interaction.response.send_message("No trades found.")
        return
    await interaction.response.send_message(f"Best Trade: {trade[0]} - Entry {trade[1]}, Exit {trade[2]}, Profit {trade[3]:.2f}, RR {trade[4]:.2f}")

# Command: /worsttrade
@client.tree.command(name="worsttrade", description="View your worst trade by profit")
async def worsttrade(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT timestamp, entry, exit, profit, rr FROM trades WHERE user_id=? ORDER BY profit ASC LIMIT 1", (user_id,))
    trade = c.fetchone()
    conn.close()
    if not trade:
        await interaction.response.send_message("No trades found.")
        return
    await interaction.response.send_message(f"Worst Trade: {trade[0]} - Entry {trade[1]}, Exit {trade[2]}, Profit {trade[3]:.2f}, RR {trade[4]:.2f}")

# Command: /calendar
@client.tree.command(name="calendar", description="View upcoming economic calendar events")
async def calendar(interaction: discord.Interaction):
    events = get_economic_calendar()
    response = "Economic Calendar (Top 10):\n" + "\n".join(events)
    await interaction.response.send_message(response)

# Helper for stats
def get_stats(user_id, start_time=None, archived=False):
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    where = "user_id=?" 
    params = [user_id]
    if not archived:
        where += " AND is_archived=0"
    if start_time:
        where += " AND timestamp >= ?"
        params.append(start_time)
    c.execute(f"SELECT COUNT(*) FROM trades WHERE {where}", params)
    total = c.fetchone()[0]
    c.execute(f"SELECT COUNT(*) FROM trades WHERE {where} AND is_win=1", params)
    wins = c.fetchone()[0]
    losses = total - wins
    c.execute(f"SELECT SUM(profit) FROM trades WHERE {where}", params)
    total_profit = c.fetchone()[0] or 0
    c.execute(f"SELECT AVG(rr) FROM trades WHERE {where}", params)
    avg_rr = c.fetchone()[0] or 0
    conn.close()
    return wins, losses, total_profit, avg_rr

# Command: /dailystats
@client.tree.command(name="dailystats", description="View today's stats")
async def dailystats(interaction: discord.Interaction):
    user_id = interaction.user.id
    start = datetime.now().replace(hour=0, minute=0, second=0).isoformat()
    wins, losses, total_profit, avg_rr = get_stats(user_id, start)
    await interaction.response.send_message(f"Daily Stats: Wins {wins}, Losses {losses}, Profit {total_profit:.2f}, Avg RR {avg_rr:.2f}")

# Command: /weeklystats
@client.tree.command(name="weeklystats", description="View this week's stats")
async def weeklystats(interaction: discord.Interaction):
    user_id = interaction.user.id
    start = (datetime.now() - timedelta(days=7)).isoformat()
    wins, losses, total_profit, avg_rr = get_stats(user_id, start)
    await interaction.response.send_message(f"Weekly Stats: Wins {wins}, Losses {losses}, Profit {total_profit:.2f}, Avg RR {avg_rr:.2f}")

# Command: /monthlystats
@client.tree.command(name="monthlystats", description="View this month's stats")
async def monthlystats(interaction: discord.Interaction):
    user_id = interaction.user.id
    start = (datetime.now() - timedelta(days=30)).isoformat()
    wins, losses, total_profit, avg_rr = get_stats(user_id, start)
    await interaction.response.send_message(f"Monthly Stats: Wins {wins}, Losses {losses}, Profit {total_profit:.2f}, Avg RR {avg_rr:.2f}")

# Command: /stats
@client.tree.command(name="stats", description="View current period stats")
async def stats(interaction: discord.Interaction):
    user_id = interaction.user.id
    wins, losses, total_profit, avg_rr = get_stats(user_id)
    await interaction.response.send_message(f"Current Stats: Wins {wins}, Losses {losses}, Profit {total_profit:.2f}, Avg RR {avg_rr:.2f}")

# Command: /lifetimestats
@client.tree.command(name="lifetimestats", description="View lifetime stats")
async def lifetimestats(interaction: discord.Interaction):
    user_id = interaction.user.id
    wins, losses, total_profit, avg_rr = get_stats(user_id, archived=True)
    await interaction.response.send_message(f"Lifetime Stats: Wins {wins}, Losses {losses}, Profit {total_profit:.2f}, Avg RR {avg_rr:.2f}")

# Command: /streak
@client.tree.command(name="streak", description="View current win streak")
async def streak(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT is_win FROM trades WHERE user_id=? AND is_archived=0 ORDER BY timestamp DESC", (user_id,))
    trades = c.fetchall()
    conn.close()
    current_streak = 0
    for t in trades:
        if t[0] == 1:
            current_streak += 1
        else:
            break
    await interaction.response.send_message(f"Current Win Streak: {current_streak}")

# Command: /leaderboard
@client.tree.command(name="leaderboard", description="View top users by lifetime profit")
async def leaderboard(interaction: discord.Interaction):
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT user_id, SUM(profit) as total FROM trades GROUP BY user_id ORDER BY total DESC LIMIT 5")
    tops = c.fetchall()
    conn.close()
    if not tops:
        await interaction.response.send_message("No leaderboard data.")
        return
    response = "Leaderboard (Top 5 by Profit):\n"
    for i, (uid, total) in enumerate(tops, 1):
        user = await client.fetch_user(uid)
        response += f"{i}. {user.name}: {total:.2f}\n"
    await interaction.response.send_message(response)

# Command: /resetstats
@client.tree.command(name="resetstats", description="Reset current stats (archives trades)")
async def resetstats(interaction: discord.Interaction):
    user_id = interaction.user.id
    wins, losses, total_profit, avg_rr = get_stats(user_id)
    if wins + losses == 0:
        await interaction.response.send_message("No current trades to reset.")
        return
    reset_date = datetime.now().isoformat()
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("INSERT INTO reset_stats (user_id, reset_date, wins, losses, total_profit, avg_rr) VALUES (?, ?, ?, ?, ?, ?)",
              (user_id, reset_date, wins, losses, total_profit, avg_rr))
    c.execute("UPDATE trades SET is_archived=1 WHERE user_id=? AND is_archived=0", (user_id,))
    conn.commit()
    conn.close()
    await interaction.response.send_message("Stats reset! Previous stats archived.")

# Command: /previousresetstats
@client.tree.command(name="previousresetstats", description="View stats from previous reset")
async def previousresetstats(interaction: discord.Interaction):
    user_id = interaction.user.id
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT wins, losses, total_profit, avg_rr FROM reset_stats WHERE user_id=? ORDER BY reset_date DESC LIMIT 1", (user_id,))
    stats = c.fetchone()
    conn.close()
    if not stats:
        await interaction.response.send_message("No previous reset found.")
        return
    await interaction.response.send_message(f"Previous Reset: Wins {stats[0]}, Losses {stats[1]}, Profit {stats[2]:.2f}, Avg RR {stats[3]:.2f}")

# Command: /allresetstats (admin only)
@client.tree.command(name="allresetstats", description="View all reset stats (admin only)")
@app_commands.checks.has_permissions(administrator=True)
async def allresetstats(interaction: discord.Interaction):
    conn = sqlite3.connect('trades.db')
    c = conn.cursor()
    c.execute("SELECT user_id, reset_date, wins, losses, total_profit FROM reset_stats ORDER BY reset_date DESC")
    all_resets = c.fetchall()
    conn.close()
    if not all_resets:
        await interaction.response.send_message("No reset stats found.")
        return
    response = "All Reset Stats:\n"
    for uid, date, wins, losses, profit in all_resets[:20]:  # Limit to 20 for message size
        user = await client.fetch_user(uid)
        response += f"{user.name} ({date}): Wins {wins}, Losses {losses}, Profit {profit:.2f}\n"
    await interaction.response.send_message(response)

# Command: /ping
@client.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(client.latency * 1000)
    await interaction.response.send_message(f"Pong! Latency: {latency}ms")

# Command: /help
@client.tree.command(name="help", description="List all commands")
async def help_command(interaction: discord.Interaction):
    commands_list = [
        "/trade: Log a trade",
        "/tradingjournal: View recent trades",
        "/besttrade: Best trade",
        "/worsttrade: Worst trade",
        "/calendar: Economic calendar",
        "/dailystats: Daily stats",
        "/weeklystats: Weekly stats",
        "/monthlystats: Monthly stats",
        "/stats: Current stats",
        "/lifetimestats: Lifetime stats",
        "/streak: Win streak",
        "/leaderboard: Top users",
        "/resetstats: Reset current stats",
        "/previousresetstats: Previous reset stats",
        "/allresetstats: All resets (admin)",
        "/ping: Bot latency",
        "/help: This list"
    ]
    response = "Available Commands:\n" + "\n".join(commands_list)
    await interaction.response.send_message(response)

if __name__ == "__main__":
    init_db()
    client.run(os.environ['DISCORD_TOKEN'])
