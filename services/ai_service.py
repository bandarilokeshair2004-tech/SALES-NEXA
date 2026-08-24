import json
import urllib.error
import urllib.request


def answer_with_ai(question, context, language, api_key, model, base_url, timeout=20):
    """Ask an OpenAI-compatible chat API, returning None when it is unavailable."""
    if not api_key or not model:
        return None
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": [
            {"role": "system", "content": (
                "You are NexaBot, a concise multilingual retail business assistant. "
                "Answer every kind of question helpfully, but never invent SalesNexa facts. "
                "For business questions, use only the supplied JSON snapshot and say when it "
                "does not contain enough information. Reply entirely in the requested language. "
                "Requested language: " + language + "\nBusiness snapshot:\n" + json.dumps(context, default=str)
            )},
            {"role": "user", "content": question},
        ],
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        answer = result["choices"][0]["message"]["content"].strip()
        return answer or None
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, OSError):
        return None