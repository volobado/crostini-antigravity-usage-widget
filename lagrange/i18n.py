"""
Interface strings.

The widget speaks English. The system locale is deliberately ignored — a tool
whose language changes depending on whose machine it runs on is harder to
support, and screenshots in an issue should match the code.

Other languages are opt-in through `"language": "ru"` in
`~/.lagrange/config.json`. Adding one means adding a dict below; keys missing
from it fall back to English rather than showing a placeholder.
"""

from __future__ import annotations

from . import config

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "title": "L A G R A N G E",
        "active": "ACTIVE",
        "running": "RUNNING",
        "loaded": "LOADED",
        "next_start": "NEXT START",
        "pending_hint": "switched — takes effect when you leave Antigravity",
        "switch": "Switch",
        "add_account": "+  Add account",
        "sign_in_again": "Sign in again",
        "revoked": "access revoked — sign in again",
        "loading": "loading…",
        "refreshing": "refreshing…",
        "switching": "switching…",
        "waiting_browser": "waiting for browser sign-in…",
        "next_refresh": "next refresh in {seconds}s",
        "switched": "Loaded into Antigravity: {email}",
        "auto_switched": "Auto-switched — quota almost spent. Next account loaded: {email}",
        "added": "Account added: {email}",
        "restart_in_place": "Leave Antigravity (/exit or Ctrl+C) — it restarts in "
                            "that same console on the new account and resumes your "
                            "conversation. Nothing is interrupted until you do.",
        "restart_hint": "Antigravity reads credentials at startup — restart it:",
        "restart_manual": "Antigravity reads credentials at startup — restart agy to apply. "
                          "Run it through `lagrange run` to have it restart in place instead.",
        "not_signed_in": "Antigravity is not signed in.\nClick “Add account” to sign in.",
        "no_accounts": "Antigravity is signed in, but Lagrange could not identify\n"
                       "the account. Click “Add account”.",
        "resets_in": "{value}",
        "days_short": "{days}d {hours}h",
        "hours_short": "{hours}h {minutes}m",
        "minutes_short": "{minutes}m",
        "refreshing_now": "refreshing",
        "tip_pin": "Keep on top",
        "tip_compact": "Compact",
        "tip_expand": "Full view",
        "tip_tray": "Hide to tray",
        "tip_close": "Quit",
        "tray_show": "Show widget",
        "tray_pin": "Always on top",
        "tray_refresh": "Refresh now",
        "tray_quit": "Quit Lagrange",
        "tray_tip_signed_out": "Lagrange — not signed in",
        "tray_hint": "Lagrange keeps running in the tray — click the icon to bring it back.",
        # tokens
        "tokens": "Tokens",
        "all_accounts": "All accounts",
        "context": "Context",
        "context_idle": "idle {age}",
        "no_turns": "nothing sent in this window",
        "unattributed": "{sent} ↑ / {received} ↓ not tied to an account",
        "counted_since": "tokens counted since {date}",
        # compact view
        "expand_all": "▤  All accounts",
        "compact_hint": "click a bar for the full view",
        "worst_window": "tightest window",
        # reset times
        "resets_at": "resets at",
        "today": "today",
        "tomorrow": "tomorrow",
        "date_short": "{month} {day}",
    },
    "ru": {
        "title": "L A G R A N G E",
        "active": "АКТИВЕН",
        "running": "РАБОТАЕТ",
        "loaded": "ПОДСТАВЛЕН",
        "next_start": "СО СЛЕДУЮЩЕГО",
        "pending_hint": "переключено — вступит в силу, когда выйдешь из agy",
        "switch": "Переключить",
        "add_account": "+  Добавить аккаунт",
        "sign_in_again": "Войти заново",
        "revoked": "доступ отозван — нужен повторный вход",
        "loading": "загружаю…",
        "refreshing": "обновляю…",
        "switching": "переключаю…",
        "waiting_browser": "жду вход в браузере…",
        "next_refresh": "обновление через {seconds} с",
        "switched": "Аккаунт подставлен: {email}",
        "auto_switched": "Авто-переключение — лимит почти исчерпан. Подставлен следующий: {email}",
        "added": "Аккаунт добавлен: {email}",
        "restart_in_place": "Выйди из agy (/exit или Ctrl+C) — он перезапустится "
                            "в том же окне на новом аккаунте и продолжит тот же "
                            "разговор. Пока не выйдешь, ничего не прервётся.",
        "restart_hint": "agy читает креды при старте — перезапусти его:",
        "restart_manual": "agy читает креды при старте — перезапусти его, чтобы применилось. "
                          "Запускай через `lagrange run`, и он будет перезапускаться "
                          "прямо в том же окне.",
        "not_signed_in": "agy сейчас не залогинен.\nНажми «Добавить аккаунт», чтобы войти.",
        "no_accounts": "agy залогинен, но виджет не смог определить аккаунт.\n"
                       "Нажми «Добавить аккаунт».",
        "resets_in": "{value}",
        "days_short": "{days} д {hours} ч",
        "hours_short": "{hours} ч {minutes} м",
        "minutes_short": "{minutes} м",
        "refreshing_now": "обновляю",
        "tip_pin": "Поверх всех окон",
        "tip_compact": "Компактно",
        "tip_expand": "Развернуть",
        "tip_tray": "Свернуть в трей",
        "tip_close": "Выход",
        "tray_show": "Показать виджет",
        "tray_pin": "Поверх всех окон",
        "tray_refresh": "Обновить сейчас",
        "tray_quit": "Выйти из Lagrange",
        "tray_tip_signed_out": "Lagrange — не залогинен",
        "tray_hint": "Lagrange остался в трее — кликни по значку, чтобы вернуть окно.",
        # токены
        "tokens": "Токены",
        "all_accounts": "Все аккаунты",
        "context": "Контекст",
        "context_idle": "простой {age}",
        "no_turns": "в этом окне ничего не отправлялось",
        "unattributed": "{sent} ↑ / {received} ↓ без привязки к аккаунту",
        "counted_since": "токены считаются с {date}",
        # компактный вид
        "expand_all": "▤  Все аккаунты",
        "compact_hint": "клик по полосе — полный вид",
        "worst_window": "ближайший лимит",
        # время сброса
        "resets_at": "сброс",
        "today": "сегодня",
        "tomorrow": "завтра",
        "date_short": "{day} {month}",
    },
}


# Quota window ids as the backend spells them. Anything not listed is shown
# verbatim, so a new window type appears instead of vanishing.
WINDOWS: dict[str, dict[str, str]] = {
    "en": {"5h": "5-hour", "weekly": "weekly", "daily": "daily", "monthly": "monthly"},
    "ru": {"5h": "5 часов", "weekly": "неделя", "daily": "сутки", "monthly": "месяц"},
}


# Month abbreviations are spelled out rather than taken from strftime("%b"),
# which follows the machine's locale: an English widget on a Russian Windows
# would print "сен" in the middle of an English line.
MONTHS: dict[str, tuple[str, ...]] = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "ru": ("янв", "фев", "мар", "апр", "мая", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек"),
}


DEFAULT_LANGUAGE = "en"


def _detect() -> str:
    configured = (config.get("language") or "").strip().lower()
    return configured if configured in STRINGS else DEFAULT_LANGUAGE


_lang = _detect()


def t(key: str, **params) -> str:
    template = STRINGS.get(_lang, {}).get(key) or STRINGS["en"][key]
    return template.format(**params) if params else template


def window(window_id: str, fallback: str = "") -> str:
    return WINDOWS.get(_lang, {}).get(window_id) or fallback or window_id


def month(index: int) -> str:
    """Abbreviated month name, 1–12."""
    names = MONTHS.get(_lang) or MONTHS["en"]
    return names[max(1, min(12, index)) - 1]


def language() -> str:
    return _lang
