"""
Unit tests for version_control_core.py

Tests the core version control logic including:
- Hash computation (HashComputer)
- Database management (VersionControlDB)
- Version control operations (VersionControlCore)
"""

import hashlib
import json
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from plugins.version_control.core.version_control_core import (
    HashComputer,
    VersionControlDB,
    VersionControlCore,
    ServerVersion,
    Base,
)


class TestHashComputer:
    """Test suite for HashComputer class"""

    def test_compute_tools_hash_empty_list(self):
        """Test hash computation with empty tools list"""
        tools = []
        hash_result = HashComputer.compute_tools_hash(tools)
        
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64  # SHA256 produces 64-char hex string
        
    def test_compute_tools_hash_single_tool(self):
        """Test hash computation with single tool"""
        tools = [
            {"name": "add", "input_schema": {"type": "object", "properties": {}}}
        ]
        hash_result = HashComputer.compute_tools_hash(tools)
        
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64
        
    def test_compute_tools_hash_multiple_tools(self):
        """Test hash computation with multiple tools"""
        tools = [
            {"name": "add", "input_schema": {"type": "object"}},
            {"name": "multiply", "input_schema": {"type": "object"}},
            {"name": "divide", "input_schema": {"type": "object"}},
        ]
        hash_result = HashComputer.compute_tools_hash(tools)
        
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64
        
    def test_compute_tools_hash_deterministic(self):
        """Test that same tools produce same hash"""
        tools = [
            {"name": "add", "input_schema": {"type": "object"}},
            {"name": "multiply", "input_schema": {"type": "object"}},
        ]
        
        hash1 = HashComputer.compute_tools_hash(tools)
        hash2 = HashComputer.compute_tools_hash(tools)
        
        assert hash1 == hash2
        
    def test_compute_tools_hash_order_independent(self):
        """Test that tool order doesn't affect hash (sorted internally)"""
        tools1 = [
            {"name": "add", "input_schema": {"type": "object"}},
            {"name": "multiply", "input_schema": {"type": "object"}},
        ]
        tools2 = [
            {"name": "multiply", "input_schema": {"type": "object"}},
            {"name": "add", "input_schema": {"type": "object"}},
        ]
        
        hash1 = HashComputer.compute_tools_hash(tools1)
        hash2 = HashComputer.compute_tools_hash(tools2)
        
        assert hash1 == hash2
        
    def test_compute_tools_hash_different_tools_different_hash(self):
        """Test that different tools produce different hashes"""
        tools1 = [{"name": "add", "input_schema": {"type": "object"}}]
        tools2 = [{"name": "multiply", "input_schema": {"type": "object"}}]
        
        hash1 = HashComputer.compute_tools_hash(tools1)
        hash2 = HashComputer.compute_tools_hash(tools2)
        
        assert hash1 != hash2
        
    def test_compute_tools_hash_schema_changes_affect_hash(self):
        """Test that schema changes produce different hashes"""
        tools1 = [{"name": "add", "input_schema": {"type": "object", "properties": {"a": {"type": "number"}}}}]
        tools2 = [{"name": "add", "input_schema": {"type": "object", "properties": {"b": {"type": "number"}}}}]
        
        hash1 = HashComputer.compute_tools_hash(tools1)
        hash2 = HashComputer.compute_tools_hash(tools2)
        
        assert hash1 != hash2
        
    def test_compute_version_hash_basic(self):
        """Test version hash computation"""
        server_version = "1.0.0"
        tools_hash = "a" * 64
        
        version_hash = HashComputer.compute_version_hash(server_version, tools_hash)
        
        assert isinstance(version_hash, str)
        assert len(version_hash) == 64
        
    def test_compute_version_hash_deterministic(self):
        """Test that same inputs produce same version hash"""
        server_version = "1.0.0"
        tools_hash = "abc123" * 10 + "abcd"  # 64 chars
        
        hash1 = HashComputer.compute_version_hash(server_version, tools_hash)
        hash2 = HashComputer.compute_version_hash(server_version, tools_hash)
        
        assert hash1 == hash2
        
    def test_compute_version_hash_different_version_different_hash(self):
        """Test that different server versions produce different hashes"""
        tools_hash = "a" * 64
        
        hash1 = HashComputer.compute_version_hash("1.0.0", tools_hash)
        hash2 = HashComputer.compute_version_hash("2.0.0", tools_hash)
        
        assert hash1 != hash2
        
    def test_compute_version_hash_different_tools_different_hash(self):
        """Test that different tools hashes produce different version hashes"""
        server_version = "1.0.0"
        
        hash1 = HashComputer.compute_version_hash(server_version, "a" * 64)
        hash2 = HashComputer.compute_version_hash(server_version, "b" * 64)
        
        assert hash1 != hash2


class TestVersionControlDB:
    """Test suite for VersionControlDB class"""
    
    @pytest.fixture
    def temp_db_urls(self, tmp_path):
        """Create temporary database URLs for testing"""
        main_db = tmp_path / "test_main.db"
        vc_db = tmp_path / "test_vc.db"
        return f"sqlite:///{main_db}", f"sqlite:///{vc_db}"
    
    def test_init_creates_engines(self, temp_db_urls):
        """Test that initialization creates database engines"""
        main_url, vc_url = temp_db_urls
        
        db_manager = VersionControlDB(main_db_url=main_url, vc_db_url=vc_url)
        
        assert db_manager.main_engine is not None
        assert db_manager.vc_engine is not None
        assert db_manager.MainSession is not None
        assert db_manager.VCSession is not None
        
    def test_create_tables_success(self, temp_db_urls):
        """Test that create_tables successfully creates tables"""
        main_url, vc_url = temp_db_urls
        
        db_manager = VersionControlDB(main_db_url=main_url, vc_db_url=vc_url)
        db_manager.create_tables()
        
        # Verify table exists by querying it
        session = db_manager.get_vc_session()
        try:
            # Should not raise an error
            result = session.execute("SELECT COUNT(*) FROM server_versions")
            count = result.scalar()
            assert count == 0  # Empty table
        finally:
            session.close()
            
    def test_get_main_session_returns_session(self, temp_db_urls):
        """Test that get_main_session returns a valid session"""
        main_url, vc_url = temp_db_urls
        
        db_manager = VersionControlDB(main_db_url=main_url, vc_db_url=vc_url)
        session = db_manager.get_main_session()
        
        assert session is not None
        session.close()
        
    def test_get_vc_session_returns_session(self, temp_db_urls):
        """Test that get_vc_session returns a valid session"""
        main_url, vc_url = temp_db_urls
        
        db_manager = VersionControlDB(main_db_url=main_url, vc_db_url=vc_url)
        db_manager.create_tables()
        session = db_manager.get_vc_session()
        
        assert session is not None
        session.close()


class TestVersionControlCore:
    """Test suite for VersionControlCore class"""
    
    @pytest.fixture
    def temp_db_urls(self, tmp_path):
        """Create temporary database URLs for testing"""
        main_db = tmp_path / "test_main.db"
        vc_db = tmp_path / "test_vc.db"
        return f"sqlite:///{main_db}", f"sqlite:///{vc_db}"
    
    @pytest.fixture
    def db_manager(self, temp_db_urls):
        """Create a test database manager"""
        main_url, vc_url = temp_db_urls
        db_mgr = VersionControlDB(main_db_url=main_url, vc_db_url=vc_url)
        db_mgr.create_tables()
        return db_mgr
    
    @pytest.fixture
    def vc_core(self, db_manager):
        """Create a VersionControlCore instance"""
        return VersionControlCore(db_manager)
    
    def test_init_creates_hash_computer(self, vc_core):
        """Test that initialization creates hash computer"""
        assert vc_core.hash_computer is not None
        assert isinstance(vc_core.hash_computer, HashComputer)
        
    def test_discover_existing_servers_empty(self, vc_core, db_manager):
        """Test discovering servers when none exist"""
        # Create empty gateways table in main DB
        session = db_manager.get_main_session()
        try:
            session.execute("""
                CREATE TABLE IF NOT EXISTS gateways (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    url TEXT,
                    transport TEXT,
                    is_active BOOLEAN
                )
            """)
            session.commit()
        finally:
            session.close()
            
        servers = vc_core.discover_existing_servers()
        assert servers == []
        
    @pytest.mark.asyncio
    async def test_create_initial_version_with_mocked_server(self, vc_core, db_manager):
        """Test creating initial version with mocked server info"""
        gateway_id = 1
        
        # Mock get_server_info to return test data
        with patch.object(vc_core, 'get_server_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = {
                'name': 'test-server',
                'version': '1.0.0',
                'url': 'http://localhost:8000',
                'transport': 'sse',
                'authentication': None
            }
            
            # Mock compute_hashes_for_gateway
            with patch.object(vc_core, 'compute_hashes_for_gateway', new_callable=AsyncMock) as mock_compute:
                mock_compute.return_value = ('tools_hash_123', 'version_hash_456', 5)
                
                version = await vc_core.create_initial_version(gateway_id, created_by="test")
                
                assert version is not None
                assert version.gateway_id == gateway_id
                assert version.version_number == 1
                assert version.status == 'active'
                assert version.is_current is True
                assert version.tools_count == 5
                
    @pytest.mark.asyncio
    async def test_check_for_changes_no_existing_version(self, vc_core):
        """Test checking for changes when no version exists"""
        gateway_id = 999  # Non-existent gateway
        
        has_changes = await vc_core.check_for_changes(gateway_id)
        
        # Should return False when no version exists
        assert has_changes is False
        
    @pytest.mark.asyncio
    async def test_check_for_changes_detects_tool_addition(self, vc_core, db_manager):
        """Test that check_for_changes detects when tools are added"""
        gateway_id = 1
        
        # Create initial version
        session = db_manager.get_vc_session()
        try:
            initial_version = ServerVersion(
                gateway_id=gateway_id,
                server_name="test-server",
                server_version="1.0.0",
                version_number=1,
                tools_hash="old_hash",
                version_hash="old_version_hash",
                tools_count=2,
                is_current=True,
                status='active',
                created_by="test"
            )
            session.add(initial_version)
            session.commit()
        finally:
            session.close()
            
        # Mock get_server_info and compute_hashes to return different hash
        with patch.object(vc_core, 'get_server_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = {
                'name': 'test-server',
                'version': '1.0.0',
                'url': 'http://localhost:8000',
                'transport': 'sse',
                'authentication': None
            }
            
            with patch.object(vc_core, 'compute_hashes_for_gateway', new_callable=AsyncMock) as mock_compute:
                # Return different hash to simulate changes
                mock_compute.return_value = ('new_tools_hash', 'new_version_hash', 3)
                
                has_changes = await vc_core.check_for_changes(gateway_id)
                
                assert has_changes is True
                
    @pytest.mark.asyncio
    async def test_check_for_changes_no_changes(self, vc_core, db_manager):
        """Test that check_for_changes returns False when no changes"""
        gateway_id = 1
        tools_hash = "same_hash"
        version_hash = "same_version_hash"
        
        # Create initial version
        session = db_manager.get_vc_session()
        try:
            initial_version = ServerVersion(
                gateway_id=gateway_id,
                server_name="test-server",
                server_version="1.0.0",
                version_number=1,
                tools_hash=tools_hash,
                version_hash=version_hash,
                tools_count=2,
                is_current=True,
                status='active',
                created_by="test"
            )
            session.add(initial_version)
            session.commit()
        finally:
            session.close()
            
        # Mock to return same hash
        with patch.object(vc_core, 'get_server_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = {
                'name': 'test-server',
                'version': '1.0.0',
                'url': 'http://localhost:8000',
                'transport': 'sse',
                'authentication': None
            }
            
            with patch.object(vc_core, 'compute_hashes_for_gateway', new_callable=AsyncMock) as mock_compute:
                # Return same hash - no changes
                mock_compute.return_value = (tools_hash, version_hash, 2)
                
                has_changes = await vc_core.check_for_changes(gateway_id)
                
                assert has_changes is False
                
    @pytest.mark.asyncio
    async def test_create_pending_version_increments_version_number(self, vc_core, db_manager):
        """Test that create_pending_version increments version number correctly"""
        gateway_id = 1
        
        # Create initial version
        session = db_manager.get_vc_session()
        try:
            initial_version = ServerVersion(
                gateway_id=gateway_id,
                server_name="test-server",
                server_version="1.0.0",
                version_number=1,
                tools_hash="old_hash",
                version_hash="old_version_hash",
                tools_count=2,
                is_current=True,
                status='active',
                created_by="test"
            )
            session.add(initial_version)
            session.commit()
        finally:
            session.close()
            
        # Mock server info and hashes
        with patch.object(vc_core, 'get_server_info', new_callable=AsyncMock) as mock_get_info:
            mock_get_info.return_value = {
                'name': 'test-server',
                'version': '1.0.0',
                'url': 'http://localhost:8000',
                'transport': 'sse',
                'authentication': None
            }
            
            with patch.object(vc_core, 'compute_hashes_for_gateway', new_callable=AsyncMock) as mock_compute:
                mock_compute.return_value = ('new_hash', 'new_version_hash', 3)
                
                pending_version = await vc_core.create_pending_version(gateway_id, created_by="test")
                
                assert pending_version is not None
                assert pending_version.version_number == 2  # Incremented from 1
                assert pending_version.status == 'pending'
                assert pending_version.is_current is True
                
    def test_update_version_status_to_active(self, vc_core, db_manager):
        """Test updating version status from pending to active"""
        gateway_id = 1
        
        # Create pending version
        session = db_manager.get_vc_session()
        try:
            pending_version = ServerVersion(
                gateway_id=gateway_id,
                server_name="test-server",
                server_version="1.0.0",
                version_number=2,
                tools_hash="hash",
                version_hash="version_hash",
                tools_count=3,
                is_current=True,
                status='pending',
                created_by="test"
            )
            session.add(pending_version)
            session.commit()
            version_id = pending_version.id
        finally:
            session.close()
            
        # Update to active
        success = vc_core.update_version_status(version_id, 'active', updated_by="admin")
        
        assert success is True
        
        # Verify status changed
        session = db_manager.get_vc_session()
        try:
            updated = session.query(ServerVersion).filter_by(id=version_id).first()
            assert updated.status == 'active'
        finally:
            session.close()
            
    def test_update_version_status_to_deactivated(self, vc_core, db_manager):
        """Test updating version status to deactivated"""
        gateway_id = 1
        
        # Create active version
        session = db_manager.get_vc_session()
        try:
            active_version = ServerVersion(
                gateway_id=gateway_id,
                server_name="test-server",
                server_version="1.0.0",
                version_number=1,
                tools_hash="hash",
                version_hash="version_hash",
                tools_count=2,
                is_current=True,
                status='active',
                created_by="test"
            )
            session.add(active_version)
            session.commit()
            version_id = active_version.id
        finally:
            session.close()
            
        # Update to deactivated
        success = vc_core.update_version_status(version_id, 'deactivated', updated_by="admin")
        
        assert success is True
        
        # Verify status changed
        session = db_manager.get_vc_session()
        try:
            updated = session.query(ServerVersion).filter_by(id=version_id).first()
            assert updated.status == 'deactivated'
        finally:
            session.close()

# Made with Bob
