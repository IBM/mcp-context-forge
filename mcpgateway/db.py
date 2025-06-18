# -*- coding: utf-8 -*-
"""MCP Gateway Database Models.

Copyright 2025
SPDX-License-Identifier: Apache-2.0
Authors: Mihai Criveti

This module defines SQLAlchemy models for storing MCP entities including:
- Tools with input schema validation
- Resources with subscription tracking
- Prompts with argument templates
- Federated gateways with capability tracking

Updated to record server associations independently using many-to-many relationships,
and to record tool execution metrics.
"""

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import jsonschema
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    create_engine,
    func,
    make_url,
    select,
)
from sqlalchemy.event import listen
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

from mcpgateway.config import settings
from mcpgateway.types import ResourceContent

# ---------------------------------------------------------------------------
# 1. Parse the URL so we can inspect backend ("postgresql", "sqlite", …)
#    and the specific driver ("psycopg2", "asyncpg", empty string = default).
# ---------------------------------------------------------------------------
url = make_url(settings.database_url)
backend = url.get_backend_name()  # e.g. 'postgresql', 'sqlite'
driver = url.get_driver_name() or "default"

# Start with an empty dict and add options only when the driver can accept
# them; this prevents unexpected TypeError at connect time.
connect_args: dict[str, object] = {}

# ---------------------------------------------------------------------------
# 2. PostgreSQL (synchronous psycopg2 only)
#    The keep-alive parameters below are recognised exclusively by libpq /
#    psycopg2 and let the kernel detect broken network links quickly.
# ---------------------------------------------------------------------------
if backend == "postgresql" and driver in ("psycopg2", "default", ""):
    connect_args.update(
        keepalives=1,  # enable TCP keep-alive probes
        keepalives_idle=30,  # seconds of idleness before first probe
        keepalives_interval=5,  # seconds between probes
        keepalives_count=5,  # drop the link after N failed probes
    )

# ---------------------------------------------------------------------------
# 3. SQLite (optional) – only one extra flag and it is *SQLite-specific*.
# ---------------------------------------------------------------------------
elif backend == "sqlite":
    # Allow pooled connections to hop across threads.
    connect_args["check_same_thread"] = False

# 4. Other backends (MySQL, MSSQL, etc.) leave `connect_args` empty.

# ---------------------------------------------------------------------------
# 5. Build the Engine with a single, clean connect_args mapping.
# ---------------------------------------------------------------------------
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,  # quick liveness check per checkout
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    connect_args=connect_args,
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Base class for all models."""


# # Association table for tools and gateways (federation)
# tool_gateway_table = Table(
#     "tool_gateway_association",
#     Base.metadata,
#     Column("tool_id", Integer, ForeignKey("tools.id"), primary_key=True),
#     Column("gateway_id", Integer, ForeignKey("gateways.id"), primary_key=True),
# )

# # Association table for resources and gateways (federation)
# resource_gateway_table = Table(
#     "resource_gateway_association",
#     Base.metadata,
#     Column("resource_id", Integer, ForeignKey("resources.id"), primary_key=True),
#     Column("gateway_id", Integer, ForeignKey("gateways.id"), primary_key=True),
# )

# # Association table for prompts and gateways (federation)
# prompt_gateway_table = Table(
#     "prompt_gateway_association",
#     Base.metadata,
#     Column("prompt_id", Integer, ForeignKey("prompts.id"), primary_key=True),
#     Column("gateway_id", Integer, ForeignKey("gateways.id"), primary_key=True),
# )

# Association table for servers and tools
server_tool_association = Table(
    "server_tool_association",
    Base.metadata,
    Column("server_id", Integer, ForeignKey("servers.id"), primary_key=True),
    Column("tool_id", Integer, ForeignKey("tools.id"), primary_key=True),
)

# Association table for servers and resources
server_resource_association = Table(
    "server_resource_association",
    Base.metadata,
    Column("server_id", Integer, ForeignKey("servers.id"), primary_key=True),
    Column("resource_id", Integer, ForeignKey("resources.id"), primary_key=True),
)

# Association table for servers and prompts
server_prompt_association = Table(
    "server_prompt_association",
    Base.metadata,
    Column("server_id", Integer, ForeignKey("servers.id"), primary_key=True),
    Column("prompt_id", Integer, ForeignKey("prompts.id"), primary_key=True),
)


class ToolMetric(Base):
    """
    ORM model for recording individual metrics for tool executions.

    Each record in this table corresponds to a single tool invocation and records:
        - timestamp (datetime): When the invocation occurred.
        - response_time (float): The execution time in seconds.
        - is_success (bool): True if the execution succeeded, False otherwise.
        - error_message (Optional[str]): Error message if the execution failed.

    Aggregated metrics (such as total executions, successful/failed counts, failure rate,
    minimum, maximum, and average response times, and last execution time) should be computed
    on the fly using SQL aggregate functions over the rows in this table.
    """

    __tablename__ = "tool_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    tool_id: Mapped[int] = mapped_column(Integer, ForeignKey("tools.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Tool model.
    tool: Mapped["Tool"] = relationship("Tool", back_populates="metrics")


class ResourceMetric(Base):
    """
    ORM model for recording metrics for resource invocations.

    Attributes:
        id (int): Primary key.
        resource_id (int): Foreign key linking to the resource.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "resource_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(Integer, ForeignKey("resources.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Resource model.
    resource: Mapped["Resource"] = relationship("Resource", back_populates="metrics")


class ServerMetric(Base):
    """
    ORM model for recording metrics for server invocations.

    Attributes:
        id (int): Primary key.
        server_id (int): Foreign key linking to the server.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "server_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int] = mapped_column(Integer, ForeignKey("servers.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Server model.
    server: Mapped["Server"] = relationship("Server", back_populates="metrics")


class PromptMetric(Base):
    """
    ORM model for recording metrics for prompt invocations.

    Attributes:
        id (int): Primary key.
        prompt_id (int): Foreign key linking to the prompt.
        timestamp (datetime): The time when the invocation occurred.
        response_time (float): The response time in seconds.
        is_success (bool): True if the invocation succeeded, False otherwise.
        error_message (Optional[str]): Error message if the invocation failed.
    """

    __tablename__ = "prompt_metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    prompt_id: Mapped[int] = mapped_column(Integer, ForeignKey("prompts.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    response_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationship back to the Prompt model.
    prompt: Mapped["Prompt"] = relationship("Prompt", back_populates="metrics")


class Tool(Base):
    """
    ORM model for a registered Tool.

    Supports both local tools and federated tools from other gateways.
    The integration_type field indicates the tool format:
    - "MCP" for MCP-compliant tools (default)
    - "REST" for REST tools

    Additionally, this model provides computed properties for aggregated metrics based
    on the associated ToolMetric records. These include:
        - execution_count: Total number of invocations.
        - successful_executions: Count of successful invocations.
        - failed_executions: Count of failed invocations.
        - failure_rate: Ratio of failed invocations to total invocations.
        - min_response_time: Fastest recorded response time.
        - max_response_time: Slowest recorded response time.
        - avg_response_time: Mean response time.
        - last_execution_time: Timestamp of the most recent invocation.

    The property `metrics_summary` returns a dictionary with these aggregated values.

    The following fields have been added to support tool invocation configuration:
        - request_type: HTTP method to use when invoking the tool.
        - auth_type: Type of authentication ("basic", "bearer", or None).
        - auth_username: Username for basic authentication.
        - auth_password: Password for basic authentication.
        - auth_token: Token for bearer token authentication.
        - auth_header_key: header key for authentication.
        - auth_header_value: header value for authentication.
    """

    __tablename__ = "tools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    url: Mapped[str] = mapped_column(String, nullable=True)
    description: Mapped[Optional[str]]
    integration_type: Mapped[str] = mapped_column(default="MCP")
    request_type: Mapped[str] = mapped_column(default="SSE")
    headers: Mapped[Optional[Dict[str, str]]] = mapped_column(JSON)
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(default=True)
    jsonpath_filter: Mapped[str] = mapped_column(default="")

    # Request type and authentication fields
    auth_type: Mapped[Optional[str]] = mapped_column(default=None)  # "basic", "bearer", or None
    auth_value: Mapped[Optional[str]] = mapped_column(default=None)

    # Federation relationship with a local gateway
    gateway_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gateways.id"))
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="tools")
    # federated_with = relationship("Gateway", secondary=tool_gateway_table, back_populates="federated_tools")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_tool_association, back_populates="tools")

    # Relationship with ToolMetric records
    metrics: Mapped[List["ToolMetric"]] = relationship("ToolMetric", back_populates="tool", cascade="all, delete-orphan")

    @hybrid_property
    def execution_count(self) -> int:
        """
        Returns the number of times the tool has been executed,
        calculated from the associated ToolMetric records.

        Returns:
            int: The total count of tool executions.
        """
        return len(self.metrics)

    @execution_count.expression
    # method is intentionally a class-level expression, so no `self`
    # pylint: disable=no-self-argument
    def execution_count(cls):
        """
        SQL expression to compute the execution count for the tool.

        Returns:
            int: Returns execution count of a given tool
        """
        return select(func.count(ToolMetric.id)).where(ToolMetric.tool_id == cls.id).label("execution_count")  # pylint: disable=not-callable

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful tool executions,
        computed from the associated ToolMetric records.

        Returns:
            int: The count of successful tool executions.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed tool executions,
        computed from the associated ToolMetric records.

        Returns:
            int: The count of failed tool executions.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed executions) / (total executions).
        Returns 0.0 if there are no executions.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total: int = self.execution_count
        # execution_count is a @hybrid_property, not a callable here
        if total == 0:  # pylint: disable=comparison-with-callable
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all tool executions.
        Returns None if no executions exist.

        Returns:
            Optional[float]: The minimum response time, or None if no executions exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all tool executions.
        Returns None if no executions exist.

        Returns:
            Optional[float]: The maximum response time, or None if no executions exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all tool executions.
        Returns None if no executions exist.

        Returns:
            Optional[float]: The average response time, or None if no executions exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent tool execution.
        Returns None if no executions exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent execution, or None if no executions exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)

    @property
    def metrics_summary(self) -> Dict[str, Any]:
        """
        Returns aggregated metrics for the tool as a dictionary with the following keys:
            - total_executions: Total number of invocations.
            - successful_executions: Number of successful invocations.
            - failed_executions: Number of failed invocations.
            - failure_rate: Failure rate (failed/total) or 0.0 if no invocations.
            - min_response_time: Minimum response time (or None if no invocations).
            - max_response_time: Maximum response time (or None if no invocations).
            - avg_response_time: Average response time (or None if no invocations).
            - last_execution_time: Timestamp of the most recent invocation (or None).

        Returns:
            Dict[str, Any]: Dictionary containing the aggregated metrics.
        """
        return {
            "total_executions": self.execution_count,
            "successful_executions": self.successful_executions,
            "failed_executions": self.failed_executions,
            "failure_rate": self.failure_rate,
            "min_response_time": self.min_response_time,
            "max_response_time": self.max_response_time,
            "avg_response_time": self.avg_response_time,
            "last_execution_time": self.last_execution_time,
        }


class Resource(Base):
    """
    ORM model for a registered Resource.

    Resources represent content that can be read by clients.
    Supports subscriptions for real-time updates.
    Additionally, this model provides a relationship with ResourceMetric records
    to capture invocation metrics (such as execution counts, response times, and failures).
    """

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    uri: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    description: Mapped[Optional[str]]
    mime_type: Mapped[Optional[str]]
    size: Mapped[Optional[int]]
    template: Mapped[Optional[str]]  # URI template for parameterized resources
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(default=True)
    metrics: Mapped[List["ResourceMetric"]] = relationship("ResourceMetric", back_populates="resource", cascade="all, delete-orphan")

    # Content storage - can be text or binary
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    binary_content: Mapped[Optional[bytes]]

    # Subscription tracking
    subscriptions: Mapped[List["ResourceSubscription"]] = relationship("ResourceSubscription", back_populates="resource", cascade="all, delete-orphan")

    gateway_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gateways.id"))
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="resources")
    # federated_with = relationship("Gateway", secondary=resource_gateway_table, back_populates="federated_resources")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_resource_association, back_populates="resources")

    @property
    def content(self) -> ResourceContent:
        """
        Returns the resource content in the appropriate format.

        If text content exists, returns a ResourceContent with text.
        Otherwise, if binary content exists, returns a ResourceContent with blob data.
        Raises a ValueError if no content is available.

        Returns:
            ResourceContent: The resource content with appropriate format (text or blob).

        Raises:
            ValueError: If the resource has no content available.
        """

        if self.text_content is not None:
            return ResourceContent(
                type="resource",
                uri=self.uri,
                mime_type=self.mime_type,
                text=self.text_content,
            )
        if self.binary_content is not None:
            return ResourceContent(
                type="resource",
                uri=self.uri,
                mime_type=self.mime_type or "application/octet-stream",
                blob=self.binary_content,
            )
        raise ValueError("Resource has no content")

    @property
    def execution_count(self) -> int:
        """
        Returns the number of times the resource has been invoked,
        calculated from the associated ResourceMetric records.

        Returns:
            int: The total count of resource invocations.
        """
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful resource invocations,
        computed from the associated ResourceMetric records.

        Returns:
            int: The count of successful resource invocations.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed resource invocations,
        computed from the associated ResourceMetric records.

        Returns:
            int: The count of failed resource invocations.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed invocations) / (total invocations).
        Returns 0.0 if there are no invocations.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total: int = self.execution_count
        if total == 0:
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all resource invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The minimum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all resource invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The maximum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all resource invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The average response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent resource invocation.
        Returns None if no invocations exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None if no invocations exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)


class ResourceSubscription(Base):
    """Tracks subscriptions to resource updates."""

    __tablename__ = "resource_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"))
    subscriber_id: Mapped[str]  # Client identifier
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    last_notification: Mapped[Optional[datetime]] = mapped_column(DateTime)

    resource: Mapped["Resource"] = relationship(back_populates="subscriptions")


class Prompt(Base):
    """
    ORM model for a registered Prompt template.

    Represents a prompt template along with its argument schema.
    Supports rendering and invocation of prompts.
    Additionally, this model provides computed properties for aggregated metrics based
    on the associated PromptMetric records. These include:
        - execution_count: Total number of prompt invocations.
        - successful_executions: Count of successful invocations.
        - failed_executions: Count of failed invocations.
        - failure_rate: Ratio of failed invocations to total invocations.
        - min_response_time: Fastest recorded response time.
        - max_response_time: Slowest recorded response time.
        - avg_response_time: Mean response time.
        - last_execution_time: Timestamp of the most recent invocation.
    """

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[Optional[str]]
    template: Mapped[str] = mapped_column(Text)
    argument_schema: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(default=True)
    metrics: Mapped[List["PromptMetric"]] = relationship("PromptMetric", back_populates="prompt", cascade="all, delete-orphan")

    gateway_id: Mapped[Optional[int]] = mapped_column(ForeignKey("gateways.id"))
    gateway: Mapped["Gateway"] = relationship("Gateway", back_populates="prompts")
    # federated_with = relationship("Gateway", secondary=prompt_gateway_table, back_populates="federated_prompts")

    # Many-to-many relationship with Servers
    servers: Mapped[List["Server"]] = relationship("Server", secondary=server_prompt_association, back_populates="prompts")

    def validate_arguments(self, args: Dict[str, str]) -> None:
        """
        Validate prompt arguments against the argument schema.

        Args:
            args (Dict[str, str]): Dictionary of arguments to validate.

        Raises:
            ValueError: If the arguments do not conform to the schema.

        """
        try:
            jsonschema.validate(args, self.argument_schema)
        except jsonschema.exceptions.ValidationError as e:
            raise ValueError(f"Invalid prompt arguments: {str(e)}")

    @property
    def execution_count(self) -> int:
        """
        Returns the number of times the prompt has been invoked,
        calculated from the associated PromptMetric records.

        Returns:
            int: The total count of prompt invocations.
        """
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful prompt invocations,
        computed from the associated PromptMetric records.

        Returns:
            int: The count of successful prompt invocations.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed prompt invocations,
        computed from the associated PromptMetric records.

        Returns:
            int: The count of failed prompt invocations.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed invocations) / (total invocations).
        Returns 0.0 if there are no invocations.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total: int = self.execution_count
        if total == 0:
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all prompt invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The minimum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all prompt invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The maximum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all prompt invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The average response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent prompt invocation.
        Returns None if no invocations exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None if no invocations exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)


class Server(Base):
    """
    ORM model for MCP Servers Catalog.

    Represents a server that composes catalog items (tools, resources, prompts).
    Additionally, this model provides computed properties for aggregated metrics based
    on the associated ServerMetric records. These include:
        - execution_count: Total number of invocations.
        - successful_executions: Count of successful invocations.
        - failed_executions: Count of failed invocations.
        - failure_rate: Ratio of failed invocations to total invocations.
        - min_response_time: Fastest recorded response time.
        - max_response_time: Slowest recorded response time.
        - avg_response_time: Mean response time.
        - last_execution_time: Timestamp of the most recent invocation.
    """

    __tablename__ = "servers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    description: Mapped[Optional[str]]
    icon: Mapped[Optional[str]]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(default=True)
    metrics: Mapped[List["ServerMetric"]] = relationship("ServerMetric", back_populates="server", cascade="all, delete-orphan")

    # Many-to-many relationships for associated items
    tools: Mapped[List["Tool"]] = relationship("Tool", secondary=server_tool_association, back_populates="servers")
    resources: Mapped[List["Resource"]] = relationship("Resource", secondary=server_resource_association, back_populates="servers")
    prompts: Mapped[List["Prompt"]] = relationship("Prompt", secondary=server_prompt_association, back_populates="servers")

    @property
    def execution_count(self) -> int:
        """
        Returns the number of times the server has been invoked,
        calculated from the associated ServerMetric records.

        Returns:
            int: The total count of server invocations.
        """
        return len(self.metrics)

    @property
    def successful_executions(self) -> int:
        """
        Returns the count of successful server invocations,
        computed from the associated ServerMetric records.

        Returns:
            int: The count of successful server invocations.
        """
        return sum(1 for m in self.metrics if m.is_success)

    @property
    def failed_executions(self) -> int:
        """
        Returns the count of failed server invocations,
        computed from the associated ServerMetric records.

        Returns:
            int: The count of failed server invocations.
        """
        return sum(1 for m in self.metrics if not m.is_success)

    @property
    def failure_rate(self) -> float:
        """
        Returns the failure rate (as a float between 0 and 1) computed as:
            (failed invocations) / (total invocations).
        Returns 0.0 if there are no invocations.

        Returns:
            float: The failure rate as a value between 0 and 1.
        """
        total: int = self.execution_count
        if total == 0:
            return 0.0
        return self.failed_executions / total

    @property
    def min_response_time(self) -> Optional[float]:
        """
        Returns the minimum response time among all server invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The minimum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return min(times) if times else None

    @property
    def max_response_time(self) -> Optional[float]:
        """
        Returns the maximum response time among all server invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The maximum response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return max(times) if times else None

    @property
    def avg_response_time(self) -> Optional[float]:
        """
        Returns the average response time among all server invocations.
        Returns None if no invocations exist.

        Returns:
            Optional[float]: The average response time, or None if no invocations exist.
        """
        times: List[float] = [m.response_time for m in self.metrics]
        return sum(times) / len(times) if times else None

    @property
    def last_execution_time(self) -> Optional[datetime]:
        """
        Returns the timestamp of the most recent server invocation.
        Returns None if no invocations exist.

        Returns:
            Optional[datetime]: The timestamp of the most recent invocation, or None if no invocations exist.
        """
        if not self.metrics:
            return None
        return max(m.timestamp for m in self.metrics)


class Gateway(Base):
    """ORM model for a federated peer Gateway."""

    __tablename__ = "gateways"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    url: Mapped[str]
    description: Mapped[Optional[str]]
    transport: Mapped[str] = mapped_column(default="SSE")
    capabilities: Mapped[Dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    is_active: Mapped[bool] = mapped_column(default=True)
    last_seen: Mapped[Optional[datetime]]

    # Relationship with local tools this gateway provides
    tools: Mapped[List["Tool"]] = relationship(back_populates="gateway", cascade="all, delete-orphan")

    # Relationship with local prompts this gateway provides
    prompts: Mapped[List["Prompt"]] = relationship(back_populates="gateway", cascade="all, delete-orphan")

    # Relationship with local resources this gateway provides
    resources: Mapped[List["Resource"]] = relationship(back_populates="gateway", cascade="all, delete-orphan")

    # # Tools federated from this gateway
    # federated_tools: Mapped[List["Tool"]] = relationship(secondary=tool_gateway_table, back_populates="federated_with")

    # # Prompts federated from this resource
    # federated_resources: Mapped[List["Resource"]] = relationship(secondary=resource_gateway_table, back_populates="federated_with")

    # # Prompts federated from this gateway
    # federated_prompts: Mapped[List["Prompt"]] = relationship(secondary=prompt_gateway_table, back_populates="federated_with")

    # Authorizations
    auth_type: Mapped[Optional[str]] = mapped_column(default=None)  # "basic", "bearer", "headers" or None
    auth_value: Mapped[Optional[Dict[str, str]]] = mapped_column(JSON)


class SessionRecord(Base):
    """ORM model for sessions from SSE client."""

    __tablename__ = "mcp_sessions"

    session_id: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))  # pylint: disable=not-callable
    last_accessed: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))  # pylint: disable=not-callable
    data: Mapped[str] = mapped_column(String, nullable=True)

    messages: Mapped[List["SessionMessageRecord"]] = relationship("SessionMessageRecord", back_populates="session", cascade="all, delete-orphan")


class SessionMessageRecord(Base):
    """ORM model for messages from SSE client."""

    __tablename__ = "mcp_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("mcp_sessions.session_id"))
    message: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))  # pylint: disable=not-callable
    last_accessed: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))  # pylint: disable=not-callable

    session: Mapped["SessionRecord"] = relationship("SessionRecord", back_populates="messages")


# Event listeners for validation
def validate_tool_schema(mapper, connection, target):
    """
    Validate tool schema before insert/update.

    Args:
        mapper: The mapper being used for the operation.
        connection: The database connection.
        target: The target object being validated.

    Raises:
        ValueError: If the tool input schema is invalid.
    """
    # You can use mapper and connection later, if required.
    _ = mapper
    _ = connection
    if hasattr(target, "input_schema"):
        try:
            jsonschema.Draft7Validator.check_schema(target.input_schema)
        except jsonschema.exceptions.SchemaError as e:
            raise ValueError(f"Invalid tool input schema: {str(e)}")


def validate_tool_name(mapper, connection, target):
    """
    Validate tool name before insert/update. Check if the name matches the required pattern.

    Args:
        mapper: The mapper being used for the operation.
        connection: The database connection.
        target: The target object being validated.

    Raises:
        ValueError: If the tool name contains invalid characters.
    """
    # You can use mapper and connection later, if required.
    _ = mapper
    _ = connection
    if hasattr(target, "name"):
        if not re.match(r"^[a-zA-Z0-9_-]+$", target.name):
            raise ValueError(f"Invalid tool name '{target.name}'. Only alphanumeric characters, hyphens, and underscores are allowed.")


def validate_prompt_schema(mapper, connection, target):
    """
    Validate prompt argument schema before insert/update.

    Args:
        mapper: The mapper being used for the operation.
        connection: The database connection.
        target: The target object being validated.

    Raises:
        ValueError: If the prompt argument schema is invalid.
    """
    # You can use mapper and connection later, if required.
    _ = mapper
    _ = connection
    if hasattr(target, "argument_schema"):
        try:
            jsonschema.Draft7Validator.check_schema(target.argument_schema)
        except jsonschema.exceptions.SchemaError as e:
            raise ValueError(f"Invalid prompt argument schema: {str(e)}")


# Register validation listeners

listen(Tool, "before_insert", validate_tool_schema)
listen(Tool, "before_update", validate_tool_schema)
listen(Tool, "before_insert", validate_tool_name)
listen(Tool, "before_update", validate_tool_name)
listen(Prompt, "before_insert", validate_prompt_schema)
listen(Prompt, "before_update", validate_prompt_schema)


def get_db():
    """
    Dependency to get database session.

    Yields:
        SessionLocal: A SQLAlchemy database session.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Create all tables
def init_db():
    """
    Initialize database tables.

    Raises:
        Exception: If database initialization fails.
    """
    try:
        # Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError as e:
        raise Exception(f"Failed to initialize database: {str(e)}")


if __name__ == "__main__":
    init_db()
