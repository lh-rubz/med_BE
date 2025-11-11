"""Lightweight FastAPI serv# ===== CONFIGURATION - UPDATE THESE VALUES =====
# Path to your Gemma-3 model directory
MODEL_PATH = Path("/medvlm/models/gemma3")  # Server location of Gemma weights
MAX_MAX_NEW_TOKENS = 1024
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8051
# ================================================

# Validate model path exists
if not MODEL_PATH.exists():
    raise RuntimeError(
        f"Gemma model weights not found at: {MODEL_PATH}\n"
        f"Please update MODEL_PATH to point to your Gemma-3 model directory."
    )s a local Gemma-3 chat endpoint
compatible with the OpenAI chat completions API used by the Flask app.

Usage
-----
1. Install requirements ``pip install -r requirements.txt``
2. Place the Gemma-3 weights under ``./models/gemma3``
3. Update MODEL_PATH below to point to your model directory
4. Start the server:

     python gemma3.py

5. Health check is available at ``GET /health``.
6. Chat completions are served at ``POST /v1/chat/completions``.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from transformers import AutoModelForCausalLM, AutoTokenizer

# ===== CONFIGURATION - UPDATE THESE VALUES =====
# Path to your Gemma-3 model directory
MODEL_PATH = Path("/medvlm/models/gemma3")  # Server location of Gemma weights
MAX_MAX_NEW_TOKENS = 1024
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8051
# ================================================

# Validate model path exists
if not MODEL_PATH.exists():
    raise RuntimeError(
        f"Gemma model weights not found at: {MODEL_PATH}\n"
        f"Please update MODEL_PATH to point to your Gemma-3 model directory."
    )

app = FastAPI(
    title="Local Gemma-3 Server",
    version="1.0.0",
    docs_url="/swagger",
    openapi_url="/swagger.json",
)

tokenizer = AutoTokenizer.from_pretrained(
    str(MODEL_PATH),
    local_files_only=True,
    trust_remote_code=True,
    use_fast=False,
)
model = AutoModelForCausalLM.from_pretrained(
    str(MODEL_PATH),
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device_map="auto",
    local_files_only=True,
    trust_remote_code=True,
)
model.eval()


class MessageContent(BaseModel):
    type: str = Field(..., description="OpenAI content type, e.g. text or image_url")
    text: Optional[str] = Field(None, description="Plain text payload")
    image_url: Optional[Dict[str, str]] = Field(
        None,
        description="{ 'url': 'https://...' } payload when type is image_url",
    )


class Message(BaseModel):
    role: str
    content: Any


class ChatCompletionRequest(BaseModel):
    model: Optional[str] = Field(default="local-gemma-3")
    messages: List[Message]
    max_tokens: int = Field(default=512, le=MAX_MAX_NEW_TOKENS)
    temperature: float = Field(default=0.7, ge=0.0, le=1.5)
    top_p: float = Field(default=0.9, ge=0.1, le=1.0)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "model_path": MODEL_PATH,
        "supports_images": True,
    }


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


@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionRequest) -> Dict[str, Any]:
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    conversation = _build_conversation(request.messages)
    prompt = tokenizer.apply_chat_template(
        conversation,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer(prompt, return_tensors="pt")
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    generate_kwargs = {
        "max_new_tokens": min(request.max_tokens, MAX_MAX_NEW_TOKENS),
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
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": decoded.strip()},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_length,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_length + completion_tokens,
        },
    }


if __name__ == "__main__":
    import uvicorn
    
    print("\n" + "="*80)
    print("🚀 Starting Gemma-3 Local Model Server")
    print("="*80)
    print(f"📍 Model Path: {MODEL_PATH}")
    print(f"🌐 Server URL: http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"📊 Max Tokens: {MAX_MAX_NEW_TOKENS}")
    print(f"🔧 Device: {'CUDA' if torch.cuda.is_available() else 'CPU'}")
    print("="*80)
    print("\n✅ Server endpoints:")
    print(f"   - Health Check: http://{SERVER_HOST}:{SERVER_PORT}/health")
    print(f"   - Chat Completions: http://{SERVER_HOST}:{SERVER_PORT}/v1/chat/completions")
    print(f"   - API Docs: http://{SERVER_HOST}:{SERVER_PORT}/swagger")
    print("="*80 + "\n")
    
    uvicorn.run("gemma3:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)