"""Configuration: environment variables, constants, and safety rails."""

import os
from dataclasses import dataclass, field
from pathlib import Path

# Load .env file if present (for local development)
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


@dataclass
class Config:
    # Alpaca credentials
    ALPACA_API_KEY: str = field(default_factory=lambda: os.environ.get("ALPACA_API_KEY", ""))
    ALPACA_SECRET_KEY: str = field(default_factory=lambda: os.environ.get("ALPACA_SECRET_KEY", ""))
    ALPACA_PAPER: bool = True  # HARDCODED: never live trading

    # Hugging Face
    HF_TOKEN: str = field(default_factory=lambda: os.environ.get("HF_TOKEN", ""))
    HF_MODEL: str = "meta-llama/Llama-3.3-70B-Instruct"

    # Groq (free fallback)
    GROQ_API_KEY: str = field(default_factory=lambda: os.environ.get("GROQ_API_KEY", ""))
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Trading parameters
    MAX_POSITION_PCT: float = 0.05  # 5% max position size
    CONFIDENCE_THRESHOLD: int = 8
    SCAN_TOP_N: int = 50
    RSI_PERIOD: int = 14

    # Scheduling
    SCAN_INTERVAL_MINUTES: int = 15
    MARKET_OPEN_HOUR: int = 9
    MARKET_OPEN_MINUTE: int = 30
    MARKET_CLOSE_HOUR: int = 16
    MARKET_CLOSE_MINUTE: int = 0

    # Paths
    LOG_DIR: str = "logs"
    TRADE_LOG_FILE: str = "logs/trades.csv"

    def validate(self) -> list[str]:
        """Return list of missing required config values."""
        missing = []
        if not self.ALPACA_API_KEY:
            missing.append("ALPACA_API_KEY")
        if not self.ALPACA_SECRET_KEY:
            missing.append("ALPACA_SECRET_KEY")
        if not self.HF_TOKEN and not self.GROQ_API_KEY:
            missing.append("HF_TOKEN or GROQ_API_KEY (need at least one)")
        return missing


config = Config()
