import asyncio
from fastapi import FastAPI, HTTPException
import uvicorn
from fastapi_lens import LensMiddleware, LensConfig
import random
import time

app = FastAPI()

LensMiddleware.setup(app, LensConfig(
    db_path="demo.db",
    security_enabled=False,
    report_key="demo-key",
    ttl_days=10
))

@app.get("/")
async def home():
    return {"message": "Welcome to Lens Demo"}


@app.get("/test")
async def test():
    return {"message": "Test"}

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    await asyncio.sleep(random.uniform(0.01, 0.2)) # Simulated latency
    if user_id % 5 == 0:
        raise HTTPException(status_code=500, detail="Server Error")
    if user_id % 3 == 0:
        raise HTTPException(status_code=400, detail="Client Error")
    return {"id": user_id}

@app.get("/items")
async def list_items():
    time.sleep(random.uniform(0.05, 0.5)) # More latency
    return [{"id": i} for i in range(10)]

if __name__ == "__main__":
    # Generate some traffic in a separate thread if needed, 
    # but I'll do it manually via browser or curl if I could.
    # Actually, I'll just run it and let the user/me browse.
    uvicorn.run(app, host="127.0.0.1", port=8002
    )
