import aiohttp
import logging
from .base import BaseLLMClient

logger = logging.getLogger(__name__)

class GeminiClient(BaseLLMClient):
    async def _raw_call(self, model: str, system: str, user: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        headers = {'Content-Type': 'application/json'}

        payload = {
            "systemInstruction": {
                "parts": [{"text": system}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user}]
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": 4096,
                "topP": 0.95
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=self.timeout) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"Erro Gemini API {resp.status}: {error_text}")

                data = await resp.json()
                try:
                    return data['candidates'][0]['content']['parts'][0]['text']
                except (KeyError, IndexError):
                    logger.warning("Resposta inesperada da Gemini API: %s", data)
                    return "NOTA FINAL: 0/50\nRESPOSTA_VAZIA"