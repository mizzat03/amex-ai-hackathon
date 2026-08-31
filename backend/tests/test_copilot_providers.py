from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from backend.copilot.models import CopilotDraft
from backend.copilot.provider import (
    AnthropicMessagesProvider,
    OpenAIResponsesProvider,
    ProviderError,
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


def test_openai_adapter_converts_pydantic_and_tool_schemas_to_strict_json_schema() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            payload = json.loads(request.content)
            response_schema = payload["text"]["format"]["schema"]
            response_properties = response_schema["properties"]
            assert response_schema["required"] == list(response_properties)
            assert response_schema["additionalProperties"] is False
            assert "default" not in response_properties["leading_hypothesis_id"]

            point_schema = response_schema["$defs"]["DraftEvidencePoint"]
            assert point_schema["required"] == list(point_schema["properties"])
            assert point_schema["additionalProperties"] is False

            tool_schema = payload["tools"][0]["parameters"]
            assert tool_schema["required"] == list(tool_schema["properties"])
            assert tool_schema["additionalProperties"] is False
            optional_evidence_types = {
                branch.get("type")
                for branch in tool_schema["properties"]["evidence_id"]["anyOf"]
            }
            assert optional_evidence_types == {
                "string",
                "null",
            }
            return httpx.Response(200, json={"id": "response-test", "output_text": '{"safe":true}'})

        request = provider_request()
        response_schema = CopilotDraft.model_json_schema()
        request = ProviderRequest(
            mode=request.mode,
            system_prompt=request.system_prompt,
            input_payload=request.input_payload,
            response_schema=response_schema,
            max_output_tokens=request.max_output_tokens,
            tools=(
                {
                    "name": "get_incident_overview",
                    "description": "Read only.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "incident_id": {"type": "string"},
                            "evidence_id": {"type": "string"},
                        },
                        "required": ["incident_id"],
                        "additionalProperties": False,
                    },
                },
            ),
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAIResponsesProvider(
                model_id="test-terra-model",
                api_key="test-only-redacted",
                endpoint="https://provider.invalid/v1/responses",
                timeout_seconds=1,
                client=client,
            )
            await provider.generate(request)
        assert response_schema["required"] != list(response_schema["properties"])
        assert response_schema["properties"]["leading_hypothesis_id"]["default"] is None

    asyncio.run(scenario())


def test_openai_adapter_classifies_token_exhaustion_as_incomplete_not_invalid_schema() -> None:
    async def scenario() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            del request
            return httpx.Response(
                200,
                json={
                    "id": "response-incomplete",
                    "status": "incomplete",
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "output": [{"type": "reasoning", "summary": []}],
                    "usage": {
                        "input_tokens": 1200,
                        "output_tokens": 512,
                        "output_tokens_details": {"reasoning_tokens": 512},
                    },
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
            with pytest.raises(ProviderError) as caught:
                await provider.generate(provider_request())

        assert caught.value.reason_code == "provider_incomplete"
        assert caught.value.retryable is True
        assert caught.value.request_id == "response-incomplete"
        assert caught.value.input_tokens == 1200
        assert caught.value.output_tokens == 512

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
