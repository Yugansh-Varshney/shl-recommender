# SHL Assessment Recommender

Conversational FastAPI agent for recommending SHL Individual Test Solutions.

## Setup

```bash
# 1. Set your Groq API key
cp .env.example .env
# Edit .env and add your GROQ_API_KEY (get free key at console.groq.com)

# 2. Run setup (installs deps + scrapes catalog + builds vector store + writes files)
python setup.py

# 3. Start server
python main.py
```

## API

### GET /health
Returns `{"status": "ok"}`

### POST /chat
Request:
```json
{
  "messages": [
    {"role": "user", "content": "I need to hire a Java developer"}
  ]
}
```

Response:
```json
{
  "reply": "...",
  "recommendations": [
    {"name": "Java 8 (New)", "url": "https://www.shl.com/...", "test_type": "K"}
  ],
  "end_of_conversation": false
}
```

## Deploy to Render (Free)
1. Push this folder to GitHub
2. Go to render.com → New Web Service
3. Connect repo → it auto-detects render.yaml
4. Add GROQ_API_KEY in Environment Variables
5. Deploy
