from approaches.chatbots.chatbot_config import ChatbotConfig

config = ChatbotConfig(
    name="cbtx",
    chatgpt_model="gpt-4.1",
    chatgpt_deployment="gpt-4.1",
    prompt_mode="override",
    # cbtx (CABLETEX) content is ingested as uploaded source documents under the "cbtx"
    # category, so cite the storage blob (default) rather than an external page url.
    citation_target="sourcepage",
    # No support_email set yet: the fallback in sampleprompt.py stays generic (points the
    # user at CABLETEX's own support/contact channels) and does not reference {{SUPPORT_EMAIL}}.
    # language_locale is left unset so responses follow the UI language, defaulting to German.
)
