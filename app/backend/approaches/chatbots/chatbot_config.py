from dataclasses import dataclass
from typing import Literal, Optional


@dataclass
class ChatbotConfig:
    name: str
    # LLM override — None means use the global default
    chatgpt_model: Optional[str] = None
    chatgpt_deployment: Optional[str] = None  # defaults to chatgpt_model if None
    reasoning_effort: Optional[str] = None
    # Prompt configuration
    support_email: Optional[str] = None
    # Retrieval
    citation_target: Literal["sourcepage", "url"] = "sourcepage"
