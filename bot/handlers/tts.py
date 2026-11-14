import io
import logging
from config import TTS_ENABLED, TTS_LANG, TTS_SPEAKER, TTS_SAMPLE_RATE

logger = logging.getLogger(__name__)

_model = None
_loaded = False


def _load():
    global _model, _loaded
    if _loaded:
        return _model
    _loaded = True
    if not TTS_ENABLED:
        return None
    try:
        import torch
        _model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-models",
            model="silero_tts",
            language=TTS_LANG,
            speaker=TTS_SPEAKER,
        )
    except Exception:
        logger.exception("Silero TTS load failed — озвучка отключена")
        _model = None
    return _model


def synthesize(text: str):
    model = _load()
    if not model:
        return None
    try:
        import soundfile as sf
        audio = model.apply_tts(text=text, speaker=TTS_SPEAKER, sample_rate=TTS_SAMPLE_RATE)
        buf = io.BytesIO()
        sf.write(buf, audio.numpy(), TTS_SAMPLE_RATE, format="OGG", subtype="OPUS")
        return buf.getvalue()
    except Exception:
        logger.exception("TTS synth failed")
        return None