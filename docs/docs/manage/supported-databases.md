# Supported Databases

MCP Gateway supports multiple database backends with full feature parity across all supported systems.

## Database Support Matrix

| Database    | Support Level | Production Ready | Connection String Example                                    | Notes                          |
|-------------|---------------|------------------|--------------------------------------------------------------|--------------------------------|
| SQLite      | ✅ Full       | ✅ Yes           | `sqlite:///./mcp.db`                                        | Default, file-based            |
| PostgreSQL  | ✅ Full       | ✅ Yes           | `postgresql://postgres:changeme@localhost:5432/mcp`         | Recommended for production     |
| MariaDB     | ✅ Full       | ✅ Yes           | `mysql+pymysql://mysql:changeme@localhost:3306/mcp`         | **36+ tables**, MariaDB 10.6+ |
| MySQL       | ✅ Full       | ✅ Yes           | `mysql+pymysql://admin:changeme@localhost:3306/mcp`         | Alternative MySQL variant      |

## MariaDB/MySQL Configuration

### Connection String Format

```bash
# MariaDB (recommended)
DATABASE_URL=mysql+pymysql://[username]:[password]@[host]:[port]/[database]

# Examples:
DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp
DATABASE_URL=mysql+pymysql://admin:secret123@mariadb.example.com:3306/mcpgateway
DATABASE_URL=mysql+pymysql://mcpuser:mypassword@192.168.1.100:3306/mcp_production
```

### Version Requirements

- **MariaDB**: 10.6+ (recommended)
- **MySQL**: 8.0+ (supported)

### Driver Requirements

The `pymysql` driver is included by default in all MCP Gateway installations:

```bash
# Already included - no additional installation needed
pip install mcp-contextforge-gateway
```

### Database Schema Compatibility

MCP Gateway's database schema is fully compatible with MariaDB/MySQL:

- **36+ database tables** work perfectly with MariaDB 10.6+ and MySQL 8.0+
- All **VARCHAR length issues** have been resolved for MariaDB/MySQL compatibility
- Complete feature parity with SQLite and PostgreSQL
- Supports all MCP Gateway features including federation, caching, and A2A agents

## Known Limitations

### MariaDB/MySQL Specific Limitations

1. **No Partial JSONPath Index Support**
   - MariaDB/MySQL do not support partial indexes on JSON paths
   - Full table scans may occur for complex JSON queries
   - **Workaround**: Use additional indexed columns for frequently queried JSON fields

2. **Foreign Key Length Constraints**
   - Foreign key column names are limited to 64 characters
   - Some composite foreign keys may require shorter naming
   - **Impact**: Minimal - affects only internal schema design

3. **Case Sensitivity**
   - Table and column names are case-sensitive on Linux, case-insensitive on Windows/macOS
   - **Recommendation**: Use consistent lowercase naming for portability

4. **JSON Data Type Differences**
   - MariaDB JSON is stored as LONGTEXT with validation
   - MySQL has native JSON data type with better performance
   - **Impact**: Functional compatibility maintained, performance may vary

### General Database Limitations

1. **SQLite Connection Limits**
   - SQLite is limited to 50 connections in pool (vs 200 for other databases)
   - **Recommendation**: Use PostgreSQL or MariaDB for high-concurrency deployments

2. **MongoDB Schema Flexibility**
   - MongoDB's schemaless nature may allow invalid data structures
   - **Mitigation**: Application-level validation enforced regardless of backend

## Performance Considerations

### MariaDB/MySQL Optimization

```bash
# Recommended connection pool settings for MariaDB/MySQL
DB_POOL_SIZE=200              # Maximum persistent connections
DB_MAX_OVERFLOW=20            # Additional connections beyond pool_size
DB_POOL_TIMEOUT=30            # Seconds to wait for connection
DB_POOL_RECYCLE=3600          # Seconds before recreating connection
```

### Index Optimization

MariaDB/MySQL benefit from these additional indexes for large deployments:

```sql
-- Recommended indexes for high-performance deployments
CREATE INDEX idx_tools_team_created ON tools(team_id, created_at);
CREATE INDEX idx_resources_owner_uri ON resources(owner_email, uri);
CREATE INDEX idx_prompts_team_name ON prompts(team_id, name);
```

## Migration Between Databases

### PostgreSQL to MariaDB Migration

MariaDB is fully compatible with PostgreSQL schemas used by MCP Gateway. Simply update your `DATABASE_URL` to point to MariaDB:

```bash
# Change from PostgreSQL
# DATABASE_URL=postgresql://postgres:changeme@localhost:5432/mcp

# To MariaDB
DATABASE_URL=mysql+pymysql://mysql:changeme@localhost:3306/mcp
```

The gateway will automatically handle schema creation and migrations when started with the new database URL.

### SQLite to MariaDB Migration

```bash
# 1. Export SQLite data
sqlite3 mcp.db .dump > mcp_backup.sql

# 2. Convert SQLite syntax to MySQL
sed -i 's/AUTOINCREMENT/AUTO_INCREMENT/g' mcp_backup.sql
sed -i 's/INTEGER PRIMARY KEY/INT AUTO_INCREMENT PRIMARY KEY/g' mcp_backup.sql

# 3. Import to MariaDB
mysql -u mysql -p mcp < mcp_backup.sql
```

## Troubleshooting

### Common MariaDB/MySQL Issues

1. **Connection Refused**
   ```bash
   # Check MariaDB service status
   sudo systemctl status mariadb

   # Verify port is open
   netstat -tlnp | grep 3306
   ```

2. **Authentication Failures**
   ```bash
   # Reset user password
   sudo mariadb -e "ALTER USER 'mysql'@'localhost' IDENTIFIED BY 'newpassword';"
   sudo mariadb -e "FLUSH PRIVILEGES;"
   ```

3. **Permission Denied**
   ```bash
   # Grant all privileges
   sudo mariadb -e "GRANT ALL PRIVILEGES ON mcp.* TO 'mysql'@'%' IDENTIFIED BY 'changeme';"
   sudo mariadb -e "FLUSH PRIVILEGES;"
   ```

4. **Character Set Issues**
   ```bash
   # Set UTF-8 character set
   sudo mariadb -e "ALTER DATABASE mcp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
   ```

## Related Documentation

- [Configuration Reference](configuration.md) - Complete database configuration options
- [Docker Compose Deployment](../deployment/compose.md) - MariaDB container setup
- [Kubernetes Deployment](../deployment/kubernetes.md) - MariaDB in Kubernetes
- [Performance Tuning](tuning.md) - Database optimization guidelines
