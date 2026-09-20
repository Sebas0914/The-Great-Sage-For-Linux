"""Contract checks for provider privacy and routing policy."""

import os

from great_sage.core import ai_settings, modes


class FakeLocal:
    pass


def run():
    fallback = FakeLocal()

    # Private mode must never construct an online provider.
    private = dict(ai_settings.DEFAULTS, mode="private", chat_provider="nvidia")
    provider, label = ai_settings.build_provider(private, fallback)
    assert provider is fallback
    assert "local-only" in label.lower()

    # Explicit LOCAL_ONLY routing must win even if the UI selected NVIDIA.
    old = os.environ.get("GREAT_SAGE_AI_MODE")
    try:
        os.environ["GREAT_SAGE_AI_MODE"] = "local_only"
        online = dict(ai_settings.DEFAULTS, mode="companion",
                      chat_provider="nvidia")
        provider, label = ai_settings.build_provider(online, fallback)
        assert provider is fallback
        assert label == "Ollama / Local"
    finally:
        if old is None:
            os.environ.pop("GREAT_SAGE_AI_MODE", None)
        else:
            os.environ["GREAT_SAGE_AI_MODE"] = old

    # LOCAL_ONLY in the global settings is an independent hard stop.
    from great_sage.config import settings
    old_local_only = getattr(settings, "LOCAL_ONLY", False)
    try:
        settings.LOCAL_ONLY = True
        configured = dict(ai_settings.DEFAULTS, mode="companion",
                          chat_provider="nvidia", keys={"nvidia": "test-key"})
        provider, label = ai_settings.build_provider(configured, fallback)
        assert provider is fallback
        assert "local-only" in label.lower()
    finally:
        settings.LOCAL_ONLY = old_local_only

    # A missing NVIDIA key must fail closed to the local provider.
    missing_key = dict(ai_settings.DEFAULTS, mode="companion",
                       chat_provider="nvidia", keys={})
    provider, label = ai_settings.build_provider(missing_key, fallback)
    assert provider is fallback
    assert "NVIDIA key missing" in label

    # Web access needs both the explicit permission and a web-capable mode.
    assert not ai_settings.web_allowed(
        dict(ai_settings.DEFAULTS, allow_web=False, mode="online")
    )
    assert ai_settings.web_allowed(
        dict(ai_settings.DEFAULTS, allow_web=True, mode="online")
    )
    assert not ai_settings.web_allowed(
        dict(ai_settings.DEFAULTS, allow_web=True, mode="private")
    )

    # The mode table itself must distinguish online and private operation.
    assert modes.get("online").allow_online
    assert not modes.get("private").allow_online
    assert not modes.get("private").allow_web

    print("OK - provider privacy and routing policy")


if __name__ == "__main__":
    run()
