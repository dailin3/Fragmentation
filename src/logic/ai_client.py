"""DeepSeek API 调用。"""
import json
import logging
import re

import httpx

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_API_URL, DEEPSEEK_MODEL

logger = logging.getLogger("ai_client")


def call_ai(prompt: str) -> dict:
    """同步调用 DeepSeek，返回解析后的 JSON。失败重试 3 次，记录错误日志。"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    for attempt in range(3):
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(DEEPSEEK_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                outer = resp.json()
                content_str = outer["choices"][0]["message"]["content"].strip()
                if content_str.startswith("```"):
                    content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
                    content_str = re.sub(r"\s*```$", "", content_str)
                return json.loads(content_str)
        except Exception as e:
            logger.error(f"AI 请求失败 (attempt {attempt + 1}/3): {e}")
            if attempt == 2:
                raise
    return {}


async def call_ai_async(prompt: str) -> dict:
    """异步调用 DeepSeek，返回解析后的 JSON。失败重试 3 次，记录错误日志。"""
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
    }
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                resp = await client.post(DEEPSEEK_API_URL, json=payload, headers=headers)
                resp.raise_for_status()
                outer = resp.json()
                content_str = outer["choices"][0]["message"]["content"].strip()
                if content_str.startswith("```"):
                    content_str = re.sub(r"^```(?:json)?\s*", "", content_str)
                    content_str = re.sub(r"\s*```$", "", content_str)
                return json.loads(content_str)
        except Exception as e:
            logger.error(f"AI 请求失败 (attempt {attempt + 1}/3): {e}")
            if attempt == 2:
                raise
    return {}
