# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/routers/email_auth_clean.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

Email-Only Authentication Routes - Clean Implementation.
"""

# Standard
import logging
from typing import Optional

# Third-Party
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

# First-Party
from mcpgateway.auth import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/email", tags=["Email Authentication"])


# Schemas
class EmailLoginRequest(BaseModel):
    email: str = Field(..., description="Email address")
    password: str = Field(..., description="Password")


class EmailUserResponse(BaseModel):
    email: str
    full_name: Optional[str]
    is_admin: bool
    is_active: bool


@router.post("/login")
async def email_login(request: Request, login_request: EmailLoginRequest, db: Session = Depends(get_db)):
    """Email-only login endpoint."""
    # Simple implementation for testing
    # First-Party
    from mcpgateway.services.email_auth_service import EmailAuthService

    email_auth_service = EmailAuthService(db)
    user = await email_auth_service.authenticate_user(email=login_request.email, password=login_request.password)

    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {"message": "Login successful", "email": user.email}


@router.get("/test")
async def test_email_endpoint():
    """Test endpoint for email-only system."""
    return {"status": "Email-only authentication system working"}
