"""Market data service for currency, gold, and crypto quotes.

Fetches public no-key data sources and stores the latest values in the
settings table using market_* keys required by the public widget and admin UI.
Network/provider failures are logged and never raised to callers.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from types import SimpleNamespace
from xml.etree import ElementTree

import requests

from database.models import FetchLog, Setting
from database.session import SessionLocal

logger = logging.getLogger(__name__)

MARKET_VALUE_KEYS = [
    "market_usd_azn",
    "market_eur_azn",
    "market_try_azn",
    "market_rub_azn",
    "market_gold_usd",
    "market_btc_usd",
    "market_eth_usd",
    "market_usdt_usd",
    "market_bnb_usd",
]
MARKET_LAST_UPDATED_KEY = "market_last_updated"
MARKET_STATUS_KEYS = ["market_last_status", "market_last_error"]
MARKET_ALL_KEYS = MARKET_VALUE_KEYS + [MARKET_LAST_UPDATED_KEY] + MARKET_STATUS_KEYS

CURRENCY_KEYS = ["market_usd_azn", "market_eur_azn", "market_try_azn", "market_rub_azn"]
GOLD_KEYS = ["market_gold_usd"]
CRYPTO_KEYS = ["market_btc_usd", "market_eth_usd", "market_usdt_usd", "market_bnb_usd"]
MARKET_GROUPS = [("currency", CURRENCY_KEYS), ("gold", GOLD_KEYS), ("crypto", CRYPTO_KEYS)]

MARKET_LABELS = {
    "market_usd_azn": "USD/AZN",
    "market_eur_azn": "EUR/AZN",
    "market_try_azn": "TRY/AZN",
    "market_rub_azn": "RUB/AZN",
    "market_gold_usd": "XAU/USD",
    "market_btc_usd": "BTC/USD",
    "market_eth_usd": "ETH/USD",
    "market_usdt_usd": "USDT/USD",
    "market_bnb_usd": "BNB/USD",
}

MARKET_QUOTE_CURRENCIES = {
    "market_usd_azn": "AZN",
    "market_eur_azn": "AZN",
    "market_try_azn": "AZN",
    "market_rub_azn": "AZN",
    "market_gold_usd": "USD/oz",
    "market_btc_usd": "USD",
    "market_eth_usd": "USD",
    "market_usdt_usd": "USD",
    "market_bnb_usd": "USD",
}

FALLBACK_VALUES = {
    "market_usd_azn": 1.7000,
    "market_eur_azn": 1.9500,
    "market_try_azn": 0.0520,
    "market_rub_azn": 0.0210,
    "market_gold_usd": 2300.00,
    "market_btc_usd": 65000.0,
    "market_eth_usd": 3500.0,
    "market_usdt_usd": 1.0,
    "market_bnb_usd": 600.0,
}


@dataclass(frozen=True)
class MarketQuoteView:
    key: str
    label: str
    value: float
    quote_currency: str


def _utcnow() -> datetime:
    return datetime.utcnow()


def _request_json(url: str, timeout: int = 10) -> dict:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "VREYC-market-service/1.0"})
    response.raise_for_status()
    return response.json()


def _request_text(url: str, timeout: int = 10) -> str:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "VREYC-market-service/1.0"})
    response.raise_for_status()
    return response.text


def _save_setting(db, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value[:500]
    else:
        db.add(Setting(key=key, value=value[:500]))


def _read_float_setting(db, key: str) -> float | None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row or row.value in (None, ""):
        return None
    try:
        return float(row.value)
    except (TypeError, ValueError):
        return None


def _log(db, level: str, message: str) -> None:
    logger.log(logging.ERROR if level == "ERROR" else logging.INFO, message)
    db.add(FetchLog(level=level, message=message[:1000]))


def _fetch_currency_quotes() -> dict[str, float]:
    try:
        rate_date = _utcnow().strftime("%d.%m.%Y")
        xml_text = _request_text(f"https://www.cbar.az/currencies/{rate_date}.xml")
        root = ElementTree.fromstring(xml_text)
        values = {}
        for valute in root.findall(".//Valute"):
            code = valute.attrib.get("Code")
            key = {"USD": "market_usd_azn", "EUR": "market_eur_azn", "TRY": "market_try_azn", "RUB": "market_rub_azn"}.get(code or "")
            nominal_text = valute.findtext("Nominal") or "1"
            value_text = valute.findtext("Value") or ""
            if key and value_text:
                nominal = float(nominal_text.replace(",", "."))
                values[key] = float(value_text.replace(",", ".")) / nominal
        if all(key in values for key in CURRENCY_KEYS):
            return values
    except Exception as exc:
        logger.warning("CBAR currency fetch failed; falling back to exchangerate.host: %s", exc)

    data = _request_json("https://open.er-api.com/v6/latest/AZN")
    rates = data.get("rates") or {}
    return {
        "market_usd_azn": 1 / float(rates["USD"]),
        "market_eur_azn": 1 / float(rates["EUR"]),
        "market_try_azn": 1 / float(rates["TRY"]),
        "market_rub_azn": 1 / float(rates["RUB"]),
    }


def _fetch_gold_quote() -> dict[str, float]:
    try:
        data = _request_json("https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd")
        return {"market_gold_usd": float(data["pax-gold"]["usd"])}
    except Exception as exc:
        logger.warning("CoinGecko pax-gold fetch failed; falling back to Binance PAXGUSDT: %s", exc)
        data = _request_json("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT")
        return {"market_gold_usd": float(data["price"])}


def _fetch_crypto_quotes() -> dict[str, float]:
    try:
        ids = "bitcoin,ethereum,tether,binancecoin"
        data = _request_json(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd")
        return {
            "market_btc_usd": float(data["bitcoin"]["usd"]),
            "market_eth_usd": float(data["ethereum"]["usd"]),
            "market_usdt_usd": float(data["tether"]["usd"]),
            "market_bnb_usd": float(data["binancecoin"]["usd"]),
        }
    except Exception as exc:
        logger.warning("CoinGecko crypto fetch failed; falling back to Binance ticker API: %s", exc)
        symbols = {"BTCUSDT": "market_btc_usd", "ETHUSDT": "market_eth_usd", "BNBUSDT": "market_bnb_usd"}
        quotes = {"market_usdt_usd": 1.0}
        for symbol, key in symbols.items():
            data = _request_json(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
            quotes[key] = float(data["price"])
        return quotes


def _fetch_group(group: str) -> dict[str, float]:
    quotes: dict[str, float] = {}
    fetchers = []
    if group in {"currency", "all"}:
        fetchers.append(("currency", _fetch_currency_quotes, CURRENCY_KEYS))
    if group in {"gold", "all"}:
        fetchers.append(("gold", _fetch_gold_quote, GOLD_KEYS))
    if group in {"crypto", "all"}:
        fetchers.append(("crypto", _fetch_crypto_quotes, CRYPTO_KEYS))
    errors = []
    for group_name, fetcher, fallback_keys in fetchers:
        try:
            quotes.update(fetcher())
        except Exception as exc:
            errors.append(f"{group_name}: {exc}")
            logger.warning("Market %s fetch failed; using fallback/current values: %s", group_name, exc)
            for key in fallback_keys:
                quotes[key] = FALLBACK_VALUES[key]
    if errors:
        logger.warning("Market refresh used fallbacks for %s", "; ".join(errors))
    return quotes


def ensure_market_settings(db, seed_values: bool = False) -> None:
    """Ensure market settings rows exist; optionally seed fallback display values."""
    if seed_values:
        for key, value in FALLBACK_VALUES.items():
            if _read_float_setting(db, key) is None:
                _save_setting(db, key, f"{value:.8f}".rstrip("0").rstrip("."))
    for key in [MARKET_LAST_UPDATED_KEY, *MARKET_STATUS_KEYS]:
        if not db.query(Setting).filter(Setting.key == key).first():
            _save_setting(db, key, "")
    db.commit()


def refresh_market_quotes(group: str = "all") -> int:
    """Fetch and persist market data. Returns number of updated value keys."""
    db = SessionLocal()
    try:
        ensure_market_settings(db)
        quotes = _fetch_group(group)
        if not quotes:
            raise RuntimeError(f"No market quotes returned for {group}")
        now = _utcnow().isoformat()
        for key, value in quotes.items():
            _save_setting(db, key, f"{float(value):.8f}".rstrip("0").rstrip("."))
        _save_setting(db, MARKET_LAST_UPDATED_KEY, now)
        _save_setting(db, "market_last_status", "ok")
        _save_setting(db, "market_last_error", "")
        _log(db, "INFO", f"Market {group} refresh succeeded: {', '.join(sorted(quotes))}")
        db.commit()
        return len(quotes)
    except Exception as exc:
        db.rollback()
        logger.exception("Market %s refresh failed", group)
        try:
            ensure_market_settings(db, seed_values=True)
            _save_setting(db, "market_last_status", "fallback")
            _save_setting(db, "market_last_error", str(exc))
            if not db.query(Setting).filter(Setting.key == MARKET_LAST_UPDATED_KEY, Setting.value != "").first():
                _save_setting(db, MARKET_LAST_UPDATED_KEY, _utcnow().isoformat())
            _log(db, "ERROR", f"Market {group} refresh failed: {exc}")
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Failed to save market refresh failure state")
        return 0
    finally:
        db.close()


def market_panel_context(db):
    rows = {row.key: row.value for row in db.query(Setting).filter(Setting.key.in_(MARKET_ALL_KEYS)).all()}
    sections = []
    for group, keys in MARKET_GROUPS:
        items = []
        for key in keys:
            try:
                value = float(rows.get(key) or "")
            except (TypeError, ValueError):
                continue
            if value <= 0 and key != "market_usdt_usd":
                continue
            items.append(MarketQuoteView(key, MARKET_LABELS[key], value, MARKET_QUOTE_CURRENCIES[key]))
        if items:
            sections.append(SimpleNamespace(group=group, items=items))
    latest = None
    if rows.get(MARKET_LAST_UPDATED_KEY):
        try:
            latest = datetime.fromisoformat(rows[MARKET_LAST_UPDATED_KEY])
        except ValueError:
            latest = None
    return SimpleNamespace(sections=sections, latest_updated_at=latest) if sections else None
