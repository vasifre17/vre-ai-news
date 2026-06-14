from __future__ import annotations

from datetime import datetime
import logging
import xml.etree.ElementTree as ET

import requests

from database.models import FetchLog, MarketQuote
from database.session import SessionLocal

logger = logging.getLogger(__name__)
HTTP_TIMEOUT = 6
USER_AGENT = "VREYC-News/1.0 (+https://vreyc.com)"

MARKET_GROUPS = {
    "currency": ["market_usd_azn", "market_eur_azn", "market_try_azn", "market_rub_azn"],
    "gold": ["market_gold_usd"],
    "crypto": ["market_btc_usd", "market_eth_usd", "market_usdt_usd", "market_bnb_usd"],
}

QUOTE_META = {
    "market_usd_azn": ("USD/AZN", "AZN"),
    "market_eur_azn": ("EUR/AZN", "AZN"),
    "market_try_azn": ("TRY/AZN", "AZN"),
    "market_rub_azn": ("RUB/AZN", "AZN"),
    "market_gold_usd": ("Gold / XAU", "USD"),
    "market_btc_usd": ("BTC/USD", "USD"),
    "market_eth_usd": ("ETH/USD", "USD"),
    "market_usdt_usd": ("USDT/USD", "USD"),
    "market_bnb_usd": ("BNB/USD", "USD"),
}


def _log(db, level: str, message: str) -> None:
    logger.log(logging.ERROR if level == "ERROR" else logging.INFO, message)
    db.add(FetchLog(level=level, message=message[:1000]))


def _upsert(db, key: str, value: float, source: str) -> None:
    label, quote_currency = QUOTE_META[key]
    row = db.query(MarketQuote).filter(MarketQuote.key == key).first()
    if not row:
        row = MarketQuote(key=key)
        db.add(row)
    row.label = label
    row.value = float(value)
    row.quote_currency = quote_currency
    row.source = source
    row.updated_at = datetime.utcnow()


def fetch_currency_quotes(db) -> int:
    today = datetime.utcnow().strftime("%d.%m.%Y")
    url = f"https://www.cbar.az/currencies/{today}.xml"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    code_to_key = {"USD": "market_usd_azn", "EUR": "market_eur_azn", "TRY": "market_try_azn", "RUB": "market_rub_azn"}
    updated = 0
    for valute in root.findall(".//Valute"):
        code = valute.attrib.get("Code")
        key = code_to_key.get(code or "")
        if not key:
            continue
        nominal = float((valute.findtext("Nominal") or "1").replace(",", "."))
        value = float((valute.findtext("Value") or "0").replace(",", ".")) / nominal
        _upsert(db, key, value, "Central Bank of Azerbaijan")
        updated += 1
    return updated


def fetch_gold_quote(db) -> int:
    response = requests.get("https://stooq.com/q/l/?s=xauusd&f=sd2t2ohlcv&h&e=csv", headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    lines = response.text.strip().splitlines()
    if len(lines) < 2:
        return 0
    fields = lines[1].split(",")
    close = fields[6] if len(fields) > 6 else "N/D"
    if close in {"N/D", ""}:
        return 0
    _upsert(db, "market_gold_usd", float(close), "Stooq XAUUSD")
    return 1


def fetch_crypto_quotes(db) -> int:
    symbols = {"BTCUSDT": "market_btc_usd", "ETHUSDT": "market_eth_usd", "USDTUSDC": "market_usdt_usd", "BNBUSDT": "market_bnb_usd"}
    response = requests.get("https://api.binance.com/api/v3/ticker/price", headers={"User-Agent": USER_AGENT}, timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    prices = {item.get("symbol"): item.get("price") for item in response.json()}
    updated = 0
    for symbol, key in symbols.items():
        if prices.get(symbol):
            _upsert(db, key, float(prices[symbol]), "Binance public ticker")
            updated += 1
    return updated


def refresh_market_quotes(group: str = "all") -> None:
    db = SessionLocal()
    try:
        tasks = []
        if group in {"all", "currency"}:
            tasks.append(("currency", fetch_currency_quotes))
        if group in {"all", "gold"}:
            tasks.append(("gold", fetch_gold_quote))
        if group in {"all", "crypto"}:
            tasks.append(("crypto", fetch_crypto_quotes))
        for name, fn in tasks:
            try:
                count = fn(db)
                _log(db, "INFO", f"Market {name} refresh updated {count} quote(s).")
                db.commit()
            except Exception as exc:
                db.rollback()
                _log(db, "ERROR", f"Market {name} refresh failed: {exc}")
                db.commit()
    finally:
        db.close()


def market_panel_context(db) -> dict | None:
    rows = db.query(MarketQuote).filter(MarketQuote.value.isnot(None)).all()
    by_key = {row.key: row for row in rows}
    if not by_key:
        return None
    sections = []
    for group, keys in MARKET_GROUPS.items():
        items = [by_key[key] for key in keys if key in by_key]
        if items:
            sections.append({"group": group, "items": items})
    if not sections:
        return None
    latest = max((row.updated_at for row in by_key.values() if row.updated_at), default=None)
    return {"sections": sections, "latest_updated_at": latest}
