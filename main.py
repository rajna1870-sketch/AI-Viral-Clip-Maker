
from fastapi import FastAPI

app = FastAPI(title="AI Viral Clip Maker")

@app.get("/")
def home():
    return {
        "status": "success",
        "message": "AI Viral Clip Maker Server is running"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}