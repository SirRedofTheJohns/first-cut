"""Structured output that degrades gracefully across providers.

Native structured output (tool calling / JSON schema) is used when the model supports it.
Otherwise the schema goes into the prompt and the reply is parsed as JSON. Either way,
validation errors are fed back to the model for another attempt.
"""

import json
import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel, ValidationError

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class StructuredOutputError(RuntimeError):
    pass


def structured_call[T: BaseModel](
    llm: BaseChatModel,
    schema: type[T],
    messages: Sequence[BaseMessage],
    *,
    fallback: BaseChatModel | None = None,
    max_attempts: int = 3,
) -> T:
    messages = list(messages)
    try:
        native = _native(llm, schema)
        if fallback is not None:
            # Fallbacks wrap the *structured* runnables: `llm.with_fallbacks()` returns a plain
            # Runnable that no longer has `with_structured_output`. They trigger on provider
            # errors (429, 5xx), not on invalid output, which the loop below handles.
            native = native.with_fallbacks([_native(fallback, schema)])
    except NotImplementedError:
        native = None
        messages.append(HumanMessage(_json_instructions(schema)))

    error: Exception | str | None = None
    for _ in range(max_attempts):
        if native is not None:
            try:
                result = native.invoke(messages)
            except Exception as exc:
                # Providers that validate output server-side (Groq json_schema) answer an
                # invalid generation with HTTP 400. Treat that like invalid output and retry;
                # anything else (auth, quota, network) is a real error and propagates.
                if getattr(exc, "status_code", None) != 400:
                    raise
                result = {"parsed": None, "parsing_error": exc}
            if result["parsed"] is not None:
                return result["parsed"]
            error = result["parsing_error"] or "the model returned no structured output"
        else:
            reply = llm.invoke(messages)
            try:
                return schema.model_validate_json(_extract_json(reply.text))
            except (ValidationError, ValueError) as exc:
                error = exc
        messages.append(
            HumanMessage(f"Your previous answer was invalid:\n{error}\nTry again and fix it.")
        )
    raise StructuredOutputError(
        f"{schema.__name__}: no valid output after {max_attempts} attempts: {error}"
    )


def _native(llm: BaseChatModel, schema: type[BaseModel]):
    # Groq's default (a forced tool call) failed 1 in 4 with gpt-oss ("Tool choice is
    # required, but model did not call a tool"); its native JSON-schema mode went 4/4.
    kwargs = {"method": "json_schema"} if llm._llm_type == "groq-chat" else {}
    return llm.with_structured_output(schema, include_raw=True, **kwargs)


def _json_instructions(schema: type[BaseModel]) -> str:
    return (
        "Respond with a single JSON object, and nothing else, that validates against this "
        f"JSON schema:\n{json.dumps(schema.model_json_schema())}"
    )


def _extract_json(text: str) -> str:
    match = _JSON_BLOCK.search(text)
    if not match:
        raise ValueError("no JSON object found in the reply")
    return match.group(0)
