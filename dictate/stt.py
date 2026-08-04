"""Google Cloud Speech-to-Text v2 — streaming sa interim (delimicnim) rezultatima."""

from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech


def make_client(cfg: dict) -> SpeechClient:
    location = cfg.get("location", "global")
    opts = None
    if location != "global":
        opts = ClientOptions(api_endpoint=f"{location}-speech.googleapis.com")
    return SpeechClient(client_options=opts)


def recognizer_path(project: str, location: str) -> str:
    # "_" znaci: koristi konfiguraciju poslatu u zahtevu, bez unapred napravljenog recognizer-a.
    return f"projects/{project}/locations/{location}/recognizers/_"


def build_streaming_config(cfg: dict) -> cloud_speech.StreamingRecognitionConfig:
    recognition = cloud_speech.RecognitionConfig(
        explicit_decoding_config=cloud_speech.ExplicitDecodingConfig(
            encoding=cloud_speech.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=cfg["sample_rate"],
            audio_channel_count=1,
        ),
        language_codes=list(cfg["language_codes"]),
        model=cfg["model"],
        features=cloud_speech.RecognitionFeatures(
            enable_automatic_punctuation=bool(cfg.get("punctuation", True)),
        ),
    )
    return cloud_speech.StreamingRecognitionConfig(
        config=recognition,
        streaming_features=cloud_speech.StreamingRecognitionFeatures(
            interim_results=True,
        ),
    )


def stream(client, cfg, project, chunk_iter, on_interim, on_final):
    """Salje audio Google-u i zove callback-e kako rezultati stizu.

    on_interim(tekst)  — delimicni rezultat, menja se dok pricas
    on_final(tekst)    — potvrdjen segment, vise se ne menja

    Vraca ceo prepoznat tekst.
    """
    location = cfg.get("location", "global")
    recognizer = recognizer_path(project, location)
    streaming_config = build_streaming_config(cfg)

    def requests():
        yield cloud_speech.StreamingRecognizeRequest(
            recognizer=recognizer,
            streaming_config=streaming_config,
        )
        for chunk in chunk_iter:
            yield cloud_speech.StreamingRecognizeRequest(audio=chunk)

    finals: list[str] = []
    for response in client.streaming_recognize(requests=requests()):
        for result in response.results:
            if not result.alternatives:
                continue
            text = result.alternatives[0].transcript
            if result.is_final:
                cleaned = text.strip()
                if cleaned:
                    finals.append(cleaned)
                    on_final(cleaned)
            else:
                on_interim(text.strip())

    return join_segments(finals)


def join_segments(segments: list[str]) -> str:
    return " ".join(s for s in segments if s).strip()
