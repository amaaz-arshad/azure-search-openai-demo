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
    prompt_mode: Literal["inject", "override"] = "override"
    language_locale: Optional[str] = None  # defaults to "German" if None
    # Retrieval
    citation_target: Literal["sourcepage", "url"] = "sourcepage"
    # Speech — voice for the per-answer "speak answer" button (Azure TTS).
    # None means use the deployment-wide AZURE_SPEECH_SERVICE_VOICE. Set this only when a bot
    # needs a different voice from the rest of the deployment: that env var is shared by every
    # speech-enabled bot, so changing it to suit one of them repoints all of them.
    speech_voice: Optional[str] = None
