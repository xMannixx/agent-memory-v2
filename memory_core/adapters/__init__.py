"""Memory Core v2 Adapters package.

Provides LLM providers and platform bridges for Memory Core.
"""

from .openai_provider import OpenAILlm

__all__ = [
    "OpenAILlm",
]

# Optional providers (require no external deps — use stdlib urllib only)
try:
    from .ollama_provider import OllamaProvider
    __all__.append("OllamaProvider")
except ImportError:
    pass

try:
    from .openrouter_provider import OpenRouterProvider
    __all__.append("OpenRouterProvider")
except ImportError:
    pass

try:
    from .openclaw_bridge import MemoryBridge
    __all__.append("MemoryBridge")
except ImportError:
    pass
