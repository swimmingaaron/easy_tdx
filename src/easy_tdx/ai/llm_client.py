"""Multi-Provider LLM Client: DeepSeek, Qwen, OpenAI, Claude, Ollama."""
from __future__ import annotations
import os
import json
import logging
from typing import Any
import httpx

logger = logging.getLogger(__name__)

class LLMClient:
    """Unified LLM Client supporting standard OpenAI-compatible endpoints."""
    
    def __init__(
        self,
        provider: str = "deepseek",
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 30.0
    ):
        self.provider = provider or os.getenv("LLM_PROVIDER", "deepseek")
        self.api_key = api_key or os.getenv("LLM_API_KEY", "")
        self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
        self.model = model or os.getenv("LLM_MODEL", "deepseek-chat")
        self.timeout = timeout

    def generate(self, prompt: str, system_prompt: str = "你是一个顶级的A股量化投资研究总监。") -> str:
        """Call LLM API with prompt and return text response."""
        if not self.api_key:
            return ""
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 1500
        }
        
        try:
            url = self.base_url.rstrip("/") + "/chat/completions"
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    return data["choices"][0]["message"]["content"]
                else:
                    logger.warning(f"LLM API Error {response.status_code}: {response.text}")
                    return ""
        except Exception as e:
            logger.warning(f"LLM request exception: {e}")
            return ""

llm_client = LLMClient()
