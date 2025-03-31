from fastapi import Request, HTTPException
import jwt
from dotenv import load_dotenv
import os

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET")

async def with_auth(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized: No token provided")
    
    token = auth_header.split(" ")[1]
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server configuration error")
    
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        if decoded.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Forbidden: Admin access required")
        request.state.user = decoded
        return None
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid token")