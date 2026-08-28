from __future__ import annotations

import asyncio
import json

import httpx

from backend.copilot.provider import (
    AnthropicMessagesProvider,
    OpenAIResponsesProvider,
    ProviderRequest,
)


def provider_request() -> ProviderRequest:
    return ProviderRequest(
        mode="FOLLOW_UP",
        system_prompt="Return only validated JSON.",
        input_payload={"incident_id": "INC-TEST"},
        response_schema={"type": "object", "properties": {}, "additionalProperties": False},
        max_output_tokens=512,
        tools=(
            {
                "name": "get_incident_overview",
                "description": "Read only.",
                "input_schema": {
                    "type": "object",
                    "properties": {"incident_id": {"type": "string"}},
                    "required": ["incident_id"],
                    "additionalProperties": False,
                },
            },
        ),
    )


def test_openai_adapter_uses_responses_schema_reasoning_and_native_tools() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert request.headers["authorization"].startswith("Bearer ")
            assert payload["reasoning"] == {"effort": "medium"}
            assert payload["text"]["format"]["type"] == "json_schema"
            assert payload["tools"][0]["type"] == "function"
            return httpx.Response(
                200,
                json={
                    "id": "response-test",
                    "output_text": '{"safe":true}',
                    "usage": {"input_tokens": 10, "output_tokens": 4},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(
                model_id="test-terra-model",
                api_key="test-only-redacted",
                endpoint="https://provider.invalid/v1/responses",
                timeout_seconds=1,
                client=client,
            )
            response = await provider.generate(provider_request())
            assert response.output == {"safe": True}
            assert response.provider == "openai"
            assert response.input_tokens == 10

    asyncio.run(scenario())


def test_anthropic_adapter_uses_structured_output_balanced_effort_and_tools() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            assert request.headers["x-api-key"] == "test-only-redacted"
            assert payload["output_config"]["effort"] == "medium"
            assert payload["output_config"]["format"]["type"] == "json_schema"
            assert payload["tools"][0]["input_schema"]["additionalProperties"] is False
            return httpx.Response(
                200,
                json={
                    "id": "message-test",
                    "content": [{"type": "text", "text": '{"safe":true}'}],
                    "usage": {"input_tokens": 11, "output_tokens": 5},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicMessagesProvider(
                model_id="test-claude-model",
                api_key="test-only-redacted",
                endpoint="https://provider.invalid/v1/messages",
                timeout_seconds=1,
                client=client,
            )
            response = await provider.generate(provider_request())
            assert response.output == {"safe": True}
            assert response.provider == "anthropic"
            assert response.output_tokens == 5

    asyncio.run(scenario())
