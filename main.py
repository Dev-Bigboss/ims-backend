from fastapi import FastAPI, Request, Depends, HTTPException
from pymongo import MongoClient
from typing import List
from dotenv import load_dotenv
import os
from models import Activity
from auth import with_auth

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI")

app = FastAPI()

# MongoDB Connection
client = None
def get_db():
    global client
    if not MONGODB_URI:
        raise HTTPException(status_code=500, detail="Server configuration error")
    if not client:
        client = MongoClient(MONGODB_URI)
    return client["inventoryhub"]["activities"]

# GET /api/activities
@app.get("/api/activities", response_model=dict)
async def get_activities(request: Request, page: int = 1, limit: int = 10, auth=Depends(with_auth)):
    try:
        db = get_db()
        skip = (page - 1) * limit
        activities = list(db.find().skip(skip).limit(limit).sort("createdAt", -1))
        total = db.count_documents({})
        
        # Convert MongoDB documents to Pydantic models
        activities = [Activity(**{**act, "_id": str(act["_id"])}) for act in activities]
        
        return {
            "activities": activities,
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit
        }
    except Exception as e:
        print(f"GET /api/activities failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# POST /api/activities
@app.post("/api/activities", response_model=dict)
async def create_activity(activity: Activity, request: Request, auth=Depends(with_auth)):
    try:
        db = get_db()
        result = db.insert_one(activity.dict())
        activity_dict = activity.dict()
        activity_dict["_id"] = str(result.inserted_id)
        return {"activity": activity_dict}
    except Exception as e:
        print(f"POST /api/activities failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)