import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from agent import chat

app = FastAPI(
    title="SHL Assessment Recommender",
    description="Conversational agent to find the right SHL assessments",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]


class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str


class ChatResponse(BaseModel):
    reply: str
    recommendations: list[Recommendation]
    end_of_conversation: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(request: ChatRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")
    
    # Validate roles
    for msg in request.messages:
        if msg.role not in ("user", "assistant"):
            raise HTTPException(status_code=400, detail=f"Invalid role: {msg.role}")
    
    # Last message must be from user
    if request.messages[-1].role != "user":
        raise HTTPException(status_code=400, detail="Last message must be from user")
    
    # Convert to dicts
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    
    # Get agent response
    result = chat(messages)
    
    return ChatResponse(
        reply=result["reply"],
        recommendations=[
            Recommendation(
                name=r["name"],
                url=r["url"],
                test_type=r["test_type"]
            )
            for r in result.get("recommendations", [])
        ],
        end_of_conversation=result.get("end_of_conversation", False),
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
