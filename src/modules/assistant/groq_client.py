"""Groq chat completion helper tailored for the assistant orchestrator."""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import requests
from loguru import logger

from src.modules.pipeline.llm.rate_limiter import get_rate_limiter

from .config import LLM_API_BASE, LLM_API_KEY, LLM_REQUEST_TIMEOUT


def _estimate_tokens(payload: Dict[str, Any]) -> int:
    messages = payload.get("messages") or []
    max_tokens = int(payload.get("max_tokens", 0) or 0)
    prompt_text = json.dumps(messages, ensure_ascii=False)
    return max_tokens + max(1, len(prompt_text) // 4)


def chat_completion(
    payload: Dict[str, Any],
    *,
    usage_tag: str,
    request_timeout: int | None = None,
) -> Dict[str, Any]:
    """Perform a Groq chat completion call returning the raw JSON payload."""
    if not LLM_API_KEY:
        raise ValueError("LLM_API_KEY not configured for Groq usage")

    base_url = (LLM_API_BASE or "https://api.groq.com/openai/v1").rstrip("/")
    endpoint = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }

    rate_limiter = get_rate_limiter()
    attempts = 0
    last_response: requests.Response | None = None
    timeout = request_timeout or LLM_REQUEST_TIMEOUT

    while attempts < 4:
        attempts += 1
        entry_id: int | None = None
        try:
            estimated_tokens = _estimate_tokens(payload)
            rate_info = rate_limiter.check_and_wait(estimated_tokens, tag=usage_tag)
            entry_id = rate_info.get("entry_id")
            if rate_info.get("wait_time", 0) > 0:
                logger.info(
                    "Rate limiter waited {wait:.1f}s before Groq request",
                    wait=rate_info["wait_time"],
                )

            logger.debug(
                "Calling Groq chat completion (attempt {attempt})", attempt=attempts
            )
            last_response = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if last_response.status_code == 200:
                data = last_response.json()
                usage = data.get("usage") or {}
                prompt_tokens = usage.get("prompt_tokens")
                completion_tokens = usage.get("completion_tokens", 0)
                if prompt_tokens is None:
                    prompt_tokens = max(
                        0, estimated_tokens - payload.get("max_tokens", 0)
                    )
                if entry_id is not None:
                    rate_limiter.record_actual_tokens(
                        entry_id,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                    )
                return data

            if last_response.status_code == 429:
                retry_after = last_response.headers.get("retry-after", "2")
                logger.warning(
                    "Groq rate limit 429 (attempt {attempt}) retry_after={retry}",
                    attempt=attempts,
                    retry=retry_after,
                )
                if entry_id is not None:
                    rate_limiter.cancel_request(entry_id)
                wait_time = (
                    min(int(retry_after), 60) if retry_after.isdigit() else 2**attempts
                )
                time.sleep(wait_time)
                continue

            if last_response.status_code in {500, 502, 503}:
                wait_time = 2**attempts
                logger.warning(
                    "Groq transient error {code}, retrying in {wait}s",
                    code=last_response.status_code,
                    wait=wait_time,
                )
                if entry_id is not None:
                    rate_limiter.cancel_request(entry_id)
                time.sleep(wait_time)
                continue

            logger.error(
                "Groq API error {code}: {body}",
                code=last_response.status_code,
                body=last_response.text[:400],
            )
            last_response.raise_for_status()

        except requests.exceptions.Timeout:
            logger.warning("Groq timeout on attempt {attempt}", attempt=attempts)
            if entry_id is not None:
                rate_limiter.cancel_request(entry_id)
            if attempts >= 4:
                raise
            time.sleep(2**attempts)
        except Exception:
            if entry_id is not None:
                rate_limiter.cancel_request(entry_id)
            raise

    if last_response is not None and last_response.status_code == 429:
        retry_after = last_response.headers.get("retry-after", "unknown")
        remaining_tokens = last_response.headers.get(
            "x-ratelimit-remaining-tokens", "0"
        )
        reset_tokens = last_response.headers.get("x-ratelimit-reset-tokens", "unknown")
        if remaining_tokens == "0":
            raise RuntimeError(
                f"⚠️ Groq daily token limit reached. Tokens reset in: {reset_tokens}."
            )
        raise RuntimeError(f"⚠️ Groq rate limit reached. Retry after: {retry_after}s.")

    raise RuntimeError("Groq API call failed after all retries")
