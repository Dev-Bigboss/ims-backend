import jwt
from fastapi import Request, HTTPException
from os import getenv

JWT_SECRET = getenv("JWT_SECRET")

def with_auth(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized: No token provided")
    token = auth_header.split(" ")[1]
    if not JWT_SECRET:
        raise HTTPException(status_code=500, detail="Server configuration error")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        request.state.user = payload  # Attach user to request.state
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid token")