#!/usr/bin/env python3
"""
Sistema de Correção Automática de Provas
Módulo de Interface com LLM - VERSÃO ASSÍNCRONA
Arquivo: llm_interface_prova.py

Adaptado de src/llm_interface.py (Sistema UAB) para correção de provas.
Diferenças principais:
  - API Key lida diretamente do config.yaml (seção groq.api_key)
  - Seção de config usada: 'groq' (não 'api')
  - System prompt vem de arquivo externo (prompt1q.txt)
  - Resposta é texto livre (não JSON estruturado)
"""

import asyncio
import aiohttp
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# ESTRUTURA DE RESPOSTA
# =============================================================================

@dataclass
class LLMResponse:
    """Estrutura de resposta da LLM"""
    success: bool
    content: str          # texto livre retornado pela IA
    model_used: Optional[str] = None
    error: Optional[str] = None
    attempts: int = 0
    duration_seconds: float = 0.0


# =============================================================================
# CLIENTE LLM ASSÍNCRONO
# =============================================================================

class LLMClientProva:
    """
    Cliente assíncrono para interface com a API Groq.
    Lê configuração da seção 'groq' do config.yaml.
    Gerencia sessão HTTP compartilhada e implementa retry/backoff.
    """

    def __init__(self, config: Dict):
        groq_cfg = config.get('groq', {})

        self.url         = groq_cfg.get('api_url', 'https://api.groq.com/openai/v1/chat/completions')
        self.api_key     = groq_cfg.get('api_key', '')
        self.temperature = groq_cfg.get('temperature', 0.7)
        # Groq aceita no máximo 32768; cap em 8192 que é suficiente para correções
        self.max_tokens  = min(groq_cfg.get('max_response_chars', 8192), 8192)
        self.models: List[str] = groq_cfg.get('models', ['llama-3.3-70b-versatile'])

        self.session: Optional[aiohttp.ClientSession] = None
        self._session_lock = asyncio.Lock()

        if not self.api_key:
            raise ValueError("groq.api_key não encontrada em config.yaml")
        if not self.url:
            raise ValueError("groq.api_url não encontrada em config.yaml")

    # ── Context manager ──────────────────────────────────────────────────────

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, *_):
        await self.close()

    # ── Sessão HTTP ──────────────────────────────────────────────────────────

    async def _ensure_session(self):
        async with self._session_lock:
            if self.session is None or self.session.closed:
                timeout = aiohttp.ClientTimeout(total=300, connect=30, sock_read=120)
                connector = aiohttp.TCPConnector(
                    limit=10,
                    limit_per_host=5,
                    ttl_dns_cache=300,
                    force_close=True,
                )
                self.session = aiohttp.ClientSession(
                    timeout=timeout,
                    connector=connector,
                    headers={"User-Agent": "ProvaCorrectorAsync/1.0"},
                )
                logger.debug("Nova sessão HTTP criada")

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("Sessão HTTP fechada")

    # ── Chamada principal com retry ───────────────────────────────────────────

    async def call_grader(
        self,
        system_prompt: str,
        code_content: str,
        max_retries: int = 3,
        backoff_base: float = 2.0,
    ) -> LLMResponse:
        start = datetime.now()
        total_attempts = 0

        await self._ensure_session()

        for model in self.models:
            for retry in range(max_retries):
                total_attempts += 1
                try:
                    content = await self._single_call(model, system_prompt, code_content)
                    if content:
                        duration = (datetime.now() - start).total_seconds()
                        logger.info(f"  ✓ {model} ({duration:.1f}s)")
                        return LLMResponse(
                            success=True,
                            content=content,
                            model_used=model,
                            attempts=total_attempts,
                            duration_seconds=duration,
                        )

                except asyncio.TimeoutError:
                    logger.warning(f"  ⏱ timeout — {model} (tentativa {retry+1}/{max_retries})")
                except aiohttp.ClientError as e:
                    logger.warning(f"  ⚠ erro HTTP — {model}: {e}")
                except Exception as e:
                    logger.error(f"  ✗ erro inesperado — {model}: {e}", exc_info=True)

                if retry < max_retries - 1:
                    wait = min(60, backoff_base ** retry)
                    await asyncio.sleep(wait)

        duration = (datetime.now() - start).total_seconds()
        logger.error(f"  ✗ todos os modelos falharam ({duration:.1f}s, {total_attempts} tentativas)")
        return LLMResponse(
            success=False,
            content="",
            error="Todos os modelos falharam",
            attempts=total_attempts,
            duration_seconds=duration,
        )

    # ── Chamada HTTP única ────────────────────────────────────────────────────

    async def _single_call(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
    ) -> Optional[str]:
        """Realiza uma única chamada HTTP à API Groq."""
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_content},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with self.session.post(self.url, json=payload, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0]["message"]["content"]
                return None

            elif resp.status == 429:
                logger.warning("  ⏳ rate limit (429) — aguardando 10s")
                await asyncio.sleep(10)
                return None

            else:
                text = await resp.text()
                logger.warning(f"  ⚠ API HTTP {resp.status} — {model if 'model' in dir() else ''}: {text[:120]}")
                return None


# =============================================================================
# PROCESSAMENTO EM LOTE — controle de concorrência via Semaphore
# =============================================================================

async def process_students_async(
    client: LLMClientProva,
    tasks: List[Tuple[str, str, Dict]],   # (system_prompt, code_content, metadata)
    max_concurrent: int = 3,
) -> List[Tuple[Dict, LLMResponse]]:
    """
    Processa múltiplos alunos em paralelo com controle de concorrência.

    Args:
        client         : instância de LLMClientProva (já inicializada)
        tasks          : lista de (system_prompt, code_content, metadata)
        max_concurrent : máximo de requisições simultâneas à API

    Returns:
        Lista de (metadata, LLMResponse) na mesma ordem das tasks.
    """
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _one(system_prompt: str, code_content: str, metadata: Dict):
        async with semaphore:
            name = metadata.get('student', 'unknown')
            logger.info(f"  → {name}")
            response = await client.call_grader(system_prompt, code_content)
            return metadata, response

    coros = [_one(sp, cc, meta) for sp, cc, meta in tasks]
    results = await asyncio.gather(*coros, return_exceptions=True)

    valid = []
    for r in results:
        if isinstance(r, Exception):
            logger.error(f"Erro em task: {r}")
        else:
            valid.append(r)
    return valid