-- OAuth Token Vault Path Lookup Queries
-- Use these to find team_id and server_id for Vault token retrieval

-- 1. Find all gateways with OAuth configuration
SELECT
    id as gateway_id,
    name,
    url as gateway_url,
    team_id,
    owner_email
FROM gateways
WHERE oauth_config IS NOT NULL
ORDER BY name;

-- 2. Find user's team memberships
SELECT
    user_email,
    team_id,
    is_active,
    created_at
FROM email_team_members
WHERE user_email = 'user@example.com'  -- Replace with your email
  AND is_active = true
ORDER BY created_at;

-- 3. Get first team for a user (what the system uses)
SELECT team_id
FROM email_team_members
WHERE user_email = 'user@example.com'  -- Replace with your email
  AND is_active = true
ORDER BY team_id
LIMIT 1;

-- 4. Find gateway URL by gateway name
SELECT url
FROM gateways
WHERE name = 'git-mcp-server';  -- Replace with your gateway name

-- 5. Complete info for Vault path construction
SELECT
    g.id as gateway_id,
    g.name as gateway_name,
    g.url as gateway_url,
    etm.user_email,
    etm.team_id,
    eu.is_admin
FROM gateways g
CROSS JOIN email_team_members etm
LEFT JOIN email_users eu ON eu.email = etm.user_email
WHERE g.oauth_config IS NOT NULL
  AND etm.is_active = true
  AND etm.user_email = 'user@example.com'  -- Replace with your email
  AND g.name = 'git-mcp-server'  -- Replace with your gateway name
ORDER BY etm.team_id
LIMIT 1;

-- 6. Check if tokens exist in database backend (if using database backend)
SELECT
    gateway_id,
    app_user_email,
    user_id,
    scopes,
    expires_at,
    created_at
FROM oauth_tokens
WHERE app_user_email = 'user@example.com'  -- Replace with your email
ORDER BY created_at DESC;

-- 7. List all users and their teams
SELECT
    eu.email,
    eu.is_admin,
    string_agg(etm.team_id, ', ') as teams
FROM email_users eu
LEFT JOIN email_team_members etm ON eu.email = etm.user_email AND etm.is_active = true
GROUP BY eu.email, eu.is_admin
ORDER BY eu.email;

-- 8. Check gateway OAuth configuration
SELECT
    id,
    name,
    url,
    auth_type,
    oauth_config::text  -- Shows OAuth config JSON
FROM gateways
WHERE name = 'git-mcp-server';  -- Replace with your gateway name
