import aiohttp
from .base import BaseLLMClient

class GroqClient(BaseLLMClient):
    async def _raw_call(self, model: str, system: str, user: str) -> str:
        # A URL e chave são pegas do self.provider_cfg (carregado na Base)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user}
            ],
            "temperature": self.temperature,
            "stream": False
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(self.api_url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_detail = await resp.text()
                    raise Exception(f"Erro Groq API {resp.status}: {error_detail}")
                
                data = await resp.json()
                return data['choices'][0]['message']['content']