# Collaborative Filtering & Usage Analytics

## Overview

This implementation adds a comprehensive collaborative filtering recommendation system to MCP Gateway that learns from user behavior to suggest relevant tools. The system combines user similarity analysis with privacy-aware analytics to provide personalized tool recommendations.

## Features

### 1. **Usage Analytics Service** ([usage_analytics_service.py](mcpgateway/services/usage_analytics_service.py))
- Real-time tool usage event ingestion with async buffering
- Privacy-aware recording (respects opt-out preferences)
- User data export (GDPR/CCPA compliance)
- Background cleanup with configurable retention periods
- Redis caching for opt-out status checks

### 2. **User Similarity Service** ([user_similarity_service.py](mcpgateway/services/user_similarity_service.py))
- Multiple similarity algorithms:
  - **Cosine similarity**: frequency-weighted tool usage vectors
  - **Jaccard similarity**: intersection over union of tool sets
  - **Dice coefficient**: 2 * intersection / sum of sizes
  - **Overlap coefficient**: intersection / min size
- Redis caching for precomputed similarities
- Background precomputation for active users (optional)
- Configurable minimum interaction thresholds

### 3. **Collaborative Recommender** ([collaborative_recommender.py](mcpgateway/services/collaborative_recommender.py))
- User-based collaborative filtering
- Weighted scoring combining popularity and similarity
- Integration with semantic search (boosts existing results)
- Trending tools analysis
- Role-based recommendations
- Includes reasoning traces for explainability

### 4. **Analytics API** ([analytics_router.py](mcpgateway/routers/analytics_router.py))
RESTful endpoints for analytics and recommendations:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/analytics/tool-usage` | POST | Record tool execution event |
| `/api/v1/users/me/preferences` | GET/PUT | Manage analytics preferences |
| `/api/v1/users/me/usage-data` | GET | Export user data (GDPR) |
| `/api/v1/users/me/usage-data` | DELETE | Delete user data (right to erasure) |
| `/api/v1/recommendations/tools` | GET | Get personalized recommendations |
| `/api/v1/recommendations/stats` | GET | Get recommendation system stats |
| `/api/v1/users/similar` | GET | Get similar users |
| `/api/v1/tools/trending` | GET | Get trending tools |

## Database Schema

### `tool_usage_events` Table
Stores individual tool execution events for collaborative filtering.

```sql
CREATE TABLE tool_usage_events (
    id VARCHAR(36) PRIMARY KEY,
    user_email VARCHAR(255) NOT NULL,
    tool_id VARCHAR(255) NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    execution_duration_ms INTEGER,
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    session_id VARCHAR(255),
    user_role VARCHAR(50),
    user_team_id VARCHAR(36),
    INDEX idx_usage_events_user_email (user_email),
    INDEX idx_usage_events_tool_id (tool_id),
    INDEX idx_usage_events_timestamp (timestamp),
    INDEX idx_usage_events_user_tool (user_email, tool_id),
    INDEX idx_usage_events_team_tool (user_team_id, tool_id)
);
```

### `user_preferences` Table
Tracks privacy preferences for analytics data collection.

```sql
CREATE TABLE user_preferences (
    user_email VARCHAR(255) PRIMARY KEY,
    analytics_opted_in BOOLEAN DEFAULT TRUE,
    data_retention_days INTEGER DEFAULT 90,
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_email) REFERENCES email_users(email) ON DELETE CASCADE
);
```

## Configuration

### Environment Variables

Add these to your `.env` file:

```bash
# Usage Analytics Configuration
ANALYTICS_ENABLED=true
ANALYTICS_RETENTION_DAYS=90
ANALYTICS_CLEANUP_ENABLED=true
ANALYTICS_CLEANUP_INTERVAL_HOURS=24
ANALYTICS_CLEANUP_BATCH_SIZE=10000

# Collaborative Filtering Configuration
COLLABORATIVE_FILTERING_ENABLED=true
CF_MIN_COMMON_TOOLS=2
CF_SIMILARITY_ALGORITHM=cosine  # cosine, jaccard, dice, overlap
CF_RECOMMENDATION_LIMIT=10
CF_MIN_USER_INTERACTIONS=3
CF_BOOST_WEIGHT=0.3  # 0.0-1.0 weight for CF boost in search

# Similarity Cache Configuration
SIMILARITY_CACHE_ENABLED=true
SIMILARITY_CACHE_TTL=3600
SIMILARITY_PRECOMPUTE_ENABLED=false
SIMILARITY_PRECOMPUTE_INTERVAL_HOURS=6

# Privacy Configuration
ANALYTICS_ALLOW_OPT_OUT=true
ANALYTICS_EXPORT_ENABLED=true
ANALYTICS_DELETE_ENABLED=true
```

### Config Class ([config.py](mcpgateway/config.py))

All settings are validated Pydantic fields with sane defaults:

- `analytics_enabled`: Master toggle for analytics system (default: `true`)
- `analytics_retention_days`: Days to retain usage events (30-730 days, default: `90`)
- `collaborative_filtering_enabled`: Enable CF recommendations (default: `true`)
- `cf_similarity_algorithm`: Algorithm choice (default: `"cosine"`)
- `cf_boost_weight`: Search result boosting weight (0.0-1.0, default: `0.3`)

## Integration with Semantic Search

The collaborative filtering system seamlessly integrates with existing semantic search in [meta_server/service.py](mcpgateway/meta_server/service.py):

1. **Semantic/keyword search** produces initial candidate tools
2. **Collaborative filtering boost** augments scores based on similar users' behavior
3. **Weighted combination**: `final_score = (1 - cf_weight) * semantic_score + cf_weight * cf_score`
4. **Re-ranking** produces personalized results

This happens automatically when `user_email` is present in the search context and `cf_boost_weight > 0`.

## Usage Examples

### Recording Tool Usage

```python
from mcpgateway.services.usage_analytics_service import usage_analytics_service

await usage_analytics_service.record_usage_event(
    user_email="alice@example.com",
    tool_id="calculator",
    execution_duration_ms=150,
    success=True,
    session_id="session-123",
    user_role="developer",
    user_team_id="team-456"
)
```

### Getting Recommendations

```python
from mcpgateway.services.collaborative_recommender import collaborative_recommender

recommendations = await collaborative_recommender.recommend_tools(
    user_email="alice@example.com",
    limit=10,
    include_reasoning=True
)

for rec in recommendations:
    print(f"Tool: {rec['tool_id']}, Score: {rec['score']:.3f}")
    if 'reasoning' in rec:
        similar_users = rec['reasoning']['top_similar_users']
        print(f"  Recommended because {similar_users[0]['email']} (similarity: {similar_users[0]['similarity']:.2f}) uses it")
```

### Computing User Similarity

```python
from mcpgateway.services.user_similarity_service import user_similarity_service

similarity = await user_similarity_service.compute_similarity(
    user1_email="alice@example.com",
    user2_email="bob@example.com",
    algorithm="cosine"
)

print(f"Similarity between Alice and Bob: {similarity:.3f}")
```

### API Usage

```bash
# Record tool usage
curl -X POST http://localhost:4444/api/v1/analytics/tool-usage \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tool_id": "calculator", "execution_duration_ms": 150, "success": true}'

# Get recommendations
curl http://localhost:4444/api/v1/recommendations/tools?limit=10&include_reasoning=true \
  -H "Authorization: Bearer $TOKEN"

# Export user data (GDPR)
curl http://localhost:4444/api/v1/users/me/usage-data \
  -H "Authorization: Bearer $TOKEN"

# Delete user data (right to erasure)
curl -X DELETE http://localhost:4444/api/v1/users/me/usage-data \
  -H "Authorization: Bearer $TOKEN"
```

## Testing

Comprehensive test suite in [tests/test_analytics_collaborative_filtering.py](tests/test_analytics_collaborative_filtering.py):

```bash
# Run analytics tests
pytest tests/test_analytics_collaborative_filtering.py -v

# Run with coverage
pytest tests/test_analytics_collaborative_filtering.py --cov=mcpgateway.services --cov-report=html
```

Test coverage includes:
- Usage event recording and buffering
- Opt-out enforcement
- Data export/delete (GDPR compliance)
- Similarity algorithms (cosine, Jaccard, Dice, overlap)
- Collaborative recommendations with reasoning
- Trending tools analysis
- API endpoint integration

## Architecture

### Service Lifecycle

All three services follow the standard initialization/shutdown pattern:

```python
# main.py lifespan manager
await usage_analytics_service.initialize()
await user_similarity_service.initialize()
await collaborative_recommender.initialize()

# Shutdown in reverse order with buffered event flush
await usage_analytics_service.shutdown()  # Flushes pending events
await user_similarity_service.shutdown()
await collaborative_recommender.shutdown()
```

### Caching Strategy

- **Redis L1 cache**: User opt-out status (60s TTL)
- **Redis L2 cache**: User tool usage vectors (3600s TTL)
- **Redis L3 cache**: Pairwise similarity scores (3600s TTL configurable)

Cache keys are normalized to ensure consistency:
- Opt-out: `analytics:opt_out:{user_email}`
- Tool usage: `user_tools:{user_email}`
- Similarity: `user_similarity:{algorithm}:{email1}:{email2}` (sorted)

### Performance Optimizations

1. **Batch event insertion**: Events are buffered and inserted in batches of 100 (configurable)
2. **Background cleanup**: Old events are deleted in batches to avoid long locks
3. **Precomputed similarities** (optional): Background task precomputes top 100 active users' pairwise similarities
4. **Indexed queries**: Composite indexes on (user_email, tool_id) and (user_team_id, tool_id)

## Privacy & Compliance

### GDPR Compliance

- **Right to be informed**: Users can view their analytics preferences via API
- **Right of access**: Full data export via `/api/v1/users/me/usage-data`
- **Right to erasure**: Data deletion via DELETE endpoint
- **Right to object**: Opt-out prevents future data collection
- **Data minimization**: Configurable retention periods (30-730 days)

### Privacy Controls

Users can manage their analytics preferences:

```python
# Opt out of analytics
await usage_analytics_service.set_user_preference(
    user_email="alice@example.com",
    analytics_opted_in=False
)

# Custom retention period
await usage_analytics_service.set_user_preference(
    user_email="alice@example.com",
    analytics_opted_in=True,
    data_retention_days=30  # Shorter than default 90 days
)
```

## Migration

Run the SQL migration to create the new tables:

```bash
# For MariaDB/MySQL
mysql -u root -p mcp < migrations/add_analytics_tables.sql

# For PostgreSQL (adjust SQL dialect if needed)
psql -U postgres mcp < migrations/add_analytics_tables.sql

# For SQLite (adjust SQL dialect if needed)
sqlite3 mcp.db < migrations/add_analytics_tables.sql
```

Note: The migration script is idempotent (uses `CREATE TABLE IF NOT EXISTS`).

## Troubleshooting

### No recommendations generated

- **Check user has sufficient interactions**: `CF_MIN_USER_INTERACTIONS=3` by default
- **Check similar users exist**: At least `CF_MIN_COMMON_TOOLS=2` tools in common
- **Check analytics enabled**: `ANALYTICS_ENABLED=true`

### Redis connection errors

- Services gracefully degrade to direct DB queries without Redis
- Check `REDIS_URL` and Redis server availability
- Cache-related warnings are non-fatal

### Performance issues

- Lower `SIMILARITY_PRECOMPUTE_ENABLED=true` to reduce on-demand computation
- Increase `SIMILARITY_CACHE_TTL` for longer caching
- Adjust `ANALYTICS_CLEANUP_BATCH_SIZE` for cleanup performance

## Future Enhancements

Potential improvements for future iterations:

1. **Item-based collaborative filtering**: Recommend similar tools (not just user-to-user)
2. **Hybrid recommendations**: Combine CF with content-based filtering
3. **Matrix factorization**: SVD/ALS for scalability with large user bases
4. **Real-time updating**: Stream processing for immediate recommendation updates
5. **A/B testing framework**: Compare recommendation algorithms
6. **Contextual bandits**: Explore/exploit tradeoff for new tools

## References

- **Collaborative Filtering**: [Wikipedia](https://en.wikipedia.org/wiki/Collaborative_filtering)
- **User-user CF**: Breese, J. S., Heckerman, D., & Kadie, C. (1998). Empirical analysis of predictive algorithms for collaborative filtering.
- **GDPR**: [Official Text](https://gdpr-info.eu/)
- **Jaccard similarity**: [Wikipedia](https://en.wikipedia.org/wiki/Jaccard_index)
- **Cosine similarity**: [Wikipedia](https://en.wikipedia.org/wiki/Cosine_similarity)
