import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";

/**
 * The microphone half of hands-free avatar conversation mode.
 *
 * The composer's mic button (`SpeechInputButton`) dictates into the text box and waits for the
 * user to press send. That is the wrong shape for a conversation, so this listens continuously
 * and decides for itself when the user has finished a turn, then hands the whole utterance over
 * to be sent.
 *
 * It is deliberately a separate recognizer from the composer mic: the two must never run at once
 * (they would fight over the microphone and double-transcribe), and this one has to be started
 * and stopped by the conversation state machine rather than by a click.
 */

/**
 * How long a silence ends the user's turn.
 *
 * Azure already endpoints each phrase and raises `recognized` after roughly a second of silence;
 * this waits a further beat on top of that so a mid-sentence pause for breath does not send half
 * a question. Too short truncates people, too long makes the avatar feel unresponsive.
 */
export const UTTERANCE_SILENCE_MS = 1500;

export interface ConversationListenerCallbacks {
    /** The user finished a turn. The text is the whole utterance, not one phrase. */
    onUtterance: (text: string) => void;
    onListeningChange?: (listening: boolean) => void;
    /** Live partial transcript, for showing the user that they are being heard. */
    onInterimTranscript?: (text: string) => void;
    onError?: (message: string) => void;
}

/**
 * Supplies the Speech credentials for the recognizer.
 *
 * Returning the avatar session's own token avoids a second /speech/token round trip, which the
 * microphone would otherwise wait on before it could open.
 */
export type SpeechCredentialsProvider = (forceRefresh: boolean) => Promise<{ token: string; region: string }>;

export class ConversationListener {
    private recognizer: SpeechSDK.SpeechRecognizer | null = null;
    private finalTranscript = "";
    private silenceTimer: number | null = null;
    private closed = false;
    private starting = false;
    private readonly locale: string;
    private readonly getCredentials: SpeechCredentialsProvider;
    private readonly callbacks: ConversationListenerCallbacks;

    constructor(locale: string, getCredentials: SpeechCredentialsProvider, callbacks: ConversationListenerCallbacks) {
        this.locale = locale;
        this.getCredentials = getCredentials;
        this.callbacks = callbacks;
    }

    get isListening(): boolean {
        return this.recognizer !== null;
    }

    private clearSilenceTimer() {
        if (this.silenceTimer !== null) {
            window.clearTimeout(this.silenceTimer);
            this.silenceTimer = null;
        }
    }

    /** Restarted on every scrap of speech, so the clock only runs while the user is quiet. */
    private armSilenceTimer() {
        this.clearSilenceTimer();
        this.silenceTimer = window.setTimeout(() => {
            this.flush();
        }, UTTERANCE_SILENCE_MS);
    }

    private flush() {
        this.clearSilenceTimer();
        const text = this.finalTranscript.trim();
        this.finalTranscript = "";
        if (!text || this.closed) {
            return;
        }
        this.callbacks.onInterimTranscript?.("");
        this.callbacks.onUtterance(text);
    }

    async start(): Promise<void> {
        if (this.recognizer || this.starting || this.closed) {
            return;
        }
        this.starting = true;

        try {
            try {
                await this.startWith(false);
            } catch (firstAttempt) {
                // The reused session token is normally valid, but if it genuinely has expired the
                // only symptom is a failure to start. Pay for a fresh one once rather than
                // leaving the user with a dead microphone.
                if (this.closed) {
                    throw firstAttempt;
                }
                await this.startWith(true);
            }
        } catch (error) {
            this.callbacks.onError?.(error instanceof Error ? error.message : String(error));
        } finally {
            this.starting = false;
        }
    }

    private async startWith(forceRefresh: boolean): Promise<void> {
        {
            const speechToken = await this.getCredentials(forceRefresh);
            if (this.closed) {
                return;
            }

            const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(speechToken.token, speechToken.region);
            speechConfig.speechRecognitionLanguage = this.locale;

            const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
            const recognizer = new SpeechSDK.SpeechRecognizer(speechConfig, audioConfig);

            recognizer.recognizing = (_sender, event) => {
                const interim = event.result?.text ?? "";
                this.callbacks.onInterimTranscript?.([this.finalTranscript, interim].filter(Boolean).join(" ").trim());
                // Partial results mean the user is still talking — hold the turn open.
                this.armSilenceTimer();
            };

            recognizer.recognized = (_sender, event) => {
                if (event.result.reason !== SpeechSDK.ResultReason.RecognizedSpeech) {
                    return;
                }
                const transcript = event.result.text.trim();
                if (!transcript) {
                    return;
                }
                this.finalTranscript = [this.finalTranscript, transcript].filter(Boolean).join(" ").trim();
                this.callbacks.onInterimTranscript?.(this.finalTranscript);
                this.armSilenceTimer();
            };

            recognizer.canceled = (_sender, event) => {
                if (event.reason === SpeechSDK.CancellationReason.Error) {
                    this.callbacks.onError?.(event.errorDetails || "Speech input is not available.");
                }
                void this.stop();
            };

            await new Promise<void>((resolve, reject) => {
                recognizer.startContinuousRecognitionAsync(
                    () => resolve(),
                    error => reject(new Error(String(error)))
                );
            });

            if (this.closed) {
                // Stopped while the microphone was being acquired; don't leave it open.
                recognizer.close();
                return;
            }

            this.recognizer = recognizer;
            this.callbacks.onListeningChange?.(true);
        }
    }

    /**
     * Release the microphone.
     *
     * Conversation mode is half-duplex: this is called before the avatar speaks so the recognizer
     * cannot transcribe the avatar's own voice back as if it were the user. Any partial utterance
     * is discarded rather than sent, because it was cut off by the state machine, not by the user
     * finishing a thought.
     */
    async stop(): Promise<void> {
        this.clearSilenceTimer();
        this.finalTranscript = "";
        this.callbacks.onInterimTranscript?.("");

        const recognizer = this.recognizer;
        this.recognizer = null;
        if (!recognizer) {
            return;
        }

        await new Promise<void>(resolve => {
            recognizer.stopContinuousRecognitionAsync(
                () => resolve(),
                () => resolve()
            );
        });

        try {
            recognizer.close();
        } catch {
            // Ignore teardown races.
        }

        this.callbacks.onListeningChange?.(false);
    }

    close(): void {
        this.closed = true;
        void this.stop();
    }
}
