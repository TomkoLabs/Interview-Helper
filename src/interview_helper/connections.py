"""Credential-free connection preferences; credentials stay in backend-owned files."""

import json
from .cloud_auth import account_path
from .config import Endpoint
from .storage import atomic_json


def cloud_endpoint(
    config,
    provider,
    account="",
    model="gpt-6.1-sol",
    reasoning="low",
    tier="default",
    transport="http",
):
    if provider not in {"chatgpt", "openai_api"}:
        raise ValueError("Unknown cloud connection")
    if provider == "chatgpt" and tier != "default":
        raise ValueError("Subscription tier overrides are not enabled")
    return Endpoint(
        name="ChatGPT plan" if provider == "chatgpt" else "OpenAI API",
        base_url="https://api.openai.com/v1",
        model=model,
        backend=provider,
        api_key_env="OPENAI_API_KEY",
        api_key_file=str(config.root / ".local" / "openai-api-key")
        if provider == "openai_api"
        else "",
        transport=transport,
        compact=True,
        host_id="openai-cloud",
        oauth_file=str(account_path(config.root / ".local" / "chatgpt", account))
        if provider == "chatgpt"
        else "",
        parameters={
            "reasoning_effort": reasoning,
            **(
                {"service_tier": tier, "max_output_tokens": 1024}
                if provider == "openai_api"
                else {}
            ),
        },
        timeout=120,
    )


def resolve(config, selection):
    if not isinstance(selection, dict) or set(selection) - {
        "provider",
        "account",
        "model",
        "reasoning",
        "tier",
        "transport",
    }:
        raise ValueError("Invalid saved connection preference")
    if not all(isinstance(value, str) for value in selection.values()):
        raise ValueError("Connection preference fields must be strings")
    if selection == {"provider": "local"}:
        return config.local_endpoints, config.local_strategy
    return [cloud_endpoint(config, **selection)], "single"


def restore(config):
    if config.selection_file.exists():
        try:
            selection = json.loads(config.selection_file.read_text())
            config.endpoints, config.strategy = resolve(config, selection)
        except (OSError, ValueError, TypeError):
            # Never silently revert to a paid/cloud default after corrupt local preference.
            raise ValueError(
                "Saved connection preference invalid; restore or remove it explicitly"
            ) from None


def select(config, selection):
    endpoints, strategy = resolve(config, selection)
    selection = dict(selection)
    if selection.get("provider") != "chatgpt":
        selection.pop("account", None)
    config.selection_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_json(config.selection_file, selection)
    config.endpoints, config.strategy = endpoints, strategy
