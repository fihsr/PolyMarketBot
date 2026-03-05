# PolyMarketBot
Telegram Bot PolyMarket

# Polymarket Trading Bot

Telegram бот для торговли на Polymarket. Позволяет просматривать рынки, размещать ордера, отслеживать цены и управлять позициями прямо через Telegram.

## Возможности

### 🔐 Аутентификация
- Безопасная аутентификация через приватный ключ
- Ключи хранятся только в сессии (не сохраняются)

### 📊 Работа с рынками
- **Просмотр рынков**: Топ-20 рынков по объему
- **Поиск рынков**: Поиск по ключевым словам
- **Статистика**: Объем, ликвидность, открытый интерес
- **Выбор исхода**: YES/NO или множественные исходы

### 💹 Торговля
- **Рыночные ордера**: Мгновенное исполнение
- **Лимитные ордера**: Ордера по заданной цене
- **Стакан заявок**: Просмотр bid/ask и глубины рынка
- **Баланс**: Проверка USDC баланса

### 📈 Управление позициями
- **Открытые ордера**: Список активных ордеров
- **Отмена ордеров**: Отмена конкретных или всех ордеров
- **Мои позиции**: Текущие позиции с P&L
- **Отслеживание цены**: Мониторинг в реальном времени

## Установка

1. **Клонируйте репозиторий**
```bash
git clone https://github.com/fihsr/polymarket-trading-bot.git
cd polymarket-trading-bot
```

2. **Установите зависимости**
```bash
pip install python-telegram-bot aiohttp py-clob-client
```

3. **Настройте бота**
   - Откройте `main.py`
   - Замените `"ВАШ ТОКЕН БОТА"` на токен вашего бота:
```python
TOKEN = "YOUR_BOT_TOKEN_HERE"
```

4. **Запустите бота**
```bash
python main.py
```

## Использование

### Начало работы
1. Откройте бота в Telegram
2. Отправьте `/start`
3. Примите предупреждение
4. Используйте меню

### Аутентификация
1. Выберите "🔐 Аутентификация"
2. Отправьте адрес кошелька
3. Отправьте приватный ключ

### Торговля
1. **Выберите рынок**: Просмотр или поиск
2. **Выберите исход**: YES/NO или другой
3. **Разместите ордер**: Рыночный или лимитный
4. **Подтвердите**: Проверьте и исполните

## Важно

⚠️ **БЕЗОПАСНОСТЬ:**
- Приватные ключи хранятся ТОЛЬКО в сессии
- Ключи НЕ сохраняются на диск
- Используйте отдельный кошелек для торговли
- Никому не передавайте приватный ключ

## API

- **Gamma API**: `https://gamma-api.polymarket.com` - данные рынков
- **Data API**: `https://data-api.polymarket.com` - данные позиций
- **CLOB API**: `https://clob.polymarket.com` - стакан и торговля

## Автор

**xone** - [GitHub](https://github.com/fihsr)

---

# Polymarket Trading Bot

Telegram bot for trading on Polymarket. Browse markets, place orders, track prices, and manage positions directly through Telegram.

## Features

### 🔐 Authentication
- Secure authentication via private key
- Keys stored only in session (not persisted)

### 📊 Market Operations
- **Browse Markets**: Top 20 markets by volume
- **Search Markets**: Search by keywords
- **Statistics**: Volume, liquidity, open interest
- **Outcome Selection**: YES/NO or multiple outcomes

### 💹 Trading
- **Market Orders**: Instant execution
- **Limit Orders**: Orders at specific price
- **Order Book**: View bids/asks and market depth
- **Balance**: Check USDC balance

### 📈 Position Management
- **Open Orders**: List active orders
- **Cancel Orders**: Cancel specific or all orders
- **My Positions**: Current positions with P&L
- **Price Tracking**: Real-time monitoring

## Installation

1. **Clone repository**
```bash
git clone https://github.com/fihsr/polymarket-trading-bot.git
cd polymarket-trading-bot
```

2. **Install dependencies**
```bash
pip install python-telegram-bot aiohttp py-clob-client
```

3. **Configure bot**
   - Open `main.py`
   - Replace `"ВАШ ТОКЕН БОТА"` with your bot token:
```python
TOKEN = "YOUR_BOT_TOKEN_HERE"
```

4. **Run bot**
```bash
python main.py
```

## Usage

### Getting Started
1. Open bot in Telegram
2. Send `/start`
3. Accept warning
4. Use menu

### Authentication
1. Select "🔐 Authenticate"
2. Send wallet address
3. Send private key

### Trading
1. **Select Market**: Browse or search
2. **Choose Outcome**: YES/NO or other
3. **Place Order**: Market or limit
4. **Confirm**: Review and execute

## Important

⚠️ **SECURITY:**
- Private keys stored ONLY in session
- Keys are NOT saved to disk
- Use dedicated trading wallet
- Never share your private key

## API

- **Gamma API**: `https://gamma-api.polymarket.com` - market data
- **Data API**: `https://data-api.polymarket.com` - position data
- **CLOB API**: `https://clob.polymarket.com` - order book and trading

## Author

**xone** - [GitHub](https://github.com/fihsr)
