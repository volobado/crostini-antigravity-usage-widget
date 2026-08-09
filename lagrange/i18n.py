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
    },
}


# Quota window ids as the backend spells them. Anything not listed is shown
# verbatim, so a new window type appears instead of vanishing.
WINDOWS: dict[str, dict[str, str]] = {
    "en": {"5h": "5-hour", "weekly": "weekly", "daily": "daily", "monthly": "monthly"},
    "ru": {"5h": "5 часов", "weekly": "неделя", "daily": "сутки", "monthly": "месяц"},
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


def language() -> str:
    return _lang
