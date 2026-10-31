"""Chargement de la configuration. Le mode paper est imposé par défaut."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str
    secret_key: str
    paper: bool


def load_settings(allow_live: bool = False) -> Settings:
    """Lit les clés depuis l'environnement (ou .env).

    Le trading réel est refusé tant que `allow_live` n'est pas passé
    explicitement ET que ALPACA_PAPER_TRADE vaut false : deux verrous.
    """
    load_dotenv(override=False)
    key = os.environ.get("ALPACA_API_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret:
        raise ConfigError(
            "ALPACA_API_KEY et ALPACA_SECRET_KEY manquent (voir .env.example)."
        )
    paper_env = os.environ.get("ALPACA_PAPER_TRADE", "true").strip().lower()
    paper = paper_env not in ("false", "0", "no")
    if not paper and not allow_live:
        raise ConfigError(
            "ALPACA_PAPER_TRADE=false mais le trading réel n'est pas autorisé "
            "dans ce code. Repasse à true."
        )
    return Settings(api_key=key, secret_key=secret, paper=paper)
