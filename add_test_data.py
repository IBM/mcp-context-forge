#!/usr/bin/env python3
"""
Script to add comprehensive test data to MCP Gateway SQLite database.
This script populates all relevant tables with sample data for testing metrics functionality.
"""

import sqlite3
import uuid
from datetime import datetime, timedelta
import json
import random

# Database file path
DB_PATH = "mcp.db"

def generate_uuid():
    """Generate a UUID hex string."""
    return uuid.uuid4().hex

def utc_now():
    """Get current UTC timestamp."""
    return datetime.utcnow()

def random_timestamp(days_back=30):
    """Generate a random timestamp within the last N days."""
    now = utc_now()
    random_days = random.uniform(0, days_back)
    return now - timedelta(days=random_days)

def add_test_data():
    """Add comprehensive test data to the database."""
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print("Adding test data to MCP Gateway database...")

    # Clear existing data for a fresh start
    tables = [
        'server_tool_association', 'server_resource_association', 'server_prompt_association', 'server_a2a_association',
        'tool_metrics', 'resource_metrics', 'server_metrics', 'prompt_metrics', 'a2a_agent_metrics',
        'tools', 'resources', 'prompts', 'servers', 'a2a_agents', 'gateways'
    ]
    for table in tables:
        cursor.execute(f"DELETE FROM {table}")
    conn.commit()
    
    # 1. Add Gateways
    print("Adding gateways...")
    gateways = []
    for i in range(5):
        gateways.append({
            'id': generate_uuid(),
            'name': f'Gateway {i+1}',
            'slug': f'gateway-{i+1}',
            'url': f'http://localhost:800{i}',
            'description': f'Sample gateway {i+1}',
            'transport': 'SSE' if i % 2 == 0 else 'REST',
            'capabilities': json.dumps({'tools': {'list_changed': True}, 'resources': {'subscribe': True}}),
            'enabled': True,
            'reachable': True,
            'created_at': utc_now(),
            'updated_at': utc_now(),
            'tags': json.dumps([f'sample{i+1}']),
            'version': 1
        })
    
    for gateway in gateways:
        cursor.execute("""
            INSERT INTO gateways (id, name, slug, url, description, transport, capabilities, 
                                enabled, reachable, created_at, updated_at, tags, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            gateway['id'], gateway['name'], gateway['slug'], gateway['url'],
            gateway['description'], gateway['transport'], gateway['capabilities'],
            gateway['enabled'], gateway['reachable'], gateway['created_at'],
            gateway['updated_at'], gateway['tags'], gateway['version']
        ))
    
    # 2. Add Tools
    print("Adding tools...")
    tools = []
    for i in range(5):
        tools.append({
            'id': generate_uuid(),
            'original_name': f'tool_{i+1}',
            'custom_name': f'Sample Tool {i+1}',
            'custom_name_slug': f'sample-tool-{i+1}',
            'name': f'sample-tool-{i+1}',
            'url': f'http://localhost:300{i+1}/tool_{i+1}',
            'description': f'Sample tool {i+1} for testing',
            'integration_type': 'MCP' if i % 2 == 0 else 'REST',
            'request_type': 'SSE' if i % 2 == 0 else 'POST',
            'headers': json.dumps({'Content-Type': 'application/json'}),
            'input_schema': json.dumps({
                'type': 'object',
                'properties': {
                    'param': {'type': 'string', 'description': f'Parameter for tool {i+1}'}
                },
                'required': ['param']
            }),
            'annotations': json.dumps({'category': f'cat{i+1}', 'danger': 'low'}),
            'enabled': True,
            'reachable': True,
            'created_at': utc_now(),
            'updated_at': utc_now(),
            'tags': json.dumps([f'tag{i+1}']),
            'jsonpath_filter': '',
            'version': 1,
            'gateway_id': gateways[i % 5]['id']
        })
    
    for tool in tools:
        cursor.execute("""
            INSERT INTO tools (id, original_name, custom_name, custom_name_slug, name, url, description,
                             integration_type, request_type, headers, input_schema, annotations,
                             enabled, reachable, created_at, updated_at, tags, gateway_id, jsonpath_filter, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tool['id'], tool['original_name'], tool['custom_name'], tool['custom_name_slug'],
            tool['name'], tool['url'], tool['description'], tool['integration_type'],
            tool['request_type'], tool['headers'], tool['input_schema'], tool['annotations'],
            tool['enabled'], tool['reachable'], tool['created_at'], tool['updated_at'],
            tool['tags'], tool.get('gateway_id'), tool['jsonpath_filter'], tool['version']
        ))
    
    # 3. Add Resources
    print("Adding resources...")
    resources = []
    for i in range(5):
        resources.append({
            'id': i+1,
            'uri': f'file:///resource_{i+1}.dat',
            'name': f'Resource {i+1}',
            'description': f'Sample resource {i+1}',
            'mime_type': 'application/octet-stream',
            'size': 1000 + i * 100,
            'text_content': f'Sample content for resource {i+1}',
            'is_active': True,
            'created_at': utc_now(),
            'updated_at': utc_now(),
            'tags': json.dumps([f'resource{i+1}']),
            'version': 1,
            'gateway_id': gateways[i % 5]['id']
        })
    
    for resource in resources:
        cursor.execute("""
            INSERT INTO resources (id, uri, name, description, mime_type, size, text_content,
                                 is_active, created_at, updated_at, tags, gateway_id, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            resource['id'], resource['uri'], resource['name'], resource['description'],
            resource['mime_type'], resource['size'], resource['text_content'],
            resource['is_active'], resource['created_at'], resource['updated_at'],
            resource['tags'], resource.get('gateway_id'), resource['version']
        ))
    
    # 4. Add Prompts
    print("Adding prompts...")
    prompts = []
    for i in range(5):
        prompts.append({
            'id': i+1,
            'name': f'prompt_{i+1}',
            'description': f'Sample prompt {i+1}',
            'template': f'Prompt template {i+1} with variable {{var{i+1}}}',
            'argument_schema': json.dumps({
                'type': 'object',
                'properties': {
                    f'var{i+1}': {'type': 'string', 'description': f'Variable {i+1}'}
                },
                'required': [f'var{i+1}']
            }),
            'is_active': True,
            'created_at': utc_now(),
            'updated_at': utc_now(),
            'tags': json.dumps([f'prompt{i+1}']),
            'version': 1,
            'gateway_id': gateways[i % 5]['id']
        })
    
    for prompt in prompts:
        cursor.execute("""
            INSERT INTO prompts (id, name, description, template, argument_schema, is_active,
                               created_at, updated_at, tags, gateway_id, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            prompt['id'], prompt['name'], prompt['description'], prompt['template'],
            prompt['argument_schema'], prompt['is_active'], prompt['created_at'],
            prompt['updated_at'], prompt['tags'], prompt.get('gateway_id'), prompt['version']
        ))
    
    # 5. Add Servers
    print("Adding servers...")
    servers = []
    for i in range(5):
        servers.append({
            'id': generate_uuid(),
            'name': f'Server {i+1}',
            'description': f'Sample server {i+1}',
            'icon': f'icon_{i+1}',
            'is_active': True,
            'created_at': utc_now(),
            'updated_at': utc_now(),
            'tags': json.dumps([f'server{i+1}']),
            'version': 1
        })
    
    for server in servers:
        cursor.execute("""
            INSERT INTO servers (id, name, description, icon, is_active, created_at, updated_at, tags, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            server['id'], server['name'], server['description'], server['icon'],
            server['is_active'], server['created_at'], server['updated_at'], server['tags'], server['version']
        ))
    
    # 6. Add A2A Agents
    print("Adding A2A agents...")
    a2a_agents = []
    for i in range(5):
        a2a_agents.append({
            'id': generate_uuid(),
            'name': f'A2A Agent {i+1}',
            'slug': f'a2a-agent-{i+1}',
            'description': f'Sample A2A agent {i+1}',
            'endpoint_url': f'https://api.agent{i+1}.com/v1',
            'agent_type': 'custom',
            'protocol_version': '1.0',
            'capabilities': json.dumps({'feature': f'capability_{i+1}'}),
            'config': json.dumps({'setting': f'value_{i+1}'}),
            'auth_type': 'api_key',
            'enabled': True,
            'reachable': True,
            'created_at': utc_now(),
            'updated_at': utc_now(),
            'tags': json.dumps([f'a2a{i+1}']),
            'version': 1
        })
    
    for agent in a2a_agents:
        cursor.execute("""
            INSERT INTO a2a_agents (id, name, slug, description, endpoint_url, agent_type,
                                  protocol_version, capabilities, config, auth_type, enabled,
                                  reachable, created_at, updated_at, tags, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent['id'], agent['name'], agent['slug'], agent['description'],
            agent['endpoint_url'], agent['agent_type'], agent['protocol_version'],
            agent['capabilities'], agent['config'], agent['auth_type'],
            agent['enabled'], agent['reachable'], agent['created_at'],
            agent['updated_at'], agent['tags'], agent['version']
        ))
    
    # 7. Add Metrics for Tools (5 metrics per tool, random success/failure)
    print("Adding tool metrics...")
    for tool in tools:
        for i in range(5):
            is_success = random.choice([True, True, False])
            response_time = random.uniform(0.1, 2.5)
            error_msg = None if is_success else f"Tool error {i+1}"
            cursor.execute("""
                INSERT INTO tool_metrics (tool_id, timestamp, response_time, is_success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (tool['id'], random_timestamp(), response_time, is_success, error_msg))
    
    # 8. Add Resource Metrics (5 metrics per resource)
    print("Adding resource metrics...")
    for resource in resources:
        for i in range(5):
            is_success = random.choice([True, True, False])
            response_time = random.uniform(0.05, 1.0)
            error_msg = None if is_success else f"Resource error {i+1}"
            cursor.execute("""
                INSERT INTO resource_metrics (resource_id, timestamp, response_time, is_success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (resource['id'], random_timestamp(), response_time, is_success, error_msg))
    
    # 9. Add Server Metrics (5 metrics per server)
    print("Adding server metrics...")
    for server in servers:
        for i in range(5):
            is_success = random.choice([True, True, False])
            response_time = random.uniform(0.1, 3.0)
            error_msg = None if is_success else f"Server error {i+1}"
            cursor.execute("""
                INSERT INTO server_metrics (server_id, timestamp, response_time, is_success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (server['id'], random_timestamp(), response_time, is_success, error_msg))
    
    # 10. Add Prompt Metrics (5 metrics per prompt)
    print("Adding prompt metrics...")
    for prompt in prompts:
        for i in range(5):
            is_success = random.choice([True, True, False])
            response_time = random.uniform(0.2, 4.0)
            error_msg = None if is_success else f"Prompt error {i+1}"
            cursor.execute("""
                INSERT INTO prompt_metrics (prompt_id, timestamp, response_time, is_success, error_message)
                VALUES (?, ?, ?, ?, ?)
            """, (prompt['id'], random_timestamp(), response_time, is_success, error_msg))
    
    # 11. Add A2A Agent Metrics (5 metrics per agent)
    print("Adding A2A agent metrics...")
    for agent in a2a_agents:
        for i in range(5):
            is_success = random.choice([True, True, False])
            response_time = random.uniform(0.5, 8.0)
            interaction_type = random.choice(['invoke', 'query', 'stream'])
            error_msg = None if is_success else f"A2A error {i+1}"
            cursor.execute("""
                INSERT INTO a2a_agent_metrics (a2a_agent_id, timestamp, response_time, is_success,
                                             error_message, interaction_type)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (agent['id'], random_timestamp(), response_time, is_success, error_msg, interaction_type))
    
    # 12. Add some association data (many-to-many relationships)
    print("Adding server associations...")
    # Associate each tool, resource, prompt, and a2a agent with each server
    for i in range(5):
        cursor.execute("""
            INSERT INTO server_tool_association (server_id, tool_id)
            VALUES (?, ?)
        """, (servers[i]['id'], tools[i]['id']))
        cursor.execute("""
            INSERT INTO server_resource_association (server_id, resource_id)
            VALUES (?, ?)
        """, (servers[i]['id'], resources[i]['id']))
        cursor.execute("""
            INSERT INTO server_prompt_association (server_id, prompt_id)
            VALUES (?, ?)
        """, (servers[i]['id'], prompts[i]['id']))
        cursor.execute("""
            INSERT INTO server_a2a_association (server_id, a2a_agent_id)
            VALUES (?, ?)
        """, (servers[i]['id'], a2a_agents[i]['id']))
    
    # Commit all changes
    conn.commit()
    conn.close()
    
    print("\n✅ Test data successfully added to the database!")
    print("\nSummary of added data:")
    print(f"- {len(gateways)} gateways")
    print(f"- {len(tools)} tools with varying success rates")
    print(f"- {len(resources)} resources")
    print(f"- {len(prompts)} prompts")
    print(f"- {len(servers)} servers")
    print(f"- {len(a2a_agents)} A2A agents")
    print("- Comprehensive metrics for all entities")
    print("- Server association relationships")
    print("\nYou can now test the metrics functionality with this data!")

if __name__ == "__main__":
    add_test_data()
