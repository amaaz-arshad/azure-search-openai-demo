from approaches.chatbots.chatbot_config import ChatbotConfig

config = ChatbotConfig(
    name="bbsa",
    chatgpt_model="gpt-4.1",
    chatgpt_deployment="gpt-4.1",
    support_email="office@bbsa.tirol",
    prompt_mode="override",
    language_locale="German",
    # The corpus is scraped web content: every record carries the live breitband.tirol
    # (or <gemeinde>.breitband.tirol) page URL, so citations link to the public page.
    citation_target="url",
)
