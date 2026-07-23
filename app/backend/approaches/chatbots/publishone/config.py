from approaches.chatbots.chatbot_config import ChatbotConfig

config = ChatbotConfig(
    name="publishone",
    chatgpt_model="gpt-4.1",
    chatgpt_deployment="gpt-4.1",
    support_email="helpdesk@publishone.nl",
    prompt_mode="override",
    language_locale="English",
    citation_target="url",
)
