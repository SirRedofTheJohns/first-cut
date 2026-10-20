"""Qwen3-8B from the Hugging Face Hub, running with `transformers` on a ZeroGPU Space.

ZeroGPU attaches a GPU only while a `@spaces.GPU` function runs, and bills each visitor's
daily quota for that time. The weights are placed on "cuda" at import (ZeroGPU emulates it
outside GPU functions); each LLM call is one short GPU task.

The model is wrapped as a LangChain chat model so the First Cut graph runs unchanged. It
has no native tool calling, so `structured_call` uses its JSON-in-the-prompt path.
"""

import spaces  # must be imported before torch initializes CUDA
import torch
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = "Qwen/Qwen3-8B"
_ROLES = {"system": "system", "human": "user", "ai": "assistant"}

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=torch.bfloat16)
model.to("cuda")


@spaces.GPU(duration=90)
def _generate(chat: list[dict], max_new_tokens: int, temperature: float) -> str:
    inputs = tokenizer.apply_chat_template(
        chat,
        add_generation_prompt=True,
        enable_thinking=False,  # Qwen3 "thinking" would spend the GPU quota on hidden text
        return_tensors="pt",
        return_dict=True,
    ).to("cuda")
    output = model.generate(
        **inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=temperature, top_p=0.9
    )
    return tokenizer.decode(output[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)


class ChatZeroGPU(BaseChatModel):
    max_new_tokens: int = 1200
    temperature: float = 0.3

    @property
    def _llm_type(self) -> str:
        return "zerogpu-transformers"

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        chat = [{"role": _ROLES.get(m.type, "user"), "content": m.text} for m in messages]
        text = _generate(chat, self.max_new_tokens, self.temperature)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])
