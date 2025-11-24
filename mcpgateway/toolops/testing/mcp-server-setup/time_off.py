# -*- coding: utf-8 -*-
"""Location: ./mcpgateway/toolops/testing/mcp-server-setup/time_off.py
Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Jay Bandlamudi

MCP Gateway - Script to set up test sap tool API

This module creates API endpoint for toolops testing purpose.
"""
# Standard
from enum import Enum
from typing import List, Optional

# Third-Party
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="SAP SuccessFactors Time Off API", description="API for retrieving upcoming time off events", version="1.0.0")


class TimeOffTypes(str, Enum):
    """
    Represents the time off event types in SAP SuccessFactors.
    """

    ABSENCE = "ABSENCE"
    PUBLIC_HOLIDAY = "PUBLIC_HOLIDAY"
    NON_WORKING_DAY = "NON_WORKING_DAY"


class UpcomingTimeOff(BaseModel):
    """
    Represents an upcoming time off event in SAP SuccessFactors.
    """

    title: str
    start_date: str
    end_date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration: int
    time_unit: str
    cross_midnight: bool
    type: str
    status_formatted: Optional[str] = None
    absence_duration_category: Optional[str] = None

    class Config:
        schema_extra = {
            "example": {
                "title": "Vacation",
                "start_date": "2024-01-01",
                "end_date": "2024-01-05",
                "start_time": None,
                "end_time": None,
                "duration": 5,
                "time_unit": "DAYS",
                "cross_midnight": False,
                "type": "ABSENCE",
                "status_formatted": None,
                "absence_duration_category": None,
            }
        }


class UpcomingTimeOffResponse(BaseModel):
    """
    Represents the response from getting a user's upcoming time off.
    """

    time_off_events: List[UpcomingTimeOff]

    class Config:
        schema_extra = {
            "example": {
                "time_off_events": [
                    {
                        "title": "Vacation",
                        "start_date": "2024-01-01",
                        "end_date": "2024-01-05",
                        "start_time": None,
                        "end_time": None,
                        "duration": 5,
                        "time_unit": "DAYS",
                        "cross_midnight": False,
                        "type": "ABSENCE",
                        "status_formatted": None,
                        "absence_duration_category": None,
                    }
                ]
            }
        }


class TimeOffRequest(BaseModel):
    """
    Request model for getting upcoming time off.
    """

    user_id: str = Field(..., description="User ID in SAP SuccessFactors")
    start_date: str = Field(..., description="Start date in YYYY-MM-DD format", example="2024-01-01")
    end_date: Optional[str] = Field(None, description="End date in YYYY-MM-DD format", example="2024-01-05")
    time_off_types: List[TimeOffTypes] = Field(..., description="List of time off types to retrieve")

    class Config:
        schema_extra = {"example": {"user_id": "12344", "start_date": "2024-01-01", "end_date": "2024-01-05", "time_off_types": ["ABSENCE", "PUBLIC_HOLIDAY"]}}


class ErrorResponse(BaseModel):
    """
    Error response model.
    """

    status_code: int
    error: str


@app.post(
    "/api/time-off/upcoming",
    response_model=UpcomingTimeOffResponse,
    summary="Get Upcoming Time Off",
    description="Retrieves the user's upcoming time off details from SAP SuccessFactors.",
    responses={
        200: {"description": "Successfully retrieved time off events", "model": UpcomingTimeOffResponse},
        400: {"description": "Invalid request parameters", "model": ErrorResponse},
        500: {"description": "Internal server error", "model": ErrorResponse},
    },
)
def get_upcoming_time_off(request: TimeOffRequest) -> UpcomingTimeOffResponse:
    """
    Retrieves the user's upcoming time off details from SAP SuccessFactors.

    Args:
        request: in TimeoffRequest format with following information
            - user_id: User ID in SAP SuccessFactors
            - start_date: Start date in YYYY-MM-DD format
            - end_date: End date in YYYY-MM-DD format
            - time_off_types: List of time off types (ABSENCE, PUBLIC_HOLIDAY, NON_WORKING_DAY)

    Returns:
        UpcomingTimeOffResponse: List of upcoming time off events matching the specified criteria

    Raises:
        HTTPException: For server error codes
    """
    time_off_events = []

    for time_type in request.time_off_types:
        # Hard-coded values for testing
        if time_type == TimeOffTypes.ABSENCE:
            time_off_events.append(
                UpcomingTimeOff(
                    title="Vacation",
                    start_date="2024-01-01",
                    end_date="2024-01-05",
                    start_time=None,
                    end_time=None,
                    duration=5,
                    time_unit="DAYS",
                    cross_midnight=False,
                    type="ABSENCE",
                    status_formatted=None,
                    absence_duration_category=None,
                )
            )
        elif time_type == TimeOffTypes.PUBLIC_HOLIDAY:
            time_off_events.append(
                UpcomingTimeOff(
                    title="New Year's Day",
                    start_date="2024-01-01",
                    end_date="2024-01-01",
                    start_time=None,
                    end_time=None,
                    duration=1,
                    time_unit="DAYS",
                    cross_midnight=False,
                    type="PUBLIC_HOLIDAY",
                    status_formatted=None,
                    absence_duration_category=None,
                )
            )
            time_off_events.append(
                UpcomingTimeOff(
                    title="Christmas Day",
                    start_date="2024-12-25",
                    end_date="2024-12-25",
                    start_time=None,
                    end_time=None,
                    duration=1,
                    time_unit="DAYS",
                    cross_midnight=False,
                    type="PUBLIC_HOLIDAY",
                    status_formatted=None,
                    absence_duration_category=None,
                )
            )
        elif time_type == TimeOffTypes.NON_WORKING_DAY:
            time_off_events.append(
                UpcomingTimeOff(
                    title="Weekend",
                    start_date="2024-01-06",
                    end_date="2024-01-07",
                    start_time=None,
                    end_time=None,
                    duration=2,
                    time_unit="DAYS",
                    cross_midnight=False,
                    type="NON_WORKING_DAY",
                    status_formatted=None,
                    absence_duration_category=None,
                )
            )

    if len(time_off_events) == 0:
        raise HTTPException(status_code=400, detail="Invalid values for time off types, valid values are ABSENCE, PUBLIC_HOLIDAY, NON_WORKING_DAY")

    return UpcomingTimeOffResponse(time_off_events=time_off_events)


@app.get("/", summary="Root Endpoint")
def read_root():
    """
    Root endpoint with API information.

    Returns:
        Live status of the root API
    """
    return {"message": "SAP SuccessFactors Time Off API", "version": "1.0.0", "docs": "/docs", "openapi": "/openapi.json"}


if __name__ == "__main__":
    """
    Main method to start the time off API server
    """
    # Third-Party
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
