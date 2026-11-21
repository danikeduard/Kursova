from app.providers import create_client


def test_openai_provider_constructs_openai_sdk_client_without_network():
    captured = {}

    def fake_openai_client(**kwargs):
        captured.update(kwargs)
        return object()

    client = create_client(
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "DEMO_MODE": False,
        },
        provider="openai",
        openai_client=fake_openai_client,
    )

    assert client is not None
    assert captured == {"api_key": "test-key", "base_url": "https://api.openai.com/v1"}
