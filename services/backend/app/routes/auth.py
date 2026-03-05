from fastapi import APIRouter, Depends, HTTPException, Response, Request
import jwt
from datetime import datetime, timedelta, timezone

from app.models import LoginRequest, TokenResponse, UserProfile
from app.config import settings
from app.services.auth_service import authenticate_user
from app.dependencies import require_auth

router = APIRouter()

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiry_hours)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.jwt_secret, algorithm="HS256")

def _set_auth_cookie(response: Response, access_token: str) -> None:
    """Set the JWT as an HttpOnly cookie with security best practices."""
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        max_age=settings.jwt_expiry_hours * 3600,
        expires=settings.jwt_expiry_hours * 3600,
        samesite="lax",
    )

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, response: Response):
    username, role = authenticate_user(request.username, request.password)
    
    if not username:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token = create_access_token({"sub": username, "roles": [f"ROLE_{role.upper()}"], "groups": []})
    
    # Set HTTP-only cookie (the token is NOT returned in the response body for security)
    _set_auth_cookie(response, access_token)
    
    # Do NOT return the JWT in the response body — it defeats HttpOnly cookie protection
    return TokenResponse(
        expires_in=settings.jwt_expiry_hours * 3600,
        role=role
    )

@router.get("/me", response_model=UserProfile)
async def get_current_user(payload: dict = Depends(require_auth)):
    return UserProfile(
        id=payload.get("sub", ""),
        email=payload.get("sub", ""),
        roles=payload.get("roles", []),
        groups=payload.get("groups", []),
        sub=payload.get("sub", "")
    )

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("access_token")
    return {"message": "Logged out successfully"}

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(response: Response, payload: dict = Depends(require_auth)):
    # Create new token with same payload but new expiry
    access_token = create_access_token({
        "sub": payload.get("sub"),
        "roles": payload.get("roles", []),
        "groups": payload.get("groups", [])
    })
    
    _set_auth_cookie(response, access_token)
    
    # Extract role for response
    roles = payload.get("roles", [])
    role = "admin" if "ROLE_ADMINISTRATOR" in roles else "user"
    
    return TokenResponse(
        expires_in=settings.jwt_expiry_hours * 3600,
        role=role
    )
