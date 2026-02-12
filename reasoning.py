"""LLM-powered sentiment analysis and confidence scoring.

Primary: HuggingFace Inference API
Fallback: Groq (free tier)
"""

import json
import time
from dataclasses import dataclass

from huggingface_hub import InferenceClient

from config import config

SYSTEM_PROMPT = """You are a senior quantitative analyst at a hedge fund. You analyze stocks using technical indicators and news sentiment to make trading decisions.

Given a ticker's RSI value and recent news headlines, provide a structured analysis.

You MUST respond with ONLY valid JSON in this exact format (no markdown, no extra text):
{
    "ticker": "SYMBOL",
    "sentiment": "bullish" | "bearish" | "neutral",
    "confidence": 1-10,
    "reasoning": "Brief explanation of your analysis",
    "action": "buy" | "sell" | "hold",
    "suggested_allocation": 0.0-1.0
}

Rules:
- confidence 1-10: only recommend action at 8+ confidence
- suggested_allocation: fraction of max position size (0.0 = no trade, 1.0 = full position)
- Consider RSI: <30 = oversold (potential buy), >70 = overbought (potential sell)
- Weigh news sentiment heavily in your decision
- Be conservative: when in doubt, hold
- If there are no headlines, base your decision primarily on RSI"""


@dataclass
class TradeDecision:
    ticker: str
    sentiment: str
    confidence: int
    reasoning: str
    action: str
    suggested_allocation: float


def _build_user_prompt(ticker: str, rsi: float | None, headlines: list[str], current_price: float | None) -> str:
    rsi_text = f"RSI (14-period): {rsi:.2f}" if rsi is not None else "RSI: unavailable"
    price_text = f"Current Price: ${current_price:.2f}" if current_price else "Current Price: unavailable"
    headlines_text = "\n".join(f"- {h}" for h in headlines) if headlines else "No recent headlines available."

    return f"""Analyze {ticker}:

{price_text}
{rsi_text}

Recent Headlines:
{headlines_text}

Provide your analysis as JSON."""


def _parse_llm_response(content: str, ticker: str) -> TradeDecision:
    """Parse JSON from LLM response text into a TradeDecision."""
    content = content.strip()
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0].strip()
    elif "```" in content:
        content = content.split("```")[1].split("```")[0].strip()

    data = json.loads(content)

    return TradeDecision(
        ticker=data.get("ticker", ticker),
        sentiment=data.get("sentiment", "neutral"),
        confidence=int(data.get("confidence", 0)),
        reasoning=data.get("reasoning", ""),
        action=data.get("action", "hold"),
        suggested_allocation=float(data.get("suggested_allocation", 0.0)),
    )


def _call_huggingface(messages: list[dict]) -> str:
    """Call HuggingFace Inference API. Returns response content string."""
    client = InferenceClient(
        model=config.HF_MODEL,
        token=config.HF_TOKEN,
    )
    response = client.chat_completion(
        messages=messages,
        max_tokens=500,
        temperature=0.1,
    )
    return response.choices[0].message.content


def _call_groq(messages: list[dict]) -> str:
    """Call Groq API as fallback. Returns response content string."""
    from groq import Groq

    client = Groq(api_key=config.GROQ_API_KEY)
    response = client.chat.completions.create(
        model=config.GROQ_MODEL,
        messages=messages,
        max_tokens=500,
        temperature=0.1,
    )
    return response.choices[0].message.content


def analyze_ticker(
    ticker: str,
    rsi: float | None,
    headlines: list[str],
    current_price: float | None,
) -> TradeDecision:
    """Analyze a ticker using HF Inference API with Groq fallback."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_prompt(ticker, rsi, headlines, current_price)},
    ]

    # Try HuggingFace first
    if config.HF_TOKEN:
        try:
            content = _call_huggingface(messages)
            time.sleep(1)  # Rate limit for free tier
            return _parse_llm_response(content, ticker)
        except Exception as e:
            print(f"[reasoning] HF failed for {ticker}: {e}")

    # Fallback to Groq
    if config.GROQ_API_KEY:
        try:
            content = _call_groq(messages)
            time.sleep(1)
            return _parse_llm_response(content, ticker)
        except Exception as e:
            print(f"[reasoning] Groq fallback also failed for {ticker}: {e}")

    # Both failed
    provider_status = []
    if not config.HF_TOKEN:
        provider_status.append("HF_TOKEN missing")
    if not config.GROQ_API_KEY:
        provider_status.append("GROQ_API_KEY missing")
    reason = f"All LLM providers failed ({', '.join(provider_status)})" if provider_status else "All LLM providers failed"

    time.sleep(1)
    return TradeDecision(
        ticker=ticker,
        sentiment="neutral",
        confidence=0,
        reasoning=reason,
        action="hold",
        suggested_allocation=0.0,
    )
