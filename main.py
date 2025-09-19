import discord
from discord.ext import commands
import os, json
from datetime import datetime, timedelta, timezone
from flask import Flask
import threading

# ===================== CONFIG =====================
DATA_FILE = "trades.json"
TOKEN = os.getenv("DISCORD_TOKEN")

# ===================== DATA HELPERS =====================
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

trade_data = load_data()

def ensure_user(uid):
    if uid not in trade_data:
        trade_data[uid] = {"trades": []}

def log_trade(uid, record):
    ensure_user(uid)
    trade_data[uid]["trades"].append(record)
    save_data(trade_data)

# ===================== DISCORD BOT =====================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=["!", "/"], intents=intents)

# ===================== KEEP ALIVE =====================
app = Flask("")

@app.route("/")
def home():
    return "TradeBot is vibin'!"

def run_web():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = threading.Thread(target=run_web)
    t.start()

# ===================== UTILS =====================
def compute_rr(entry, sl, tp):
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk == 0: return 0.0
    return round(reward / risk, 2)

def filter_trades(trades, period):
    now = datetime.now(timezone.utc)
    if period == "daily":
        cutoff = now - timedelta(days=1)
    elif period == "weekly":
        cutoff = now - timedelta(days=7)
    elif period == "monthly":
        cutoff = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return trades
    return [t for t in trades if datetime.fromisoformat(t["timestamp"]) > cutoff]

def stats_summary(trades):
    total = len(trades)
    wins = sum(1 for t in trades if t["result"] == "tp")
    losses = sum(1 for t in trades if t["result"] == "sl")
    neutral = total - wins - losses
    total_rr = sum(t["rr"] for t in trades)
    avg_rr = (total_rr / total) if total > 0 else 0.0
    win_rate = (wins / (total - neutral) * 100) if (total - neutral) > 0 else 0.0
    return total, wins, losses, neutral, total_rr, avg_rr, win_rate

# ===================== COMMANDS =====================
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user}")

@bot.command()
async def ping(ctx):
    await ctx.send("🏓 Boing! I'm alive and kickin'!")

@bot.command()
async def help(ctx):
    text = """
🎉 **TradeBot — Your Trading Sidekick!**
Prefix with `!`, `/`, or `#`.

➕ **Log a Trade**
!trade <pair> <buy/sell> <entry> <sl> <tp> <tp/sl/none>

📊 **Check Your Game**
!stats → All-time glory
!dailystats / !weeklystats / !monthlystats

🏆 **Show Off**
!leaderboard → Top traders
!besttrade / !worsttrade
!streak → Win streak vibes

🛠 **Tweak It**
!removelasttrade
!resetstats (yours) or !resetstats all (admin only)

📅 **Time Travel**
!calendar → Trade timeline
"""
    await ctx.send(text)

@bot.command()
async def trade(ctx, pair: str, direction: str, entry: float, sl: float, tp: float, result: str):
    direction = direction.lower()
    result = result.lower()
    if direction not in ("buy", "sell") or result not in ("tp", "sl", "none"):
        await ctx.send("❌ Whoops! Try: !trade xauusd buy 3300 3290 3330 tp/sl/none")
        return

    rr_val = compute_rr(entry, sl, tp)
    rr_signed = rr_val if result == "tp" else -rr_val if result == "sl" else 0.0

    record = {
        "pair": pair,
        "dir": direction,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "result": result,
        "rr": rr_signed,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    user_id = str(ctx.author.id)
    log_trade(user_id, record)

    await ctx.send(f"🎉 Nice one! {pair.upper()} {direction.upper()} is logged 🎉 RR: {rr_signed:+.2f} 🚀 "
                   f"(TP {'reached' if result == 'tp' else 'not reached' if result == 'none' else 'missed'}!)")

def build_stats_table(ctx, trades, title):
    total, wins, losses, neutral, total_rr, avg_rr, win_rate = stats_summary(trades)
    table = f"**{ctx.author.name} — {title}**\n" \
            f"| Metric         | Value         |\n" \
            f"|---------------:|---------------|\n" \
            f"| Trades         | {total}        |\n" \
            f"| Wins           | {wins}         |\n" \
            f"| Losses         | {losses}       |\n" \
            f"| Neutral        | {neutral}      |\n" \
            f"| Total RR       | {total_rr:+.2f}    |\n" \
            f"| Avg RR         | {avg_rr:.2f}   |\n" \
            f"| Win Rate       | {win_rate:.1f}%  |"
    return table

@bot.command()
async def stats(ctx):
    user_id = str(ctx.author.id)
    trades = trade_data.get(user_id, {}).get("trades", [])
    if not trades:
        await ctx.send("📊 No trades yet, champ! Start logging!")
        return
    await ctx.send(build_stats_table(ctx, trades, "Lifetime Stats"))

@bot.command()
async def dailystats(ctx):
    user_id = str(ctx.author.id)
    trades = filter_trades(trade_data.get(user_id, {}).get("trades", []), "daily")
    if not trades:
        await ctx.send("📊 No trades in the last 24h, huh?")
        return
    await ctx.send(build_stats_table(ctx, trades, "Daily Stats"))

@bot.command()
async def weeklystats(ctx):
    user_id = str(ctx.author.id)
    trades = filter_trades(trade_data.get(user_id, {}).get("trades", []), "weekly")
    if not trades:
        await ctx.send("📊 Quiet week? No trades yet!")
        return
    await ctx.send(build_stats_table(ctx, trades, "Weekly Stats"))

@bot.command()
async def monthlystats(ctx):
    user_id = str(ctx.author.id)
    trades = filter_trades(trade_data.get(user_id, {}).get("trades", []), "monthly")
    if not trades:
        await ctx.send("📊 No trades this month, time to shine!")
        return
    await ctx.send(build_stats_table(ctx, trades, "Monthly Stats"))

@bot.command()
async def leaderboard(ctx):
    scores = []
    for uid, udata in trade_data.items():
        total_rr = sum(t["rr"] for t in udata["trades"])
        scores.append((uid, total_rr))
    scores.sort(key=lambda x: x[1], reverse=True)
    text = "🏆 **Leaderboard of Legends!**\n"
    for i, (uid, rr) in enumerate(scores[:5], 1):
        user = await bot.fetch_user(int(uid))
        trophy = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🎖️"
        text += f"{i}. {trophy} {user.name} — {rr:+.2f} RR\n"
    await ctx.send(text)

@bot.command()
async def removelasttrade(ctx):
    user_id = str(ctx.author.id)
    trades = trade_data.get(user_id, {}).get("trades", [])
    if not trades:
        await ctx.send("❌ No trades to zap! Log one first.")
        return
    last = trades.pop()
    save_data(trade_data)
    await ctx.send(f"⏪ Trade removed! {last['pair']} {last['dir']} RR {last['rr']:+.2f}\n✓ Data saved.")

@bot.command()
async def besttrade(ctx):
    user_id = str(ctx.author.id)
    trades = trade_data.get(user_id, {}).get("trades", [])
    if not trades:
        await ctx.send("❌ No trades to brag about!")
        return
    best = max(trades, key=lambda t: t["rr"])
    await ctx.send(f"🌟 **GLORIOUS VICTORY!** {best['pair']} {best['dir']} RR {best['rr']:+.2f}")

@bot.command()
async def worsttrade(ctx):
    user_id = str(ctx.author.id)
    trades = trade_data.get(user_id, {}).get("trades", [])
    if not trades:
        await ctx.send("❌ No trades to mourn!")
        return
    worst = min(trades, key=lambda t: t["rr"])
    await ctx.send(f"💀 **OUCH! EPIC FAIL!** {worst['pair']} {worst['dir']} RR {worst['rr']:+.2f}")

@bot.command()
async def streak(ctx):
    user_id = str(ctx.author.id)
    trades = trade_data.get(user_id, {}).get("trades", [])
    if not trades:
        await ctx.send("📊 No trades for a streak!")
        return
    streak = 0
    for t in reversed(trades):
        if t["result"] == "tp": streak += 1
        else: break
    await ctx.send(f"🔥 **WIN STREAK ALERT!** {streak} in a row!")

@bot.command()
async def resetstats(ctx, arg=None):
    user_id = str(ctx.author.id)
    if arg == "all":
        if ctx.author.guild_permissions.administrator:
            await ctx.send("⚠️ Confirm reset all with `!resetstats confirm` or `/resetstats confirm`\n✓ Admin check passed.")
            return
        else:
            await ctx.send("❌ Only admins can reset all stats!")
            return
    if arg == "confirm" and ctx.author.guild_permissions.administrator:
        trade_data.clear()
        save_data(trade_data)
        await ctx.send("✅ All stats wiped! Fresh start for everyone.\n✓ Data saved.")
        return
    trade_data[user_id] = {"trades": []}
    save_data(trade_data)
    await ctx.send("✅ Your stats are reset! New beginning.\n✓ Data saved.")

@bot.command()
async def calendar(ctx):
    user_id = str(ctx.author.id)
    trades = trade_data.get(user_id, {}).get("trades", [])
    if not trades:
        await ctx.send("📅 No trade history to tell!")
        return
    trades_by_day = {}
    for t in trades:
        d = datetime.fromisoformat(t["timestamp"]).strftime("%Y-%m-%d")
        trades_by_day.setdefault(d, []).append(t)
    text = "📖 **Trade Adventure Log**\n"
    for d, ts in trades_by_day.items():
        total_rr = sum(x["rr"] for x in ts)
        text += f"On {d}, you rocked {len(ts)} trades with a total RR of {total_rr:+.2f}!\n"
    await ctx.send(text)

# ===================== RUN =====================
if __name__ == "__main__":
    if not TOKEN:
        print("❌ Set DISCORD_TOKEN in Replit Secrets.")
    else:
        keep_alive()
        bot.run(TOKEN)