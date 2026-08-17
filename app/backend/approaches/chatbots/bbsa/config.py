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
    # Austrian German for an Austrian audience, matching the live avatar's voice. The
    # deployment-wide default is de-DE-Florian:DragonHDLatestNeural, which is a higher-fidelity
    # HD voice but German-German; there is no de-AT HD voice, so this trades fidelity for the
    # right accent. Overriding here rather than via AZURE_SPEECH_SERVICE_VOICE keeps every other
    # speech-enabled bot on the deployment default.
    speech_voice="de-AT-JonasNeural",
)
