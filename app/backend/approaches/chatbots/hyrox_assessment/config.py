from approaches.chatbots.chatbot_config import ChatbotConfig

# Interactive assessment bot — see sampleprompt.py / questions.py.
# language_locale is intentionally left None so the prompt honours the per-request
# language supplied by the LMS (resolved from the request "language" override).
config = ChatbotConfig(
    name="hyrox-assessment",
    chatgpt_model="gpt-5.4-mini",
    chatgpt_deployment="gpt-5.4-mini",
    reasoning_effort="high",
    prompt_mode="override",
    support_email="hyrox@lemon-systems.com",
)
