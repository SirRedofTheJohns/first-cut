import json

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from firstcut.schemas import PageCopy
from firstcut.structured import StructuredOutputError, structured_call
from tests.fakes import ScriptedChatModel, page_copy

PROMPT = [HumanMessage("write it")]


def test_fallback_extracts_json_wrapped_in_prose():
    llm = ScriptedChatModel(respond=lambda _: f"Sure!\n```json\n{json.dumps(page_copy())}\n```")
    result = structured_call(llm, PageCopy, PROMPT)
    assert result.call_to_action == "Pre-order now"
    # The schema was injected into the prompt because the fake has no native support.
    assert "JSON schema" in llm.calls[0][-1].content


def test_fallback_retries_with_the_validation_error():
    replies = iter(['{"meta_description": "x"}', json.dumps(page_copy())])
    llm = ScriptedChatModel(respond=lambda _: next(replies))
    structured_call(llm, PageCopy, PROMPT)
    assert len(llm.calls) == 2
    assert "previous answer was invalid" in llm.calls[1][-1].content


def test_gives_up_after_max_attempts():
    llm = ScriptedChatModel(respond=lambda _: "no json here")
    with pytest.raises(StructuredOutputError):
        structured_call(llm, PageCopy, PROMPT, max_attempts=2)
    assert len(llm.calls) == 2


class NativeFake(ScriptedChatModel):
    """Simulates a provider with native structured output that fails once."""

    def with_structured_output(self, schema, *, include_raw=False, **kwargs):
        def invoke(messages):
            self.calls.append(messages)
            if len(self.calls) == 1:
                return {"raw": None, "parsed": None, "parsing_error": ValueError("bad args")}
            return {
                "raw": None,
                "parsed": schema.model_validate(page_copy()),
                "parsing_error": None,
            }

        return RunnableLambda(invoke)


def test_native_path_retries_on_parsing_error():
    llm = NativeFake(respond=lambda _: "unused")
    result = structured_call(llm, PageCopy, PROMPT)
    assert result.sections[0].heading == "Hello"
    assert "bad args" in llm.calls[1][-1].content
