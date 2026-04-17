"""
`__init__.py` - Esta pasta é um pacote. Execute este código ao importar o diretório.

O arquivo `__init__.py` dentro da pasta `providers/` tem como objetivo principal transformar o 
diretório em um **pacote Python** e atuar como uma **Fábrica de Clientes (Factory)** para os 
diferentes provedores de IA.

Abaixo, detalho as funções específicas que ele desempenha no seu projeto:

### 1. Centralização e Exportação
O arquivo importa as classes específicas de cada arquivo (`groq.py`, `deepseek.py`, `gemini.py`) 
para que quem utilize o pacote não precise saber o nome exato do arquivo interno, apenas o nome 
do pacote.
* Ele expõe `GroqClient`, `DeepSeekClient` e `GeminiClient` de forma organizada.

### 2. Implementação do Padrão Factory (Fábrica)
A função `get_client(config: dict)` funciona como uma interface única para o restante do sistema. 
* **Encapsulamento:** O código principal do seu sistema não precisa saber como instanciar um cliente 
da Gemini ou da DeepSeek. Ele apenas chama `get_client` e passa a configuração.
* **Mapeamento Dinâmico:** Ele utiliza um dicionário (`mapping`) para associar a string do provedor 
(vinda do `config.yaml`) à classe Python correspondente.

### 3. Padronização e Segurança
O arquivo garante que o sistema seja robusto contra erros de configuração:
* **Tratamento de Strings:** Ele normaliza o nome do provedor usando `.lower().strip()` para evitar 
erros por espaços extras ou letras maiúsculas no arquivo YAML.
* **Fallback:** Se nenhum provedor for especificado, ele define o `groq` como padrão.
* **Validação:** Caso o usuário digite um provedor não suportado, o arquivo dispara um erro 
(`ValueError`) informando quais são as opções válidas, impedindo que o sistema tente rodar com 
dados inválidos.

### 4. Log de Inicialização
Ele fornece feedback visual no terminal através do `logger`, confirmando qual provedor está sendo 
inicializado para facilitar o monitoramento do processo de correção.

---
**Resumo técnico:** Sem este arquivo, você teria que importar manualmente cada classe no seu script 
principal e fazer vários blocos de `if/else` para decidir qual usar. Com o `__init__.py`, essa lógica 
fica isolada, tornando o sistema modular e fácil de expandir (basta adicionar uma nova 
linha no `mapping` para suportar uma nova IA).
"""


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