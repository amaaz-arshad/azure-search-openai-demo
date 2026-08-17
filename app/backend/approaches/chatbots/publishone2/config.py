from approaches.chatbots.chatbot_config import ChatbotConfig

config = ChatbotConfig(
    name="publishone2",
    chatgpt_model="gpt-4.1",
    chatgpt_deployment="gpt-4.1",
    support_email="helpdesk@publishone.nl",
    prompt_mode="override",
    # Unlike publishone (pinned to English), publishone2 answers in the language of the UI locale
    # the frontend resolved from the browser, so leaving this unset is deliberate: it makes
    # render_chatbot_prompt fall through to the request language.
    language_locale=None,
    citation_target="url",
)
