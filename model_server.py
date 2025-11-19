from __future__ import annotations
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer

# ---------------------------
# ????? ?????? ???????
# ---------------------------
MODEL_PATH = "/home/medvlm/models/gemma3"
MAX_NEW_TOKENS = 1024

# ---------------------------
# ????? ????? FastAPI
# ---------------------------
app = FastAPI(title="Local Gemma-3 Server", version="1.0.0")

# ---------------------------
# ????? Tokenizer ????????
# ---------------------------
print(f"Loading tokenizer from: {MODEL_PATH}")
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH, local_files_only=True)

print(f"Loading model from: {MODEL_PATH}")
device_type = "cuda" if torch.cuda.is_available() else "cpu"
model = AutoModelForCausalLM.from_pretrained(
    MODEL_PATH,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device_map="auto",
    local_files_only=True
)
model.eval()
print("? Model loaded successfully!")

# ---------------------------
# Pydantic models
# ---------------------------
class MessageContent(BaseModel):
    type: str = Field(..., description="OpenAI content type, e.g. text or image_url")
    text: Optional[str] = Field(None, description="Plain text payload")
    image_url: Optional[Dict[str, str]] = Field(
        None, description="{ 'url': 'https://...' } payload when type is image_url"
    )

class Message(BaseModel):
    role: str
    content: Any

class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(default="local-gemma-3")
    messages: List[Message]
    max_tokens: int = Field(default=512, le=MAX_NEW_TOKENS)
    temperature: float = Field(default=0.7, ge=0.0, le=1.5)
    top_p: float = Field(default=0.9, ge=0.1, le=1.0)

# ---------------------------
# Health check endpoint
# ---------------------------
@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "model_path": MODEL_PATH, "supports_images": False}

# ---------------------------
# Helper functions
# ---------------------------
def _normalise_message_content(message: Message) -> str:
    content = message.content
    if isinstance(content, list):
        parts: List[str] = []
        for part in content:
            part_type = part.get("type")
            if part_type == "text" and part.get("text"):
                parts.append(part["text"])
            elif part_type == "image_url" and part.get("image_url"):
                url = part["image_url"].get("url", "")
                parts.append(f"[Image URL: {url}]")
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        return content.get("text", str(content))
    if isinstance(content, str):
        return content
    return str(content)

def _build_conversation(messages: List[Message]) -> List[Dict[str, str]]:
    conversation: List[Dict[str, str]] = []
    for message in messages:
        normalised = _normalise_message_content(message)
        conversation.append({"role": message.role, "content": normalised})
    return conversation

# ---------------------------
# Chat completions endpoint
# ---------------------------
@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionRequest) -> Dict[str, Any]:
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    conversation = _build_conversation(request.messages)
    prompt = tokenizer.apply_chat_template(conversation, tokenize=False, add_generation_prompt=True)

    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    generate_kwargs = {
        "max_new_tokens": min(request.max_tokens, MAX_NEW_TOKENS),
        "temperature": request.temperature,
        "top_p": request.top_p,
        "do_sample": request.temperature > 0,
        "pad_token_id": tokenizer.eos_token_id,
    }

    with torch.inference_mode():
        output_ids = model.generate(**inputs, **generate_kwargs)

    prompt_length = inputs["input_ids"].shape[1]
    decoded = tokenizer.decode(output_ids[0][prompt_length:], skip_special_tokens=True)
    total_tokens = output_ids[0].shape[0]
    completion_tokens = total_tokens - prompt_length

    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": decoded.strip()}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": prompt_length, "completion_tokens": completion_tokens, "total_tokens": prompt_length + completion_tokens},
    }

# ---------------------------
# ????? ???????
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("gemma_server:app", host="0.0.0.0", port=8051, reload=False)
