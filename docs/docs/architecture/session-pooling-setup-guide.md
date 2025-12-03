# Session Pooling Setup Guide

## Quick Start

Session pooling improves performance and maintains state continuity by reusing MCP sessions across requests. Follow these steps to enable it.

## Step 1: Enable Global Pooling

### Option A: Update `.env` file (Recommended)

1. Copy `.env.example` to `.env` if you haven't already:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set:
   ```bash
   SESSION_POOL_ENABLED=true
   ```

3. Optionally configure other pool settings:
   ```bash
   SESSION_POOL_STRATEGY=round_robin
   SESSION_POOL_SIZE=5
   SESSION_POOL_TTL=3600
   SESSION_POOL_MAX_IDLE_TIME=300
   SESSION_POOL_CLEANUP_INTERVAL=60
   SESSION_POOL_METRICS_ENABLED=true
   SESSION_POOL_HEALTH_CHECK_INTERVAL=60
   SESSION_POOL_REBALANCE_INTERVAL=300
   ```

### Option B: Set Environment Variable

```bash
export SESSION_POOL_ENABLED=true
```

## Step 2: Restart the Gateway

```bash
# If running with make
make serve

# Or if running directly
mcpgateway --host 0.0.0.0 --port 4444
```

## Step 3: Enable Pooling for Servers

### Via Admin UI (Recommended)

#### 3.1 Navigate to Pool Configuration

1. Open your browser: `http://localhost:4444/admin`
2. Click **"Servers"** in the left sidebar
3. Find your server in the list
4. Click the **"🔄 Pool Config"** button (cyan/teal button in Actions column)

**Button Location:**
```
Actions Column:
Row 1: [Edit]
Row 2: [🔄 Pool Config] [📊 Pool Stats]  ← Click here
Row 3: [Export Config]
Row 4: [Activate/Deactivate] [Delete]
```

#### 3.2 Enable Session Pooling

A modal dialog opens with title **"🔄 Pool Configuration"**

1. **Toggle "Enable Session Pooling"** to ON (turns blue)
2. Additional configuration fields will appear

**Visual Change:**
```
Before: Enable Session Pooling  [○────]  (Gray/Off)
After:  Enable Session Pooling  [────●]  (Blue/On)
```

#### 3.3 Configure Pool Settings

Once enabled, configure these settings:

**Pool Strategy** (Dropdown)
- Select: **Round Robin** (recommended for general use)
- Other options: Least Connections, Sticky Sessions, Weighted, None

**Pool Sizes** (3 fields)
```
Min Size: 2    Max Size: 10    Target Size: 5
```
- **Min Size**: Minimum sessions to maintain (recommended: 2)
- **Max Size**: Maximum sessions allowed (recommended: 10)
- **Target Size**: Ideal number of sessions (recommended: 5)

**Timeouts** (2 fields)
```
Idle Timeout: 300 seconds    Max Lifetime: 3600 seconds
```
- **Idle Timeout**: How long unused sessions stay alive (5 minutes)
- **Max Lifetime**: Maximum age of any session (1 hour)

**Additional Options**
- ✅ **Enable Auto-scaling**: ON (allows pool to grow/shrink with demand)
- **Health Check Threshold**: 70% (minimum success rate for healthy status)

#### 3.4 Save Configuration

1. Click **"Save Configuration"** button (blue, bottom right)
2. Pool is created immediately (no restart needed)
3. Success notification appears: "Pool configuration saved successfully"
4. Modal closes automatically

### Via API

```bash
# Get your JWT token
export TOKEN="your-jwt-token-here"

# Enable pooling for a server
curl -X PUT "http://localhost:4444/servers/{server_id}/pool/config" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "enabled": true,
    "size": 5,
    "strategy": "round_robin",
    "min_size": 2,
    "max_size": 10,
    "timeout": 30,
    "max_idle_time": 3600,
    "auto_scale": true,
    "health_check_interval": 60,
    "rebalance_interval": 300
  }'
```

## Step 4: Verify Pool Creation

### Check Server Logs

Look for these log messages:
```
INFO - SessionPoolManager initialized with 0 pools
INFO - Creating/updating pool for server {server_id} with strategy=PoolStrategy.ROUND_ROBIN, min_size=2, max_size=10
INFO - Created new pool {pool_id} for server {server_id}
INFO - Successfully created/updated pool {pool_id} for server {server_id}
```

### Check Pool Health Dashboard

1. Go to `http://localhost:4444/admin`
2. Click **"Pool Health"** in the left sidebar
3. You should see your server's pool listed with:
   - Status: healthy (green indicator)
   - Health Score: 100 (or close to it)
   - Total Sessions: 5 (or your configured size)
   - Active Sessions: 0
   - Available Sessions: 5

### Test Pool Stats

1. Go to the Servers page
2. Find your server
3. Click **"📊 Pool Stats"** button (same row as Pool Config)
4. A modal should open showing:
   - Pool ID and strategy
   - Session counts (total, active, available)
   - Health score
   - Acquisition metrics (acquisitions, releases, timeouts)

**Before enabling pooling**: 503 error "Pooling not enabled for server"
**After enabling pooling**: Pool statistics displayed successfully

## Configuration Reference

### Global Settings (`.env`)

| Setting | Default | Description |
|---------|---------|-------------|
| `SESSION_POOL_ENABLED` | `false` | Enable/disable session pooling globally |
| `SESSION_POOL_STRATEGY` | `round_robin` | Default strategy for new servers |
| `SESSION_POOL_SIZE` | `5` | Default pool size |
| `SESSION_POOL_TTL` | `3600` | Session lifetime (seconds) |
| `SESSION_POOL_MAX_IDLE_TIME` | `300` | Max idle time before cleanup (seconds) |
| `SESSION_POOL_CLEANUP_INTERVAL` | `60` | Cleanup task interval (seconds) |
| `SESSION_POOL_METRICS_ENABLED` | `true` | Enable metrics collection |
| `SESSION_POOL_HEALTH_CHECK_INTERVAL` | `60` | Health check interval (seconds) |
| `SESSION_POOL_REBALANCE_INTERVAL` | `300` | Rebalancing interval (seconds) |

### Per-Server Settings (via UI or API)

| Setting | Default | Range | Description |
|---------|---------|-------|-------------|
| `enabled` | `false` | - | Enable pooling for this server |
| `strategy` | `round_robin` | - | Pooling strategy |
| `size` | `5` | 1-1000 | Target pool size |
| `min_size` | `1` | 1-1000 | Minimum pool size |
| `max_size` | `10` | 1-1000 | Maximum pool size |
| `timeout` | `30` | 1-300 | Acquisition timeout (seconds) |
| `max_idle_time` | `3600` | 60-86400 | Max idle time (seconds) |
| `auto_scale` | `false` | - | Enable auto-scaling |
| `health_check_interval` | `60` | 10-3600 | Health check interval (seconds) |
| `rebalance_interval` | `300` | 60-3600 | Rebalancing interval (seconds) |

## Pooling Strategies

### Round Robin (Recommended)
- **Use Case**: General purpose, balanced load distribution
- **Pros**: Simple, fair distribution, predictable
- **Cons**: Doesn't consider session load

### Least Connections
- **Use Case**: Workloads with varying request durations
- **Pros**: Load-aware, optimal for mixed workloads
- **Cons**: Slightly more complex, requires connection tracking

### Sticky Sessions
- **Use Case**: Stateful applications requiring session affinity
- **Pros**: Maintains state, reduces context switching
- **Cons**: Uneven distribution, session failure affects specific users

### Weighted
- **Use Case**: Heterogeneous resources or priority-based routing
- **Pros**: Flexible, supports priorities, resource-aware
- **Cons**: Requires weight configuration, more complex setup

### None (Direct)
- **Use Case**: Disable pooling for specific servers
- **Pros**: Simple, no overhead
- **Cons**: No performance benefits, no state continuity

## Troubleshooting

### Pool Not Created

**Symptom**: 404 error when viewing pool stats

**Causes**:
1. Global pooling disabled (`SESSION_POOL_ENABLED=false`)
2. Server pooling disabled (`pool_enabled=false` in database)
3. Pool creation failed (check logs)

**Solution**:
1. Check `.env` file: `SESSION_POOL_ENABLED=true`
2. Enable pooling via Pool Config UI
3. Check server logs for errors
4. Restart gateway if needed

### Pool Stats Show 503 Error

**Symptom**: "Pooling not enabled for server" error

**Cause**: Server has `pool_enabled=false` in database

**Solution**: Enable pooling via Pool Config UI (Step 3)

### Pool Creation Fails Silently

**Symptom**: Config saves but pool not created

**Causes**:
1. Pool manager not initialized
2. Database transaction issue
3. Invalid configuration

**Solution**:
1. Check startup logs for "SessionPoolManager initialized"
2. Verify database is writable
3. Check for validation errors in logs

### Sessions Not Reused

**Symptom**: New session created for each request

**Causes**:
1. Pool size too small
2. Sessions timing out
3. Health checks failing

**Solution**:
1. Increase pool size
2. Increase `max_idle_time`
3. Check health check logs

### Pool Config Button Not Responding

**Symptom**: Clicking Pool Config button does nothing

**Solution**:
1. Check browser console (F12) for JavaScript errors
2. Verify `pools.js` is loaded
3. Refresh the page and try again

## Best Practices

1. **Start Small**: Begin with `size=5`, `min_size=2`, `max_size=10`
2. **Enable Auto-scaling**: Let the pool adjust based on demand
3. **Monitor Health**: Check Pool Health dashboard regularly
4. **Use Round Robin**: Best for most use cases
5. **Set Reasonable Timeouts**: 30s acquisition, 1h idle time
6. **Enable Metrics**: Track performance and optimize
7. **Test Thoroughly**: Verify pool behavior under load

## Performance Tips

1. **Pool Size**: Set based on expected concurrent requests
2. **Idle Time**: Balance between reuse and resource usage
3. **Health Checks**: More frequent = better reliability, more overhead
4. **Rebalancing**: Less frequent = more stable, slower adaptation
5. **Strategy**: Round robin for balanced, least connections for variable load

## Verification Checklist

After enabling pooling, verify:

- [ ] Pool Config modal shows "Enable Session Pooling" as ON (blue toggle)
- [ ] Pool Stats button opens modal without 503 error
- [ ] Pool Stats shows correct session counts
- [ ] Pool Health dashboard lists your server's pool
- [ ] Pool health score is 100 (or close to it)
- [ ] Server logs show successful pool creation

## Related Documentation

- [Session Pooling Architecture](./session-pooling.md) - Technical implementation details
- [Deployment Guide](../deployment/session-pooling.md) - Production deployment
- [User Guide](../using/session-pooling.md) - Feature overview and usage
- [API Reference](../using/api/pool-management.md) - Complete API documentation

## Support

If you encounter issues:
1. Check server logs for errors
2. Verify configuration in `.env` and database
3. Test with a simple server first
4. Review troubleshooting section above
5. Check GitHub issues for similar problems