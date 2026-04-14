from approaches.chatbots.chatbot_config import ChatbotConfig

config = ChatbotConfig(
    name="fhg",
    chatgpt_model="gpt-4.1-mini",
    chatgpt_deployment="gpt-4.1-mini",
    prompt_mode="inject",
    citation_target="url",
)
