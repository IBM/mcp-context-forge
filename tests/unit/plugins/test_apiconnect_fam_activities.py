"""Unit tests for API Connect FAM Activities.

Tests the activity classes for runtime registration, heartbeat, and metrics.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import time

from plugins.apiconnect_fam.activities.register_runtime import RegisterRuntimeActivity
from plugins.apiconnect_fam.activities.send_heartbeat import SendHeartbeatActivity
from plugins.apiconnect_fam.activities.send_metrics import SendMetricsActivity
from plugins.apiconnect_fam.models import ActivityContext, ReregistrationReport
from plugins.apiconnect_fam.utils.errors import RegistrationError, SyncError


class TestRegisterRuntimeActivity:
    """Test runtime registration activity."""

    @pytest.fixture
    def context(self):
        """Create activity context."""
        return ActivityContext(
            runtime_id="test-runtime-123",
            fam_base_url="https://fam.example.com",
            config={
                "fam_runtime_name": "Test Runtime",
                "fam_runtime_description": "Test Description",
                "fam_runtime_type": "MCP_CONTEXT_FORGE",
                "fam_runtime_deployment_type": "ON_PREMISE",
                "fam_runtime_region": "us-east-1",
                "fam_runtime_location": "US East",
                "fam_runtime_host": "gateway-01",
                "fam_runtime_tags": ["test", "dev"],
                "fam_runtime_capacity_value": "100",
                "fam_runtime_capacity_unit": "per minute",
            }
        )

    @pytest.fixture
    def fam_client(self):
        """Create mock FAM client."""
        return AsyncMock()

    @pytest.fixture
    def runtime_config(self):
        """Create runtime configuration."""
        return {
            "name": "Test Runtime",
            "description": "Test Description",
            "type": "MCP_CONTEXT_FORGE",
            "deployment_type": "ON_PREMISE",
            "region": "us-east-1",
            "location": "US East",
            "host": "gateway-01",
            "tags": ["test", "dev"],
            "capacity_value": "100",
            "capacity_unit": "per minute",
            "heartbeat_interval": 60,
        }

    @pytest.mark.asyncio
    async def test_successful_first_time_registration(self, context, fam_client, runtime_config):
        """Test successful first-time registration (201)."""
        activity = RegisterRuntimeActivity(context, fam_client, runtime_config)
        
        # Mock successful registration
        report = ReregistrationReport(
            runtime_id="runtime-456",
            status_code=201,
            last_registration_time=None,
            last_heartbeat_time=None,
            last_metrics_time=None,
            last_asset_sync_time=None,
        )
        fam_client.register_runtime = AsyncMock(return_value=report)
        
        await activity.perform()
        
        assert activity.get_runtime_id() == "runtime-456"
        assert context.runtime_id == "runtime-456"
        fam_client.register_runtime.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_successful_reregistration(self, context, fam_client, runtime_config):
        """Test successful re-registration (200)."""
        activity = RegisterRuntimeActivity(context, fam_client, runtime_config)
        
        # Mock re-registration
        report = ReregistrationReport(
            runtime_id="test-runtime-123",
            status_code=200,
            last_registration_time=1234567890000,
            last_heartbeat_time=1234567891000,
            last_metrics_time=1234567892000,
            last_asset_sync_time=1234567893000,
        )
        fam_client.register_runtime = AsyncMock(return_value=report)
        
        await activity.perform()
        
        assert activity.get_runtime_id() == "test-runtime-123"
        assert report.is_reregistration() is True

    @pytest.mark.asyncio
    async def test_registration_failure_no_runtime_id(self, context, fam_client, runtime_config):
        """Test registration failure when no runtime ID returned."""
        activity = RegisterRuntimeActivity(context, fam_client, runtime_config)
        
        # Mock registration returning None
        fam_client.register_runtime = AsyncMock(return_value=None)
        
        # The error message will be wrapped by retry logic
        with pytest.raises(RegistrationError, match="Runtime registration failed"):
            await activity.perform()

    @pytest.mark.asyncio
    async def test_registration_failure_exception(self, context, fam_client, runtime_config):
        """Test registration failure with exception."""
        activity = RegisterRuntimeActivity(context, fam_client, runtime_config)
        
        # Mock registration raising exception
        fam_client.register_runtime = AsyncMock(side_effect=Exception("Connection failed"))
        
        with pytest.raises(RegistrationError, match="Runtime registration failed"):
            await activity.perform()

    @pytest.mark.asyncio
    async def test_registration_with_retry(self, context, fam_client, runtime_config):
        """Test registration with retry logic."""
        activity = RegisterRuntimeActivity(context, fam_client, runtime_config)
        
        # Mock registration succeeding on second attempt
        report = ReregistrationReport(
            runtime_id="runtime-789",
            status_code=201,
        )
        fam_client.register_runtime = AsyncMock(side_effect=[
            Exception("Temporary failure"),
            report
        ])
        
        await activity.perform()
        
        assert activity.get_runtime_id() == "runtime-789"
        assert fam_client.register_runtime.await_count == 2


class TestSendHeartbeatActivity:
    """Test heartbeat activity."""

    @pytest.fixture
    def context(self):
        """Create activity context."""
        return ActivityContext(
            runtime_id="test-runtime-123",
            fam_base_url="https://fam.example.com",
            config={}
        )

    @pytest.fixture
    def fam_client(self):
        """Create mock FAM client."""
        return AsyncMock()

    def test_get_interval_seconds(self, context, fam_client):
        """Test getting heartbeat interval."""
        activity = SendHeartbeatActivity(context, fam_client, heartbeat_interval=120)
        assert activity.get_interval_seconds() == 120

    @pytest.mark.asyncio
    async def test_successful_heartbeat(self, context, fam_client):
        """Test successful heartbeat."""
        activity = SendHeartbeatActivity(context, fam_client, heartbeat_interval=60)
        
        fam_client.send_heartbeat = AsyncMock(return_value=True)
        
        await activity.perform()
        
        fam_client.send_heartbeat.assert_awaited_once_with("test-runtime-123")
        assert activity._consecutive_failures == 0
        assert activity._total_heartbeats_sent == 1

    @pytest.mark.asyncio
    async def test_heartbeat_failure(self, context, fam_client):
        """Test heartbeat failure."""
        activity = SendHeartbeatActivity(context, fam_client, heartbeat_interval=60)
        
        fam_client.send_heartbeat = AsyncMock(return_value=False)
        
        with pytest.raises(SyncError, match="Failed to send heartbeat"):
            await activity.perform()
        
        assert activity._consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_heartbeat_consecutive_failures(self, context, fam_client):
        """Test tracking consecutive failures."""
        activity = SendHeartbeatActivity(context, fam_client, heartbeat_interval=60)
        
        fam_client.send_heartbeat = AsyncMock(return_value=False)
        
        # First failure
        with pytest.raises(SyncError):
            await activity.perform()
        assert activity._consecutive_failures == 1
        
        # Second failure
        with pytest.raises(SyncError):
            await activity.perform()
        assert activity._consecutive_failures == 2

    @pytest.mark.asyncio
    async def test_heartbeat_resets_failures_on_success(self, context, fam_client):
        """Test that successful heartbeat resets failure count."""
        activity = SendHeartbeatActivity(context, fam_client, heartbeat_interval=60)
        activity._consecutive_failures = 5
        
        fam_client.send_heartbeat = AsyncMock(return_value=True)
        
        await activity.perform()
        
        assert activity._consecutive_failures == 0


class TestSendMetricsActivity:
    """Test metrics activity."""

    @pytest.fixture
    def context(self):
        """Create activity context."""
        return ActivityContext(
            runtime_id="test-runtime-123",
            fam_base_url="https://fam.example.com",
            config={}
        )

    @pytest.fixture
    def fam_client(self):
        """Create mock FAM client."""
        return AsyncMock()

    def test_get_interval_seconds(self, context, fam_client):
        """Test getting metrics interval."""
        activity = SendMetricsActivity(context, fam_client, metrics_interval=300)
        assert activity.get_interval_seconds() == 300

    @pytest.mark.asyncio
    async def test_successful_metrics_submission(self, context, fam_client):
        """Test successful metrics submission."""
        activity = SendMetricsActivity(context, fam_client, metrics_interval=300)
        
        fam_client.submit_metrics = AsyncMock(return_value=True)
        
        with patch('plugins.apiconnect_fam.activities.send_metrics.SessionLocal') as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock database queries
            mock_db.query.return_value.filter.return_value.count.return_value = 10
            mock_db.query.return_value.filter.return_value.all.return_value = []
            
            await activity.perform()
        
        fam_client.submit_metrics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_metrics_failure(self, context, fam_client):
        """Test metrics submission logs error when FAM API fails."""
        activity = SendMetricsActivity(context, fam_client, metrics_interval=300)
        
        fam_client.submit_metrics = AsyncMock(return_value=False)
        
        with patch('plugins.apiconnect_fam.activities.send_metrics.SessionLocal') as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_db.query.return_value.filter.return_value.count.return_value = 0
            mock_db.query.return_value.filter.return_value.all.return_value = []
            
            # Metrics failure logs error but doesn't raise (graceful degradation)
            await activity.perform()
            
            # Verify metrics were attempted
            fam_client.submit_metrics.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_metrics_database_error(self, context, fam_client):
        """Test metrics collection with database error."""
        activity = SendMetricsActivity(context, fam_client, metrics_interval=300)
        
        with patch('plugins.apiconnect_fam.activities.send_metrics.SessionLocal') as mock_session:
            mock_session.side_effect = Exception("Database connection failed")
            
            # Error message will be wrapped by retry logic
            with pytest.raises(SyncError, match="Failed to send metrics"):
                await activity.perform()


class TestAbstractScheduledActivity:
    """Test abstract scheduled activity base class."""

    @pytest.fixture
    def context(self):
        """Create activity context."""
        return ActivityContext(
            runtime_id="test-runtime-123",
            fam_base_url="https://fam.example.com",
            config={}
        )

    def test_should_execute_first_time(self, context):
        """Test should_execute returns True on first call."""
        from plugins.apiconnect_fam.activities.base import AbstractScheduledActivity
        
        class TestActivity(AbstractScheduledActivity):
            def get_interval_seconds(self):
                return 60
            
            async def perform(self):
                pass
        
        activity = TestActivity(context)
        assert activity.should_execute() is True

    def test_should_execute_respects_interval(self, context):
        """Test should_execute respects interval."""
        from plugins.apiconnect_fam.activities.base import AbstractScheduledActivity
        
        class TestActivity(AbstractScheduledActivity):
            def get_interval_seconds(self):
                return 60
            
            async def perform(self):
                pass
        
        activity = TestActivity(context)
        activity.last_execution_time = time.time()
        
        # Should not execute immediately after
        assert activity.should_execute() is False
        
        # Should execute after interval
        activity.last_execution_time = time.time() - 61
        assert activity.should_execute() is True

    @pytest.mark.asyncio
    async def test_execute_updates_last_execution(self, context):
        """Test execute updates last execution time."""
        from plugins.apiconnect_fam.activities.base import AbstractScheduledActivity
        
        class TestActivity(AbstractScheduledActivity):
            def get_interval_seconds(self):
                return 60
            
            async def perform(self):
                pass
        
        activity = TestActivity(context)
        initial_time = activity.last_execution_time
        
        await activity.execute()
        
        assert activity.last_execution_time is not None
        if initial_time is not None:
            assert activity.last_execution_time > initial_time


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
