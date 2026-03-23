#!/usr/bin/env python3
"""
Interface unificada para API DeepSeek (substitui Groq)
Arquivo: llm_interface_prova_deepseek.py

Cliente assíncrono para chamadas à API DeepSeek com:
  - Modelos lidos de config.yaml → deepseek.models (lista ou string)
  - Iteração por todos os modelos da lista até obter resposta válida
  - Retry com backoff exponencial por modelo
  - Rate limiting adaptativo
  - Extração de metadados (modelo usado, tempo, tokens)
"""

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)


# =============================================================================
# ESTRUTURAS DE DADOS
# =============================================================================

@dataclass
class LLMResponse:
    """Resposta padronizada de qualquer LLM."""
    success: bool
    content: Optional[str] = None
    model_used: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None
    attempts: int = 0
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


# =============================================================================
# CLIENTE DEEPSEEK
# =============================================================================

class DeepSeekClient:
    """
    Cliente assíncrono para API DeepSeek.
    Varia entre todos os modelos de deepseek.models até obter resposta.
    """

    def __init__(self, config: Dict):
        deepseek_cfg = config.get('deepseek', {})

        self.api_key = deepseek_cfg.get('api_key')
        if not self.api_key:
            raise ValueError("DeepSeek API key não encontrada no config.yaml")

        self.api_url = deepseek_cfg.get(
            'api_url',
            "https://api.deepseek.com/v1/chat/completions"
        )
        self.temperature = deepseek_cfg.get('temperature', 0.3)

        # Limites de resposta
        self.max_response_chars = deepseek_cfg.get('max_response_chars', 8000)
        self.min_response_chars = deepseek_cfg.get('min_response_chars', 5)

        # DeepSeek aceita no máximo 8192 tokens; 1 token ≈ 4 chars
        self.max_tokens = max(1, min(8192, self.max_response_chars // 4))
        logger.info(f"DeepSeek max_tokens configurado para: {self.max_tokens}")

        # Normaliza models para lista (pode vir como string ou lista no YAML)
        raw_models = deepseek_cfg.get('models', 'deepseek-chat')
        if isinstance(raw_models, str):
            self.models = [raw_models]
        else:
            self.models = list(raw_models)
        if not self.models:
            self.models = ['deepseek-chat']

        # Rate limiting
        self.requests_per_minute = 60
        self._request_timestamps: List[float] = []
        self._semaphore = asyncio.Semaphore(5)

        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *args):
        if self._session:
            await self._session.close()

    async def _wait_for_rate_limit(self):
        now = time.time()
        self._request_timestamps = [t for t in self._request_timestamps if now - t < 60]
        if len(self._request_timestamps) >= self.requests_per_minute:
            oldest = self._request_timestamps[0]
            sleep_time = 60 - (now - oldest)
            if sleep_time > 0:
                logger.debug(f"Rate limit: aguardando {sleep_time:.2f}s")
                await asyncio.sleep(sleep_time)
        self._request_timestamps.append(time.time())

    async def _make_request(
        self,
        session: aiohttp.ClientSession,
        model: str,
        messages: List[Dict],
        timeout: int = 120,
    ) -> Dict:
        """Executa uma requisição única."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        logger.debug(f"Enviando requisição para {model} com max_tokens={self.max_tokens}")
        async with session.post(
            self.api_url,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {error_text}")
            return await resp.json()

    async def chat_completion(
        self,
        system_prompt: str,
        user_content: str,
        timeout_per_try: int = 120,
    ) -> LLMResponse:
        """
        Tenta todos os modelos de deepseek.models em sequência.
        Retorna na primeira resposta válida.
        """
        start_time = time.time()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content},
        ]

        last_error = None
        total_attempts = 0

        async with self._semaphore:
            await self._wait_for_rate_limit()

            for model in self.models:
                total_attempts += 1
                try:
                    logger.debug(f"Tentando modelo: {model}")
                    data = await self._make_request(
                        self._session, model, messages, timeout_per_try
                    )
                    content = data['choices'][0]['message']['content']

                    if len(content.strip()) < self.min_response_chars:
                        raise ValueError(f"Resposta muito curta ({len(content)} chars)")

                    if len(content) > self.max_response_chars:
                        content = content[:self.max_response_chars] + "\n[TRUNCADO...]"

                    usage   = data.get('usage', {})
                    elapsed = time.time() - start_time
                    logger.info(f"✓ DeepSeek/{model} em {elapsed:.1f}s")

                    return LLMResponse(
                        success=True,
                        content=content,
                        model_used=model,
                        duration_seconds=elapsed,
                        attempts=total_attempts,
                        prompt_tokens=usage.get('prompt_tokens'),
                        completion_tokens=usage.get('completion_tokens'),
                        total_tokens=usage.get('total_tokens'),
                    )

                except asyncio.TimeoutError:
                    last_error = f"Timeout após {timeout_per_try}s"
                    logger.warning(f"Timeout com {model}: {last_error}")

                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Falha com {model}: {last_error}")
                    # Erros de autenticação/saldo: não adianta tentar outros modelos
                    if any(code in last_error for code in ("401", "402", "unauthorized")):
                        break

                # Pausa curta entre modelos
                if total_attempts < len(self.models):
                    await asyncio.sleep(1)

        elapsed = time.time() - start_time
        return LLMResponse(
            success=False,
            error=last_error or "Todos os modelos falharam",
            duration_seconds=elapsed,
            attempts=total_attempts,
        )


# =============================================================================
# INTERFACE DE ALTO NÍVEL — compatível com graderNq.py
# =============================================================================

class LLMClientProva:
    """
    Wrapper sobre DeepSeekClient para manter compatibilidade com graderNq.py.
    Expõe call_grader() e chat_completion() com a mesma assinatura do cliente Groq.
    """

    def __init__(self, config: Dict):
        self.config = config
        self._client: Optional[DeepSeekClient] = None

    async def __aenter__(self):
        self._client = DeepSeekClient(self.config)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.__aexit__(*args)

    async def chat_completion(self, system_prompt: str, code_content: str) -> LLMResponse:
        """Chama DeepSeekClient iterando pelos modelos configurados."""
        if self._client is None:
            raise RuntimeError("LLMClientProva não inicializado (use 'async with')")
        return await self._client.chat_completion(system_prompt, code_content)

    async def call_grader(self, system_prompt: str, code_content: str) -> LLMResponse:
        """Alias para compatibilidade com graderNq.py."""
        return await self.chat_completion(system_prompt, code_content)


# =============================================================================
# PROCESSAMENTO EM LOTE ASSÍNCRONO
# =============================================================================

async def process_students_async(
    client: LLMClientProva,
    tasks: List[Tuple[str, str, Dict]],
    max_concurrent: int = 3,
) -> List[Tuple[Dict, LLMResponse]]:
    """
    Processa múltiplos alunos em paralelo com controle de concorrência.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results   = []

    async def _process_one(system_prompt: str, user_content: str, metadata: Dict):
        async with semaphore:
            response = await client.chat_completion(system_prompt, user_content)
            return metadata, response

    coros = [_process_one(prompt, content, meta) for prompt, content, meta in tasks]

    for future in asyncio.as_completed(coros):
        try:
            metadata, response = await future
            results.append((metadata, response))
            status   = "✓" if response.success else "✗"
            model    = response.model_used or "N/A"
            duration = response.duration_seconds
            logger.info(f"{status} {metadata['student']} | {model} | {duration:.1f}s")
        except Exception as e:
            logger.error(f"Erro inesperado: {e}")

    return results