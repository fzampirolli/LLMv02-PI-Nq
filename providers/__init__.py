import logging
from .groq import GroqClient
from .deepseek import DeepSeekClient
from .gemini import GeminiClient

logger = logging.getLogger(__name__)

def get_client(config: dict):
    """
    Fábrica de Clientes LLM.
    Retorna uma instância do provedor configurado no config.yaml.
    """
    # Busca o provedor no config, padronizando para 'groq' se não existir
    provider_name = config.get('llm', {}).get('provider', 'groq').lower().strip()
    
    mapping = {
        "groq": GroqClient,
        "deepseek": DeepSeekClient,
        "gemini": GeminiClient
    }
    
    if provider_name not in mapping:
        logger.error(f"❌ Provedor '{provider_name}' não suportado. "
                     f"Opções válidas: {list(mapping.keys())}")
        raise ValueError(f"Provider {provider_name} desconhecido.")

    logger.info(f"🔌 Inicializando provedor: {provider_name.upper()}")
    
    # Instancia o cliente passando o dicionário de configuração e o nome do provedor
    return mapping[provider_name](config, provider_name)