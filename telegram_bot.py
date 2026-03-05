import asyncio
import json
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List
import aiohttp
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, MarketOrderArgs, OrderType, OpenOrderParams, BalanceAllowanceParams, \
    AssetType
from py_clob_client.order_builder.constants import BUY, SELL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.constants import ParseMode
import logging

logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.ERROR)
logging.getLogger("telegram.ext").setLevel(logging.ERROR)
logging.getLogger("asyncio").setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

GAMMA_API = "https://gamma-api.polymarket.com"
DATA_API = "https://data-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

user_states: Dict[int, Dict[str, Any]] = {}

class UserState:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.auth_client = None
        self.yes_token_id = None
        self.no_token_id = None
        self.selected_market = None
        self.selected_outcome = None
        self.wallet_address = None
        self.current_positions = []
        self.last_message_id = None
        self.waiting_for_input = False
        self.input_type = None
        self.temp_data = {}
        self.markets_cache = []

def get_user_state(user_id: int) -> UserState:
    if user_id not in user_states:
        user_states[user_id] = UserState(user_id)
    return user_states[user_id]

async def start_authentication(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    state.waiting_for_input = True
    state.input_type = "wallet_address"
    text = (
        "🔐 <b>Authentication Setup</b>\n\n"
        "Please send your <b>wallet address</b> (one message):"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(context, user_id, text, reply_markup)

async def delete_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message:
            await update.message.delete()
    except Exception as e:
        logger.error(f"Error deleting message: {e}")

async def update_bot_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str,
                             reply_markup: Optional[InlineKeyboardMarkup] = None,
                             message_id: Optional[int] = None,
                             parse_mode: str = ParseMode.HTML):
    state = get_user_state(chat_id)
    try:
        if state.last_message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=state.last_message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        else:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            state.last_message_id = msg.message_id
    except Exception as e:
        if "message is not modified" not in str(e):
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
            state.last_message_id = msg.message_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    state.last_message_id = None
    welcome_text = (
        "⚠️ <b>WARNING</b> ⚠️\n\n"
        "This is a trading bot for Polymarket.\n"
        "1. Your private keys are stored in the bot session, making them impossible to steal or lose.\n"
        "2. Fast and secure.\n"
        "3. All PolyPlat bots do not guarantee 100% profit!\n\n"
        "Click 'I AGREE' to continue"
    )
    keyboard = [
        [InlineKeyboardButton("✅ I AGREE", callback_data="agree")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(context, user_id, welcome_text, reply_markup)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    state.waiting_for_input = False
    status_text = await get_status_text(state)
    keyboard = [
        [InlineKeyboardButton("🔐 Authenticate", callback_data="authenticate")],
        [InlineKeyboardButton("📊 Browse Markets", callback_data="browse_markets")],
        [InlineKeyboardButton("📈 Market Statistics", callback_data="market_stats")],
        [InlineKeyboardButton("🎯 Select Outcome", callback_data="select_outcome")],
        [InlineKeyboardButton("📈 Analyze Order Book", callback_data="analyze_order_book")],
        [InlineKeyboardButton("💰 Check Balance", callback_data="check_balance")],
        [InlineKeyboardButton("⚡ Place Market Order", callback_data="market_order")],
        [InlineKeyboardButton("📝 Place Limit Order", callback_data="limit_order")],
        [InlineKeyboardButton("📋 View Open Orders", callback_data="view_orders")],
        [InlineKeyboardButton("❌ Cancel Orders", callback_data="cancel_orders")],
        [InlineKeyboardButton("📊 Track Price", callback_data="track_price")],
        [InlineKeyboardButton("📊 My Positions", callback_data="my_positions")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(context, user_id, status_text, reply_markup)

async def get_status_text(state: UserState) -> str:
    text = "📊 <b>CURRENT STATUS</b>\n"
    text += "═" * 38 + "\n"
    if state.selected_market:
        question = state.selected_market.get('question', 'Unknown')
        if len(question) > 60:
            question = question[:57] + "..."
        text += f"<b>Market:</b> {question}\n"
    else:
        text += "<b>Market:</b> None\n"
    if state.selected_outcome:
        text += f"<b>Outcome:</b> {state.selected_outcome['name']}\n"
    else:
        text += "<b>Outcome:</b> None\n"
    text += f"<b>Authenticated:</b> {'✅ Yes' if state.auth_client else '❌ No'}\n"
    if state.auth_client and state.wallet_address:
        text += f"<b>Wallet:</b> {state.wallet_address[:10]}...\n"
    text += "═" * 30 + "\n"
    return text

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    callback_data = query.data

    if callback_data == "agree":
        await show_main_menu(update, context, user_id)
    elif callback_data == "cancel":
        await update_bot_message(context, user_id, "Operation cancelled. Use /start to begin again.")
    elif callback_data == "authenticate":
        await start_authentication(update, context, user_id)
    elif callback_data == "browse_markets":
        await show_market_browse_options(update, context, user_id)
    elif callback_data == "market_stats":
        if state.selected_market:
            await show_market_statistics(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please select a market first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "select_outcome":
        if state.selected_market:
            await select_outcome_for_market(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please select a market first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "analyze_order_book":
        if state.selected_outcome:
            await analyze_order_book(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please select an outcome first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "check_balance":
        if state.auth_client:
            await check_balance(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please authenticate first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "market_order":
        if state.auth_client and state.selected_outcome:
            await place_market_order_menu(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please authenticate and select outcome first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "limit_order":
        if state.auth_client and state.selected_outcome:
            await place_limit_order_menu(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please authenticate and select outcome first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "view_orders":
        if state.auth_client:
            await view_open_orders(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please authenticate first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "cancel_orders":
        if state.auth_client:
            await cancel_orders_menu(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please authenticate first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "track_price":
        if state.selected_outcome:
            await track_price_menu(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please select an outcome first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "my_positions":
        if state.auth_client:
            await get_my_positions(update, context, user_id)
        else:
            await update_bot_message(context, user_id, "❌ Please authenticate first!")
            await asyncio.sleep(2)
            await show_main_menu(update, context, user_id)
    elif callback_data == "refresh":
        await show_main_menu(update, context, user_id)
    elif callback_data == "show_top_markets":
        await fetch_top_markets(update, context, user_id, search_mode=False)
    elif callback_data == "search_markets":
        await start_market_search(update, context, user_id)
    elif callback_data.startswith("market_"):
        await handle_market_selection(update, context, user_id, callback_data)
    elif callback_data.startswith("outcome_"):
        await handle_outcome_selection(update, context, user_id, callback_data)
    elif callback_data == "order_side_buy":
        await handle_order_side(update, context, user_id, "BUY")
    elif callback_data == "order_side_sell":
        await handle_order_side(update, context, user_id, "SELL")
    elif callback_data == "order_amount_usd":
        await handle_order_amount_type(update, context, user_id, "usd")
    elif callback_data == "order_amount_shares":
        await handle_order_amount_type(update, context, user_id, "shares")
    elif callback_data == "limit_order_side_buy":
        await handle_limit_order_side(update, context, user_id, "BUY")
    elif callback_data == "limit_order_side_sell":
        await handle_limit_order_side(update, context, user_id, "SELL")
    elif callback_data.startswith("cancel_"):
        option = callback_data.split("_")[1]
        if option == "all":
            await confirm_cancel_all(update, context, user_id)
        elif option == "current":
            await confirm_cancel_current(update, context, user_id)
    elif callback_data == "confirm_market_order":
        await place_market_order_execute(update, context, user_id)
    elif callback_data == "confirm_limit_order":
        await place_limit_order_execute(update, context, user_id)
    elif callback_data == "confirm_cancel_all":
        await execute_cancel_all(update, context, user_id)
    elif callback_data == "confirm_cancel_current":
        await execute_cancel_current(update, context, user_id)
    elif callback_data.startswith("track_"):
        duration_str = callback_data.split("_")[1]
        duration_map = {"30": 30, "60": 60, "120": 120}
        duration = duration_map.get(duration_str, 30)
        await start_price_tracking(update, context, user_id, duration)
    elif callback_data == "back_to_main":
        await show_main_menu(update, context, user_id)

async def show_market_browse_options(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    keyboard = [
        [InlineKeyboardButton("📈 Top 20 Markets by Volume", callback_data="show_top_markets")],
        [InlineKeyboardButton("🔍 Search by Keyword", callback_data="search_markets")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        "📊 <b>Browse Markets</b>\n\n"
        "Select browsing option:",
        reply_markup
    )

async def start_market_search(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    state.waiting_for_input = True
    state.input_type = "market_search"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="browse_markets")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        "🔍 <b>Search Markets</b>\n\n"
        "Enter keyword or phrase to search:\n\n"
        "<i>Examples: 'bitcoin', 'election', 'sports'</i>",
        reply_markup
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = get_user_state(user_id)
    text = update.message.text.strip()
    try:
        await update.message.delete()
    except:
        pass
    if not state.waiting_for_input:
        return

    if state.input_type == "market_search":
        state.waiting_for_input = False
        await fetch_top_markets(update, context, user_id, search_mode=True, search_term=text)
    elif state.input_type == "wallet_address":
        state.wallet_address = text
        state.temp_data['wallet_address'] = text
        state.input_type = "private_key"
        await update_bot_message(
            context, user_id,
            "✅ Wallet address saved.\n\n"
            "Now send your <b>private key</b> (one message):",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]])
        )
    elif state.input_type == "private_key":
        private_key = text
        state.input_type = None
        state.waiting_for_input = False
        await update_bot_message(
            context, user_id,
            "🔄 Authenticating...",
            InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Please wait...", callback_data="wait")]])
        )
        try:
            auth_client = ClobClient(
                CLOB_API,
                key=private_key,
                chain_id=137,
                signature_type=1,
                funder=state.wallet_address
            )
            creds = auth_client.derive_api_key()
            auth_client.set_api_creds(creds)
            state.auth_client = auth_client
            await update_bot_message(
                context, user_id,
                "✅ <b>Authentication successful!</b>\n\n"
                f"Wallet: {state.wallet_address[:10]}...\n"
                "API credentials set.",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            await update_bot_message(
                context, user_id,
                f"❌ <b>Authentication failed:</b>\n{str(e)[:200]}",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
    elif state.input_type == "market_order_amount":
        await handle_market_order_amount(update, context, user_id, text)
    elif state.input_type == "limit_order_price":
        await handle_limit_order_price(update, context, user_id, text)
    elif state.input_type == "limit_order_size":
        await handle_limit_order_size(update, context, user_id, text)

async def fetch_top_markets(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                            search_mode: bool = False, search_term: str = ""):
    state = get_user_state(user_id)
    if search_mode and search_term:
        await update_bot_message(
            context, user_id,
            f"🔍 Searching markets for: '{search_term}'...",
            InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
        )
    else:
        await update_bot_message(
            context, user_id,
            "🔄 Fetching top markets...",
            InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
        )
    try:
        async with aiohttp.ClientSession() as session:
            limit = 350 if search_mode else 20
            url = f"{GAMMA_API}/markets"
            params = {
                "limit": limit,
                "active": "true",
                "closed": "false",
                "order": "volume24hr",
                "ascending": "false"
            }
            logger.info(f"Fetching markets from {url} with params: {params}")
            async with session.get(url, params=params, timeout=15) as response:
                if response.status != 200:
                    logger.error(f"API error: {response.status}")
                    await update_bot_message(
                        context, user_id,
                        f"❌ API Error: {response.status}",
                        InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
                    )
                    return
                all_markets = await response.json()
                logger.info(f"Received {len(all_markets)} markets")
        if not all_markets:
            await update_bot_message(
                context, user_id,
                "❌ No markets found",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
            return
        if search_mode and search_term:
            search_term_lower = search_term.lower()
            filtered_markets = []
            for m in all_markets:
                question = m.get('question', '').lower()
                description = m.get('description', '').lower()
                if (search_term_lower in question or
                        search_term_lower in description):
                    filtered_markets.append(m)
            if not filtered_markets:
                await update_bot_message(
                    context, user_id,
                    f"❌ No markets found with: '{search_term}'\n\n"
                    "Showing top 20 markets instead...",
                    InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
                )
                markets = sorted(all_markets,
                                 key=lambda x: x.get('volume24hr', 0),
                                 reverse=True)[:20]
            else:
                markets = sorted(filtered_markets,
                                 key=lambda x: x.get('volume24hr', 0),
                                 reverse=True)[:20]
                logger.info(f"Found {len(filtered_markets)} markets, showing top {len(markets)}")
                if len(markets) > 0:
                    await update_bot_message(
                        context, user_id,
                        f"✅ Found {len(filtered_markets)} markets with '{search_term}', showing top {len(markets)}",
                        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
                    )
        else:
            markets = all_markets[:20]
        state.markets_cache = markets
        keyboard = []
        for i, m in enumerate(markets[:20], 1):
            question = m.get('question', 'Unknown Market')
            if len(question) > 40:
                question = question[:37] + "..."
            volume = m.get('volume24hr', 0)
            volume_str = f"{volume:,.0f}" if volume >= 1000 else f"{volume:.0f}"
            end_date_str = m.get('endDate', 'N/A')
            days_left = 'N/A'
            if end_date_str and end_date_str != 'N/A':
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                    now = datetime.now()
                    days_left = max(0, (end_date - now).days)
                    if days_left < 7:
                        days_indicator = "⏰"
                    else:
                        days_indicator = "📅"
                except:
                    days_indicator = ""
            else:
                days_indicator = ""
            button_text = f"{i}. ${volume_str} - {question} {days_indicator}"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"market_{i - 1}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="browse_markets")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        if search_mode and search_term:
            title = f"🔍 <b>Search Results for '{search_term}'</b>\n\n"
        else:
            title = "📊 <b>Top Markets by Volume</b>\n\n"
        title += f"Showing {len(markets)} markets\n\nSelect a market:"
        await update_bot_message(context, user_id, title, reply_markup)
    except Exception as e:
        logger.error(f"Error fetching markets: {e}", exc_info=True)
        await update_bot_message(
            context, user_id,
            f"❌ Error fetching markets: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def handle_market_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, callback_data: str):
    state = get_user_state(user_id)
    try:
        market_index = int(callback_data.split("_")[1])
        if 0 <= market_index < len(state.markets_cache):
            state.selected_market = state.markets_cache[market_index]
            state.selected_outcome = None
            clob_token_ids = state.selected_market.get('clobTokenIds')
            if clob_token_ids:
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                    if len(clob_token_ids) >= 2:
                        state.yes_token_id = clob_token_ids[0]
                        state.no_token_id = clob_token_ids[1]
                        outcomes_data = state.selected_market.get('outcomes')
                        outcomes_list = []
                        if outcomes_data:
                            if isinstance(outcomes_data, str):
                                try:
                                    outcomes_list = json.loads(outcomes_data)
                                except:
                                    outcomes_list = [o.strip() for o in outcomes_data.split(',')]
                            elif isinstance(outcomes_data, list):
                                outcomes_list = outcomes_data
                        first_outcome_name = "YES"
                        if outcomes_list and len(outcomes_list) > 0:
                            first_outcome_name = outcomes_list[0]
                        state.selected_outcome = {
                            'name': first_outcome_name,
                            'token_id': state.yes_token_id,
                            'index': 0
                        }
                except:
                    pass
            question = state.selected_market.get('question', 'Unknown Market')
            if len(question) > 60:
                question = question[:57] + "..."
            volume = state.selected_market.get('volume24hr', 0)
            liquidity = state.selected_market.get('liquidityNum', 0)
            end_date_str = state.selected_market.get('endDate', 'N/A')
            end_date_info = ""
            if end_date_str and end_date_str != 'N/A':
                try:
                    end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                    end_date_info = f"⏰ Ends: {end_date.strftime('%d %b %Y, %H:%M UTC')}\n"
                except:
                    end_date_info = f"⏰ Ends: {end_date_str}\n"
            await update_bot_message(
                context, user_id,
                f"✅ <b>Market Selected</b>\n\n"
                f"<b>{question}</b>\n\n"
                f"📊 Volume 24h: ${volume:,.0f}\n"
                f"💰 Liquidity: ${liquidity:,.0f}\n"
                f"{end_date_info}\n"
                f"Automatically selected <b>{state.selected_outcome['name']}</b> outcome.\n"
                f"Use 'Select Outcome' to change.",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
    except Exception as e:
        logger.error(f"Error selecting market: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error selecting market: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )


async def show_market_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    if not state.selected_market:
        await update_bot_message(
            context, user_id,
            "❌ No market selected",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
        return
    await update_bot_message(
        context, user_id,
        "🔄 Fetching market statistics...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
    )
    try:
        market = state.selected_market
        question = market.get('question', 'Unknown Market')
        volume_24hr = market.get('volume24hr', 0)
        liquidity = market.get('liquidityNum', 0)
        open_interest = market.get('openInterestNum', 0)
        start_date_str = market.get('startDate', 'N/A')
        end_date_str = market.get('endDate', 'N/A')
        outcomes_data = market.get('outcomes')
        outcomes_list = []
        if outcomes_data:
            if isinstance(outcomes_data, str):
                try:
                    outcomes_list = json.loads(outcomes_data)
                except:
                    outcomes_list = [o.strip() for o in outcomes_data.split(',')]
            elif isinstance(outcomes_data, list):
                outcomes_list = outcomes_data
        clob_token_ids_str = market.get('clobTokenIds')
        clob_token_ids = []
        token_prices = []
        if clob_token_ids_str:
            try:
                clob_token_ids = json.loads(clob_token_ids_str)
                client = ClobClient(CLOB_API)
                for token_id in clob_token_ids[:2]:
                    try:
                        mid = client.get_midpoint(token_id)
                        price = float(mid['mid'])
                        token_prices.append(price)
                    except:
                        token_prices.append(0)
            except:
                pass
        start_date_formatted = "N/A"
        if start_date_str and start_date_str != 'N/A':
            try:
                start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))
                start_date_formatted = start_date.strftime('%d %b %Y, %H:%M UTC')
            except:
                start_date_formatted = start_date_str
        end_date_formatted = "N/A"
        if end_date_str and end_date_str != 'N/A':
            try:
                end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))
                end_date_formatted = end_date.strftime('%d %b %Y, %H:%M UTC')
            except:
                end_date_formatted = end_date_str
        text = f"📊 <b>Market Statistics</b>\n\n"
        text += f"<b>{question}</b>\n\n"
        text += f"<b>Start Date:</b> {start_date_formatted}\n"
        text += f"<b>End Date:</b> {end_date_formatted}\n\n"
        text += f"<b>Financial Data:</b>\n"
        text += f"  • 24h Volume: <b>${volume_24hr:,.2f}</b>\n"
        text += f"  • Liquidity: <b>${liquidity:,.2f}</b>\n"
        text += f"  • Open Interest: <b>${open_interest:,.2f}</b>\n\n"
        if outcomes_list:
            text += f"<b>Outcomes:</b>\n"
            for i, outcome in enumerate(outcomes_list):
                price_info = ""
                if i < len(token_prices) and token_prices[i] > 0:
                    price_info = f" - <b>${token_prices[i]:.4f}</b>"
                text += f"  {i+1}. {outcome}{price_info}\n"
        keyboard = [[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update_bot_message(context, user_id, text, reply_markup)
    except Exception as e:
        logger.error(f"Error showing market statistics: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error showing market statistics: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def select_outcome_for_market(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    if not state.selected_market:
        await update_bot_message(context, user_id, "❌ Please select a market first!")
        await asyncio.sleep(2)
        await show_main_menu(update, context, user_id)
        return
    outcomes_data = state.selected_market.get('outcomes')
    outcomes_list = []
    if outcomes_data:
        if isinstance(outcomes_data, str):
            try:
                outcomes_list = json.loads(outcomes_data)
            except:
                outcomes_list = [o.strip() for o in outcomes_data.split(',')]
        elif isinstance(outcomes_data, list):
            outcomes_list = outcomes_data
    is_binary_market = False
    if len(outcomes_list) == 2:
        outcomes_lower = [o.lower() for o in outcomes_list]
        if 'yes' in outcomes_lower or 'no' in outcomes_lower:
            is_binary_market = True
    keyboard = []
    if is_binary_market or len(outcomes_list) <= 2:
        outcomes_lower = [o.lower() for o in outcomes_list]
        yes_outcome = None
        no_outcome = None
        for i, outcome in enumerate(outcomes_list):
            if 'yes' in outcome.lower():
                yes_outcome = outcome
                yes_index = i
            elif 'no' in outcome.lower():
                no_outcome = outcome
                no_index = i
        if not yes_outcome or not no_outcome:
            yes_outcome = outcomes_list[0] if len(outcomes_list) > 0 else "YES"
            no_outcome = outcomes_list[1] if len(outcomes_list) > 1 else "NO"
            yes_index = 0
            no_index = 1
        keyboard.append([InlineKeyboardButton(f"🟢 {yes_outcome}", callback_data=f"outcome_{yes_index}")])
        keyboard.append([InlineKeyboardButton(f"🔴 {no_outcome}", callback_data=f"outcome_{no_index}")])
    else:
        for i, outcome in enumerate(outcomes_list):
            display_name = outcome
            if any(sport_word in outcome.lower() for sport_word in ['win', 'lose', 'victory', 'defeat', 'vs']):
                if i == 0:
                    display_name = f"🏆 {outcome}"
                else:
                    display_name = f"⚽ {outcome}"
            keyboard.append([InlineKeyboardButton(display_name, callback_data=f"outcome_{i}")])
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    question = state.selected_market.get('question', 'Unknown Market')
    if len(question) > 60:
        question = question[:57] + "..."
    await update_bot_message(
        context, user_id,
        f"🎯 <b>Select Outcome</b>\n\n"
        f"Market: {question}\n\n"
        f"Available outcomes:",
        reply_markup
    )

async def handle_outcome_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int,
                                   callback_data: str):
    state = get_user_state(user_id)
    try:
        outcome_type = callback_data.split("_")[1]
        idx = int(outcome_type) if outcome_type.isdigit() else None
        outcomes_data = state.selected_market.get('outcomes')
        outcomes_list = []
        if outcomes_data:
            if isinstance(outcomes_data, str):
                try:
                    outcomes_list = json.loads(outcomes_data)
                except:
                    outcomes_list = [o.strip() for o in outcomes_data.split(',')]
            elif isinstance(outcomes_data, list):
                outcomes_list = outcomes_data
        if idx is not None and 0 <= idx < len(outcomes_list):
            outcome_name = outcomes_list[idx]
            clob_token_ids_str = state.selected_market.get('clobTokenIds')
            clob_token_ids = []
            if clob_token_ids_str:
                try:
                    clob_token_ids = json.loads(clob_token_ids_str)
                except:
                    pass
            token_id = clob_token_ids[idx] if idx < len(clob_token_ids) else None
            state.selected_outcome = {
                'name': outcome_name,
                'token_id': token_id,
                'index': idx
            }
            if idx == 0 and len(clob_token_ids) >= 1:
                state.yes_token_id = clob_token_ids[0]
            elif idx == 1 and len(clob_token_ids) >= 2:
                state.no_token_id = clob_token_ids[1]
            emoji = "✅"
            if outcome_name.lower() == 'no' or 'lose' in outcome_name.lower() or 'defeat' in outcome_name.lower():
                emoji = "❌"
            elif 'win' in outcome_name.lower() or 'victory' in outcome_name.lower():
                emoji = "🏆"
            await update_bot_message(
                context, user_id,
                f"{emoji} Selected outcome: <b>{outcome_name}</b>",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
        else:
            if outcome_type == "yes":
                if state.yes_token_id:
                    state.selected_outcome = {
                        'name': 'YES',
                        'token_id': state.yes_token_id,
                        'index': 0
                    }
                    outcome_name = "YES"
                else:
                    await update_bot_message(
                        context, user_id,
                        "❌ YES token ID not available",
                        InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
                    )
                    return
            elif outcome_type == "no":
                if state.no_token_id:
                    state.selected_outcome = {
                        'name': 'NO',
                        'token_id': state.no_token_id,
                        'index': 1
                    }
                    outcome_name = "NO"
                else:
                    await update_bot_message(
                        context, user_id,
                        "❌ NO token ID not available",
                        InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
                    )
                    return
            await update_bot_message(
                context, user_id,
                f"✅ Selected outcome: <b>{outcome_name}</b>",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
    except Exception as e:
        logger.error(f"Error selecting outcome: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error selecting outcome: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def analyze_order_book(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    if not state.selected_outcome or not state.selected_outcome.get('token_id'):
        await update_bot_message(
            context, user_id,
            "❌ Invalid outcome or token ID",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
        return
    await update_bot_message(
        context, user_id,
        "🔄 Analyzing order book...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
    )
    try:
        client = ClobClient(CLOB_API)
        token_id = state.selected_outcome['token_id']
        book = client.get_order_book(token_id)
        sorted_bids = sorted(book.bids, key=lambda x: float(x.price), reverse=True)
        sorted_asks = sorted(book.asks, key=lambda x: float(x.price), reverse=False)
        text = f"📈 <b>Order Book Analysis</b>\n\n"
        text += f"Outcome: <b>{state.selected_outcome['name']}</b>\n\n"
        text += "<b>Top 5 Asks (sell orders):</b>\n"
        for ask in sorted_asks[:5]:
            text += f"  Price: ${float(ask.price):.4f} | Size: {float(ask.size):.2f}\n"
        text += "\n<b>Top 5 Bids (buy orders):</b>\n"
        for bid in sorted_bids[:5]:
            text += f"  Price: ${float(bid.price):.4f} | Size: {float(bid.size):.2f}\n"
        mid = client.get_midpoint(token_id)
        buy_price = client.get_price(token_id, side="BUY")
        sell_price = client.get_price(token_id, side="SELL")
        spread = client.get_spread(token_id)
        text += "\n<b>Market Summary:</b>\n"
        text += f"   Midpoint: ${float(mid['mid']):.4f}\n"
        text += f"   Best ask: ${float(buy_price['price']):.4f}\n"
        text += f"   Best bid: ${float(sell_price['price']):.4f}\n"
        text += f"   Spread: ${float(spread['spread']):.4f}\n"
        keyboard = [[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update_bot_message(context, user_id, text, reply_markup)
    except Exception as e:
        logger.error(f"Error analyzing order book: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error analyzing order book: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def check_balance(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    await update_bot_message(
        context, user_id,
        "🔄 Checking balance...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
    )
    try:
        balance = state.auth_client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        usdc_balance = int(balance['balance']) / 1e6
        await update_bot_message(
            context, user_id,
            f"💰 <b>USDC Balance: ${usdc_balance:.2f}</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
    except Exception as e:
        logger.error(f"Error checking balance: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error checking balance: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def place_market_order_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    keyboard = [
        [InlineKeyboardButton("📈 BUY", callback_data="order_side_buy")],
        [InlineKeyboardButton("📉 SELL", callback_data="order_side_sell")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        f"⚡ <b>Place Market Order</b>\n\n"
        f"Outcome: <b>{state.selected_outcome['name']}</b>\n\n"
        "Select side:",
        reply_markup
    )

async def handle_order_side(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, side: str):
    state = get_user_state(user_id)
    state.temp_data['order_side'] = side
    keyboard = [
        [InlineKeyboardButton("💵 USD Amount", callback_data="order_amount_usd")],
        [InlineKeyboardButton("📊 Number of Shares", callback_data="order_amount_shares")],
        [InlineKeyboardButton("🔙 Back", callback_data="market_order")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        f"⚡ <b>Place {side} Market Order</b>\n\n"
        f"Outcome: <b>{state.selected_outcome['name']}</b>\n\n"
        "Enter amount as:",
        reply_markup
    )

async def handle_order_amount_type(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, amount_type: str):
    state = get_user_state(user_id)
    state.temp_data['amount_type'] = amount_type
    state.waiting_for_input = True
    state.input_type = "market_order_amount"
    try:
        client = ClobClient(CLOB_API)
        if state.temp_data['order_side'] == "BUY":
            price_info = client.get_price(state.selected_outcome['token_id'], side="SELL")
            current_price = float(price_info['price'])
        else:
            price_info = client.get_price(state.selected_outcome['token_id'], side="BUY")
            current_price = float(price_info['price'])
        if amount_type == "usd":
            prompt = f"Enter <b>USD amount</b> to {'spend' if state.temp_data['order_side'] == 'BUY' else 'receive'}:\n"
            prompt += f"<i>Current price: ${current_price:.4f}</i>\n"
            prompt += f"<i>$1.00 ≈ {1 / current_price:.2f} shares</i>"
        else:
            prompt = f"Enter <b>number of shares</b>:\n"
            prompt += f"<i>Current price: ${current_price:.4f}</i>\n"
            prompt += f"<i>1 share ≈ ${current_price:.4f}</i>"
    except:
        if amount_type == "usd":
            prompt = f"Enter <b>USD amount</b> to {'spend' if state.temp_data['order_side'] == 'BUY' else 'receive'}:"
        else:
            prompt = "Enter <b>number of shares</b>:"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data=f"order_side_{state.temp_data['order_side'].lower()}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        f"⚡ <b>Place {state.temp_data['order_side']} Market Order</b>\n\n"
        f"{prompt}",
        reply_markup
    )

async def handle_market_order_amount(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str):
    state = get_user_state(user_id)
    try:
        amount = float(text)
        if amount <= 0:
            await update_bot_message(
                context, user_id,
                "❌ Amount must be greater than 0.",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back",
                                           callback_data=f"order_side_{state.temp_data['order_side'].lower()}")]])
            )
            return
        state.temp_data['amount'] = amount
        client = ClobClient(CLOB_API)
        if state.temp_data['order_side'] == "BUY":
            price_info = client.get_price(state.selected_outcome['token_id'], side="SELL")
            current_price = float(price_info['price'])
        else:
            price_info = client.get_price(state.selected_outcome['token_id'], side="BUY")
            current_price = float(price_info['price'])
        if current_price <= 0:
            await update_bot_message(
                context, user_id,
                "❌ Invalid price. Cannot calculate order size.",
                InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔙 Back",
                                           callback_data=f"order_side_{state.temp_data['order_side'].lower()}")]])
            )
            state.waiting_for_input = False
            return
        if state.temp_data['amount_type'] == "usd":
            usd_amount = amount
            shares_amount = usd_amount / current_price
            total_cost = shares_amount * current_price
        else:
            shares_amount = amount
            total_cost = shares_amount * current_price
            usd_amount = total_cost
        if state.temp_data['order_side'] == "BUY":
            balance = state.auth_client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            usdc_balance = int(balance['balance']) / 1e6
            if total_cost > usdc_balance:
                await update_bot_message(
                    context, user_id,
                    f"❌ <b>Insufficient balance!</b>\n\n"
                    f"Available: <b>${usdc_balance:.2f}</b>\n"
                    f"Needed: <b>${total_cost:.2f}</b>\n\n"
                    f"Difference: <b>${total_cost - usdc_balance:.2f}</b>",
                    InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
                )
                state.waiting_for_input = False
                return
        state.temp_data['calculated_shares'] = shares_amount
        state.temp_data['calculated_usd'] = total_cost
        state.temp_data['current_price'] = current_price
        keyboard = [
            [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_market_order")],
            [InlineKeyboardButton("❌ Cancel", callback_data="market_order")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        order_type = "Buy" if state.temp_data['order_side'] == "BUY" else "Sell"
        await update_bot_message(
            context, user_id,
            f"⚡ <b>Order Confirmation</b>\n\n"
            f"Type: <b>Market {order_type}</b>\n"
            f"Outcome: <b>{state.selected_outcome['name']}</b>\n"
            f"Price: <b>${current_price:.4f}</b>\n"
            f"Shares: <b>{shares_amount:.4f}</b>\n"
            f"Total: <b>${total_cost:.4f}</b>\n"
            f"To win: <b>${usd_amount/current_price:.4f}</b>\n\n"
            f"<i>Note: For market orders, actual execution may vary slightly.</i>\n\n"
            f"Click Confirm to execute:",
            reply_markup
        )
        state.waiting_for_input = False
    except ValueError:
        await update_bot_message(
            context, user_id,
            "❌ Invalid amount. Please enter a valid number.",
            InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data=f"order_side_{state.temp_data['order_side'].lower()}")]])
        )
    except Exception as e:
        logger.error(f"Error processing order amount: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
        state.waiting_for_input = False

async def place_market_order_execute(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    await update_bot_message(
        context, user_id,
        "🔄 Executing market order...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Please wait...", callback_data="wait")]])
    )
    try:
        if state.temp_data['order_side'] == "BUY":
            order_amount = state.temp_data['calculated_usd']
        else:
            order_amount = state.temp_data['calculated_shares']
        market_order = MarketOrderArgs(
            token_id=state.selected_outcome['token_id'],
            amount=order_amount,
            side=BUY if state.temp_data['order_side'] == "BUY" else SELL,
            order_type=OrderType.FOK
        )
        signed_market_order = state.auth_client.create_market_order(market_order)
        response = state.auth_client.post_order(signed_market_order, OrderType.FOK)
        order_type = "Buy" if state.temp_data['order_side'] == "BUY" else "Sell"
        await update_bot_message(
            context, user_id,
            f"✅ <b>Market Order Executed!</b>\n\n"
            f"Type: <b>Market {order_type}</b>\n"
            f"Outcome: <b>{state.selected_outcome['name']}</b>\n"
            f"Shares: <b>{state.temp_data['calculated_shares']:.4f}</b>\n"
            f"Estimated {'Cost' if order_type == 'Buy' else 'Proceeds'}: <b>${state.temp_data['calculated_usd']:.4f}</b>\n"
            f"Price: <b>${state.temp_data['current_price']:.4f}</b>\n\n"
            f"<i>Note: Actual execution may vary slightly from estimate.</i>",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
    except Exception as e:
        logger.error(f"Error executing market order: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error executing market order: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def place_limit_order_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    keyboard = [
        [InlineKeyboardButton("📈 BUY", callback_data="limit_order_side_buy")],
        [InlineKeyboardButton("📉 SELL", callback_data="limit_order_side_sell")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        f"📝 <b>Place Limit Order</b>\n\n"
        f"Outcome: <b>{state.selected_outcome['name']}</b>\n\n"
        "Select side:",
        reply_markup
    )

async def handle_limit_order_side(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, side: str):
    state = get_user_state(user_id)
    state.temp_data['limit_order_side'] = side
    state.waiting_for_input = True
    state.input_type = "limit_order_price"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="limit_order")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        f"📝 <b>Place {side} Limit Order</b>\n\n"
        f"Outcome: <b>{state.selected_outcome['name']}</b>\n\n"
        "Enter <b>price per share</b>:",
        reply_markup
    )

async def handle_limit_order_price(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str):
    state = get_user_state(user_id)
    try:
        price = float(text)
        if price <= 0 or price > 1.0:
            await update_bot_message(
                context, user_id,
                "❌ Invalid price. Price must be between $0.0001 and $1.0000",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                            callback_data=f"limit_order_side_{state.temp_data['limit_order_side'].lower()}")]])
            )
            return
        state.temp_data['limit_order_price'] = price
        state.waiting_for_input = True
        state.input_type = "limit_order_size"
        keyboard = [[InlineKeyboardButton("🔙 Back",
                                          callback_data=f"limit_order_side_{state.temp_data['limit_order_side'].lower()}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update_bot_message(
            context, user_id,
            f"📝 <b>Place {state.temp_data['limit_order_side']} Limit Order</b>\n\n"
            f"Price: <b>${price:.4f}</b>\n\n"
            "Enter <b>number of shares</b>:",
            reply_markup
        )
    except ValueError:
        await update_bot_message(
            context, user_id,
            "❌ Invalid price. Please enter a valid number.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                        callback_data=f"limit_order_side_{state.temp_data['limit_order_side'].lower()}")]])
        )

async def handle_limit_order_size(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, text: str):
    state = get_user_state(user_id)
    try:
        size = float(text)
        if size <= 0:
            await update_bot_message(
                context, user_id,
                "❌ Invalid size. Size must be greater than 0.",
                InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                            callback_data=f"limit_order_side_{state.temp_data['limit_order_side'].lower()}")]])
            )
            return
        price = state.temp_data['limit_order_price']
        total_cost = price * size
        if state.temp_data['limit_order_side'] == "BUY":
            balance = state.auth_client.get_balance_allowance(
                BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
            )
            usdc_balance = int(balance['balance']) / 1e6
            if total_cost > usdc_balance:
                await update_bot_message(
                    context, user_id,
                    f"❌ <b>Insufficient balance!</b>\n\n"
                    f"Available: <b>${usdc_balance:.2f}</b>\n"
                    f"Needed: <b>${total_cost:.2f}</b>\n\n"
                    f"Difference: <b>${total_cost - usdc_balance:.2f}</b>",
                    InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
                )
                state.waiting_for_input = False
                return
        state.temp_data['limit_order_size'] = size
        state.temp_data['limit_order_total'] = total_cost
        keyboard = [
            [InlineKeyboardButton("✅ Confirm Order", callback_data="confirm_limit_order")],
            [InlineKeyboardButton("❌ Cancel", callback_data="limit_order")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        order_type = "Buy" if state.temp_data['limit_order_side'] == "BUY" else "Sell"
        await update_bot_message(
            context, user_id,
            f"📝 <b>Limit Order Confirmation</b>\n\n"
            f"Type: <b>Limit {order_type}</b>\n"
            f"Outcome: <b>{state.selected_outcome['name']}</b>\n"
            f"Price: <b>${price:.4f}</b>\n"
            f"Shares: <b>{size:.4f}</b>\n"
            f"Total: <b>${total_cost:.4f}</b>\n\n"
            f"Click Confirm to place order:",
            reply_markup
        )
        state.waiting_for_input = False
    except ValueError:
        await update_bot_message(
            context, user_id,
            "❌ Invalid size. Please enter a valid number.",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",
                                                        callback_data=f"limit_order_side_{state.temp_data['limit_order_side'].lower()}")]])
        )

async def place_limit_order_execute(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    await update_bot_message(
        context, user_id,
        "🔄 Placing limit order...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Please wait...", callback_data="wait")]])
    )
    try:
        limit_order = OrderArgs(
            token_id=state.selected_outcome['token_id'],
            price=state.temp_data['limit_order_price'],
            size=state.temp_data['limit_order_size'],
            side=BUY if state.temp_data['limit_order_side'] == "BUY" else SELL
        )
        signed_order = state.auth_client.create_order(limit_order)
        response = state.auth_client.post_order(signed_order, OrderType.GTC)
        order_type = "Buy" if state.temp_data['limit_order_side'] == "BUY" else "Sell"
        await update_bot_message(
            context, user_id,
            f"✅ <b>Limit Order Placed!</b>\n\n"
            f"Type: <b>Limit {order_type}</b>\n"
            f"Outcome: <b>{state.selected_outcome['name']}</b>\n"
            f"Price: <b>${state.temp_data['limit_order_price']:.4f}</b>\n"
            f"Shares: <b>{state.temp_data['limit_order_size']:.4f}</b>\n"
            f"Total: <b>${state.temp_data['limit_order_total']:.4f}</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
    except Exception as e:
        logger.error(f"Error placing limit order: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error placing limit order: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def view_open_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    await update_bot_message(
        context, user_id,
        "🔄 Fetching open orders...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
    )
    try:
        open_orders = state.auth_client.get_orders(OpenOrderParams())
        if not open_orders:
            await update_bot_message(
                context, user_id,
                "📋 <b>No open orders found.</b>",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
            return
        text = f"📋 <b>Open Orders: {len(open_orders)}</b>\n\n"
        orders_by_token = {}
        for order in open_orders:
            token_id = order['token_id']
            if token_id not in orders_by_token:
                orders_by_token[token_id] = []
            orders_by_token[token_id].append(order)
        for token_id, orders in orders_by_token.items():
            text += f"<b>Token: {token_id[:20]}...</b>\n"
            for i, order in enumerate(orders[:5], 1):
                text += f"  {i}. Side: {order['side']}, Price: ${float(order['price']):.4f}, "
                text += f"Size: {float(order['original_size']):.2f}\n"
            text += "\n"
        if len(open_orders) > 20:
            text += f"... and {len(open_orders) - 20} more orders\n"
        keyboard = [[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update_bot_message(context, user_id, text, reply_markup)
    except Exception as e:
        logger.error(f"Error fetching open orders: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error fetching open orders: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def cancel_orders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    keyboard = [
        [InlineKeyboardButton("❌ Cancel All Orders", callback_data="cancel_all")],
        [InlineKeyboardButton("🎯 Cancel Current Outcome Orders", callback_data="cancel_current")],
        [InlineKeyboardButton("📋 View Open Orders First", callback_data="view_orders")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        "❌ <b>Cancel Orders</b>\n\n"
        "Select cancellation option:",
        reply_markup
    )

async def confirm_cancel_all(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    keyboard = [
        [InlineKeyboardButton("✅ Yes, Cancel ALL Orders", callback_data="confirm_cancel_all")],
        [InlineKeyboardButton("❌ No, Go Back", callback_data="cancel_orders")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        "⚠️ <b>Cancel ALL Orders?</b>\n\n"
        "This will cancel ALL your open orders.\n"
        "Are you sure?",
        reply_markup
    )

async def confirm_cancel_current(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    if not state.selected_outcome:
        await update_bot_message(
            context, user_id,
            "❌ Please select an outcome first!",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
        return
    try:
        open_orders = state.auth_client.get_orders(OpenOrderParams())
        current_token_orders = [o for o in open_orders if o['token_id'] == state.selected_outcome['token_id']]
        if not current_token_orders:
            await update_bot_message(
                context, user_id,
                f"❌ No open orders for outcome: {state.selected_outcome['name']}",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
            return
        keyboard = [
            [InlineKeyboardButton(f"✅ Yes, Cancel {len(current_token_orders)} Orders",
                                  callback_data="confirm_cancel_current")],
            [InlineKeyboardButton("❌ No, Go Back", callback_data="cancel_orders")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update_bot_message(
            context, user_id,
            f"⚠️ <b>Cancel Orders for {state.selected_outcome['name']}?</b>\n\n"
            f"This will cancel {len(current_token_orders)} open orders.\n"
            "Are you sure?",
            reply_markup
        )
    except Exception as e:
        logger.error(f"Error checking current orders: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def execute_cancel_all(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    await update_bot_message(
        context, user_id,
        "🔄 Cancelling all orders...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Please wait...", callback_data="wait")]])
    )
    try:
        result = state.auth_client.cancel_all()
        await update_bot_message(
            context, user_id,
            "✅ <b>All orders cancelled!</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
    except Exception as e:
        logger.error(f"Error cancelling all orders: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error cancelling all orders: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def execute_cancel_current(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    await update_bot_message(
        context, user_id,
        "🔄 Cancelling orders...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Please wait...", callback_data="wait")]])
    )
    try:
        open_orders = state.auth_client.get_orders(OpenOrderParams())
        current_token_orders = [o for o in open_orders if o['token_id'] == state.selected_outcome['token_id']]
        cancelled_count = 0
        for order in current_token_orders:
            try:
                state.auth_client.cancel(order['id'])
                cancelled_count += 1
            except Exception as e:
                logger.error(f"Error cancelling order {order['id']}: {e}")
        await update_bot_message(
            context, user_id,
            f"✅ <b>{cancelled_count} orders cancelled for {state.selected_outcome['name']}!</b>",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
    except Exception as e:
        logger.error(f"Error cancelling current orders: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error cancelling orders: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def track_price_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    keyboard = [
        [InlineKeyboardButton("⏱️ 30 seconds", callback_data="track_30")],
        [InlineKeyboardButton("⏱️ 60 seconds", callback_data="track_60")],
        [InlineKeyboardButton("⏱️ 120 seconds", callback_data="track_120")],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update_bot_message(
        context, user_id,
        "📊 <b>Price Tracker</b>\n\n"
        "Select tracking duration:",
        reply_markup
    )

async def start_price_tracking(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, duration: int):
    state = get_user_state(user_id)
    if not state.selected_outcome or not state.selected_outcome.get('token_id'):
        await update_bot_message(
            context, user_id,
            "❌ Invalid outcome selected",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
        return
    try:
        client = ClobClient(CLOB_API)
        token_id = state.selected_outcome['token_id']
        start_time = asyncio.get_event_loop().time()
        prices = []
        message = await update_bot_message(
            context, user_id,
            f"📊 <b>Price Tracking Started</b>\n\n"
            f"Outcome: <b>{state.selected_outcome['name']}</b>\n"
            f"Duration: <b>{duration} seconds</b>\n\n"
            "Starting...",
            None
        )
        while (asyncio.get_event_loop().time() - start_time) < duration:
            try:
                mid = client.get_midpoint(token_id)
                mid_price = float(mid['mid'])
                prices.append(mid_price)
                elapsed = int(asyncio.get_event_loop().time() - start_time)
                remaining = duration - elapsed
                change = ""
                if len(prices) > 1:
                    diff = prices[-1] - prices[-2]
                    change = f" ({'+' if diff >= 0 else ''}{diff:.4f})"
                text = (
                    f"📊 <b>Price Tracking</b>\n\n"
                    f"Outcome: <b>{state.selected_outcome['name']}</b>\n"
                    f"Elapsed: <b>{elapsed}s</b> | Remaining: <b>{remaining}s</b>\n\n"
                    f"Current Price: <b>${mid_price:.4f}</b>{change}\n\n"
                    f"History: {len(prices)} samples"
                )
                await update_bot_message(context, user_id, text, None)
                if remaining > 0:
                    await asyncio.sleep(5)
            except KeyboardInterrupt:
                break
            except Exception as e:
                await asyncio.sleep(5)
        if len(prices) > 1:
            summary = (
                f"📊 <b>Price Tracking Complete</b>\n\n"
                f"Outcome: <b>{state.selected_outcome['name']}</b>\n"
                f"Duration: <b>{duration} seconds</b>\n\n"
                f"Start: <b>${prices[0]:.4f}</b>\n"
                f"End: <b>${prices[-1]:.4f}</b>\n"
                f"Change: <b>{prices[-1] - prices[0]:.4f}</b>\n"
                f"Samples: <b>{len(prices)}</b>"
            )
        else:
            summary = "❌ Not enough data collected."
        keyboard = [[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update_bot_message(context, user_id, summary, reply_markup)
    except Exception as e:
        logger.error(f"Error in price tracker: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error in price tracker: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def get_my_positions(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = get_user_state(user_id)
    if not state.wallet_address:
        await update_bot_message(
            context, user_id,
            "❌ Wallet address not found. Please authenticate first.",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )
        return
    await update_bot_message(
        context, user_id,
        "🔄 Fetching positions...",
        InlineKeyboardMarkup([[InlineKeyboardButton("⏳ Loading...", callback_data="wait")]])
    )
    try:
        url = f"{DATA_API}/positions"
        params = {
            "user": state.wallet_address,
            "sortBy": "CURRENT",
            "sortDirection": "DESC",
            "sizeThreshold": ".1",
            "limit": 50,
            "offset": 0
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=15) as response:
                if response.status != 200:
                    await update_bot_message(
                        context, user_id,
                        f"❌ API Error: {response.status}",
                        InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
                    )
                    return
                data = await response.json()
        positions = []
        if isinstance(data, dict) and 'positions' in data:
            positions = data['positions']
        elif isinstance(data, list):
            positions = data
        else:
            await update_bot_message(
                context, user_id,
                "❌ Unexpected API response",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
            return
        if not positions:
            await update_bot_message(
                context, user_id,
                "📊 <b>No positions found.</b>",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
            state.current_positions = []
            return
        text = f"📊 <b>My Positions: {len(positions)} found</b>\n\n"
        total_value = 0
        total_investment = 0
        state.current_positions = []
        for i, pos in enumerate(positions[:10], 1):
            try:
                market_title = pos.get('title', 'Unknown Market')
                if market_title == 'Unknown Market':
                    market_slug = pos.get('slug', '')
                    if market_slug and market_slug != 'unknown':
                        market_title = market_slug.replace('-', ' ').title()
                if len(market_title) > 50:
                    display_title = market_title[:47] + "..."
                else:
                    display_title = market_title
                outcome = pos.get('outcome', 'N/A')
                shares = float(pos.get('size', 0))
                avg_price = float(pos.get('avgPrice', 0))
                current_value = float(pos.get('currentValue', 0))
                initial_value = float(pos.get('initialValue', 0))
                cash_pnl = float(pos.get('cashPnl', 0))
                percent_pnl = float(pos.get('percentPnl', 0))
                if shares <= 0:
                    continue
                text += f"<b>{i}. {display_title}</b>\n"
                text += f"   Outcome: {outcome}\n"
                text += f"   Shares: {shares:.2f}\n"
                text += f"   Avg Price: ${avg_price:.4f}\n"
                text += f"   Initial: ${initial_value:.2f}\n"
                text += f"   Current: ${current_value:.2f}\n"
                if cash_pnl >= 0:
                    text += f"   P&L: +${cash_pnl:.2f} (+{percent_pnl:.1f}%)\n"
                else:
                    text += f"   P&L: -${abs(cash_pnl):.2f} (-{abs(percent_pnl):.1f}%)\n"
                text += "\n"
                total_value += current_value
                total_investment += initial_value
            except Exception as e:
                continue
        if total_investment > 0:
            total_pnl = total_value - total_investment
            total_pnl_percent = (total_pnl / total_investment * 100) if total_investment > 0 else 0
            text += "═" * 30 + "\n"
            text += "<b>PORTFOLIO SUMMARY:</b>\n"
            text += f"   Total Investment: <b>${total_investment:.2f}</b>\n"
            text += f"   Current Value: <b>${total_value:.2f}</b>\n"
            if total_pnl >= 0:
                text += f"   Total P&L: <b>+${total_pnl:.2f} (+{total_pnl_percent:.1f}%)</b>\n"
            else:
                text += f"   Total P&L: <b>-${abs(total_pnl):.2f} (-{abs(total_pnl_percent):.1f}%)</b>\n"
            text += "═" * 30 + "\n"
        if len(positions) > 10:
            text += f"\n... and {len(positions) - 10} more positions not shown\n"
        keyboard = [[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update_bot_message(context, user_id, text, reply_markup)
    except Exception as e:
        logger.error(f"Error fetching positions: {e}")
        await update_bot_message(
            context, user_id,
            f"❌ Error fetching positions: {str(e)[:200]}",
            InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")
    if update and update.effective_user:
        try:
            await update_bot_message(
                context, update.effective_user.id,
                f"❌ <b>An error occurred:</b>\n{str(context.error)[:300]}",
                InlineKeyboardMarkup([[InlineKeyboardButton("📋 Main Menu", callback_data="back_to_main")]])
            )
        except:
            pass

def main():
    TOKEN = "ВАШ ТОКЕН БОТА"
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    print("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
#https://github.com/fihsr
#xone