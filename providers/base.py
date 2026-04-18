import asyncio
import time
import logging
import random
import re
import aiohttp
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# =============================================================================
# ESTRUTURA DE RESPOSTA PADRONIZADA
# =============================================================================

@dataclass
class LLMResponse:
    """Resposta unificada para qualquer provedor de IA."""
    success: bool
    content: str = ""
    model_used: str = ""
    duration: float = 0.0
    error: str = ""

# =============================================================================
# CLASSE BASE (TEMPLATE METHOD)
# =============================================================================

class BaseLLMClient:
    """
    Classe base que gerencia a lógica comum a todos os provedores:
    - Iteração sobre lista de modelos (fallback)
    - Sistema de retentativas (retry)
    - Controle de tempo de execução
    """
    
    def __init__(self, config: Dict, provider_name: str):
        self.provider_cfg = config.get(provider_name, {})
        
        # Normaliza modelos para lista
        models = self.provider_cfg.get('models', [])
        self.models = [models] if isinstance(models, str) else list(models)
        
        self.api_key = self.provider_cfg.get('api_key')
        self.api_url = self.provider_cfg.get('api_url')
        self.temperature = self.provider_cfg.get('temperature', 0.3)
        
        # Configuração de timeout padrão (120 segundos)
        self.timeout = aiohttp.ClientTimeout(total=120)

    async def chat_completion(self, system_prompt: str, user_content: str) -> LLMResponse:
        """
        Template Method: Orquestra a tentativa de obter uma resposta.
        Tenta cada modelo da lista; para cada modelo, tenta até 3 vezes em caso de erro.
        """
        start_time = time.time()
        last_error = "Nenhum modelo configurado"

        # Embaralha os modelos a cada chamada para distribuir a carga
        modelos = self.models.copy()
        random.shuffle(modelos)

        for model in self.models:
            for attempt in range(3):  # Máximo de 3 tentativas por modelo
                try:
                    logger.debug(f"Tentando {model} (atempto {attempt+1})...")
                    
                    content = await self._raw_call(model, system_prompt, user_content)
                    
                    if not content or len(content.strip()) < 5:
                        raise ValueError("Resposta da IA vazia ou muito curta.")

                    return LLMResponse(
                        success=True,
                        content=content,
                        model_used=model,
                        duration=time.time() - start_time
                    )

                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"⚠️ Falha no modelo {model} [Tentativa {attempt+1}]: {last_error}")

                    # Respeita o tempo sugerido pelo Groq no erro 429
                    retry_after = None
                    if "429" in last_error:
                        m = re.search(r'(?:try again in|retry after)\s*([\d.]+)\s*s', last_error, re.IGNORECASE)
                        if m:
                            retry_after = float(m.group(1)) + 0.5

                    wait = retry_after if retry_after else 2 ** (attempt + 1)
                    await asyncio.sleep(wait)

                    if any(x in last_error.lower() for x in ["401", "unauthorized", "402", "balance"]):
                        break

        return LLMResponse(
            success=False,
            error=f"Todos os modelos falharam. Último erro: {last_error}",
            duration=time.time() - start_time
        )

    async def _raw_call(self, model: str, system: str, user: str) -> str:
        """
        Método Abstrato: Deve ser implementado pelas subclasses 
        (Groq, DeepSeek, Gemini) para lidar com suas APIs específicas.
        """
        raise NotImplementedError("As subclasses devem implementar o método _raw_call")