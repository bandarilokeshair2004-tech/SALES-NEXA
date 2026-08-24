import json
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "translations"

LANGUAGES = {
    "en": ("English", "en-US"), "hi": ("Hindi", "hi-IN"), "bn": ("Bengali", "bn-IN"),
    "te": ("Telugu", "te-IN"), "mr": ("Marathi", "mr-IN"), "ta": ("Tamil", "ta-IN"),
    "gu": ("Gujarati", "gu-IN"), "kn": ("Kannada", "kn-IN"), "ml": ("Malayalam", "ml-IN"),
    "pa": ("Punjabi", "pa-IN"), "ur": ("Urdu", "ur-IN"), "or": ("Odia", "or-IN"),
    "as": ("Assamese", "as-IN"), "sa": ("Sanskrit", "sa-IN"), "ne": ("Nepali", "ne-NP"),
    "fr": ("French", "fr-FR"), "de": ("German", "de-DE"), "es": ("Spanish", "es-ES"),
    "ar": ("Arabic", "ar-SA"), "ja": ("Japanese", "ja-JP"),
}


def language_options():
    return [{"code": code, "name": value[0], "speech": value[1]} for code, value in LANGUAGES.items()]


def language_name(code):
    return LANGUAGES.get(code, LANGUAGES["en"])[0]

def load_language(language="en"):
    path = BASE / f"{language}.json"
    if not path.exists():
        path = BASE / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))
