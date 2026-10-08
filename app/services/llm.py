from groq import Groq


class LLMClient:
    """Тонка обгортка над Groq, щоб модель і ключ брались з конфігу."""

    def __init__(self, api_key: str | None, model: str):
        if not api_key or api_key == "your_groq_api_key_here":
            raise RuntimeError("GROQ_API_KEY не задано. Додай його у файл .env")
        self._client = Groq(api_key=api_key)
        self.model = model

    def complete(self, messages: list[dict]) -> str:
        completion = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
        )
        return completion.choices[0].message.content
