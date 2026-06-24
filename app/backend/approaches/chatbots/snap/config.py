from approaches.chatbots.chatbot_config import ChatbotConfig

config = ChatbotConfig(
    name="snap",
    chatgpt_model="gpt-4.1-mini",
    chatgpt_deployment="gpt-4.1-mini",
    support_email="info@snap.de",
    prompt_mode="override",
    # snap content is the snap.de website feed (data/snap.json); each record carries a
    # first-class live page url, so cite the public page instead of the storage blob.
    citation_target="url",
)
