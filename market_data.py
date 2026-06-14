"""No-key market data fetch, cache, and presentation helpers."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import logging

import requests

from database.models import MarketQuote, Setting
from database.session import SessionLocal

logger = logging.getLogger(__name__)

CURRENCY_KEYS = ["market_usd_azn", "market_eur_azn", "market_try_azn", "market_rub_azn"]
GOLD_KEYS = ["market_gold_azn"]
CRYPTO_KEYS = ["market_btc_usd", "market_eth_usd", "market_usdt_usd", "market_bnb_usd"]
MARKET_ORDER = CURRENCY_KEYS + GOLD_KEYS + CRYPTO_KEYS

DEFAULT_QUOTES = {
    "market_usd_azn": ("USD/AZN", 1.7000, "AZN", "fallback"),
    "market_eur_azn": ("EUR/AZN", 1.8300, "AZN", "fallback"),
    "market_try_azn": ("TRY/AZN", 0.0520, "AZN", "fallback"),
    "market_rub_azn": ("RUB/AZN", 0.0190, "AZN", "fallback"),
    "market_gold_azn": ("Gold", 4000.00, "AZN/oz", "fallback"),
    "market_btc_usd": ("BTC", 0.0, "USD", "fallback"),
    "market_eth_usd": ("ETH", 0.0, "USD", "fallback"),
    "market_usdt_usd": ("USDT", 1.0, "USD", "fallback"),
    "market_bnb_usd": ("BNB", 0.0, "USD", "fallback"),
}

SETTING_DEFAULTS = {
    "market_enabled": "1",
    "market_currency_provider": "open.er-api.com",
    "market_gold_provider": "coingecko:pax-gold",
    "market_crypto_provider": "coingecko",
    "market_last_refresh_status": "never",
    "market_last_refresh_error": "",
    "market_last_refreshed_at": "",
}


def _utcnow() -> datetime:
    return datetime.utcnow()


def _request_json(url: str, timeout: int = 8) -> dict:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "VREYC-market-widget/1.0"})
    response.raise_for_status()
    return response.json()


def _save_setting(db, key: str, value: str) -> None:
    row = db.query(Setting).filter(Setting.key == key).first()
    if row:
        row.value = value[:500]
    else:
        db.add(Setting(key=key, value=value[:500]))


def ensure_market_settings(db) -> None:
    for key, value in SETTING_DEFAULTS.items():
        if not db.query(Setting).filter(Setting.key == key).first():
            db.add(Setting(key=key, value=value))
    db.commit()


def _upsert_quote(db, key: str, label: str, value: float, quote_currency: str, source: str, updated_at: datetime | None = None) -> None:
    if value is None:
        return
    row = db.query(MarketQuote).filter(MarketQuote.key == key).first()
    if not row:
        row = MarketQuote(key=key)
        db.add(row)
    row.label = label
    row.value = float(value)
    row.quote_currency = quote_currency
    row.source = source
    row.updated_at = updated_at or _utcnow()


def _fetch_currency_quotes() -> dict[str, tuple[str, float, str, str]]:
    data = _request_json("https://open.er-api.com/v6/latest/AZN")
    rates = data.get("rates") or {}
    quotes = {}
    for code, key in [("USD", "market_usd_azn"), ("EUR", "market_eur_azn"), ("TRY", "market_try_azn"), ("RUB", "market_rub_azn")]:
        per_azn = float(rates[code])
        quotes[key] = (f"{code}/AZN", 1 / per_azn, "AZN", "open.er-api.com")
    return quotes


def _fetch_crypto_quotes() -> dict[str, tuple[str, float, str, str]]:
    ids = "bitcoin,ethereum,tether,binancecoin"
    data = _request_json(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd")
    mapping = {"market_btc_usd": ("BTC", "bitcoin"), "market_eth_usd": ("ETH", "ethereum"), "market_usdt_usd": ("USDT", "tether"), "market_bnb_usd": ("BNB", "binancecoin")}
    return {key: (label, float(data[coin]["usd"]), "USD", "coingecko") for key, (label, coin) in mapping.items()}


def _fetch_gold_quote(usd_azn: float | None = None) -> dict[str, tuple[str, float, str, str]]:
    data = _request_json("https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd")
    usd_value = float(data["pax-gold"]["usd"])
    value = usd_value * (usd_azn or DEFAULT_QUOTES["market_usd_azn"][1])
    return {"market_gold_azn": ("Gold", value, "AZN/oz", "coingecko:pax-gold")}


def _current_usd_azn(db) -> float:
    row = db.query(MarketQuote).filter(MarketQuote.key == "market_usd_azn").first()
    return float(row.value) if row and row.value else DEFAULT_QUOTES["market_usd_azn"][1]


def _refresh_group(db, group: str) -> int:
    fetched = {}
    if group in {"currency", "all"}:
        fetched.update(_fetch_currency_quotes())
    if group in {"gold", "all"}:
        fetched.update(_fetch_gold_quote(fetched.get("market_usd_azn", (None, _current_usd_azn(db)))[1]))
    if group in {"crypto", "all"}:
        fetched.update(_fetch_crypto_quotes())
    now = _utcnow()
    for key, payload in fetched.items():
        _upsert_quote(db, key, *payload, updated_at=now)
    _save_setting(db, "market_last_refreshed_at", now.isoformat())
    _save_setting(db, "market_last_refresh_status", "ok")
    _save_setting(db, "market_last_refresh_error", "")
    return len(fetched)


def seed_market_fallbacks(db) -> None:
    existing = {row.key for row in db.query(MarketQuote.key).all()}
    stale_time = _utcnow() - timedelta(days=1)
    for key, payload in DEFAULT_QUOTES.items():
        if key not in existing:
            _upsert_quote(db, key, *payload, updated_at=stale_time)
    db.commit()


def refresh_market_quotes(group: str = "all") -> int:
    db = SessionLocal()
    try:
        ensure_market_settings(db)
        count = _refresh_group(db, group)
        db.commit()
        return count
    except Exception as exc:  # graceful fallback: keep stale cache
        db.rollback()
        logger.warning("Market refresh failed for %s: %s", group, exc)
        try:
            ensure_market_settings(db)
            seed_market_fallbacks(db)
            _save_setting(db, "market_last_refresh_status", "fallback")
            _save_setting(db, "market_last_refresh_error", str(exc))
            db.commit()
        except Exception:
            db.rollback()
        return 0
    finally:
        db.close()


def market_panel_context(db):
    ensure_market_settings(db)
    seed_market_fallbacks(db)
    rows = {row.key: row for row in db.query(MarketQuote).filter(MarketQuote.key.in_(MARKET_ORDER)).all()}
    sections = []
    for group, keys in [("currency", CURRENCY_KEYS), ("gold", GOLD_KEYS), ("crypto", CRYPTO_KEYS)]:
        items = [rows[key] for key in keys if key in rows and rows[key].value is not None]
        if items:
            sections.append(SimpleNamespace(group=group, items=items))
    latest = max((row.updated_at for row in rows.values() if row.updated_at), default=None)
    return SimpleNamespace(sections=sections, latest_updated_at=latest) if sections else None
