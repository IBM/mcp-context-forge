import http from 'k6/http';
import { check, fail } from 'k6';

const endpoint = __ENV.CF_MCP_ENDPOINT;
const toolName = __ENV.CF_TOOL_NAME;
const token = __ENV.CF_TEST_TOKEN;
const protocolVersion = '2025-11-25';

if (!endpoint || !toolName || !token) {
  throw new Error('CF_MCP_ENDPOINT, CF_TOOL_NAME, and CF_TEST_TOKEN are required');
}

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    checks: ['rate==1'],
    http_req_failed: ['rate==0'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(95)', 'p(99)'],
};

function responseHeader(response, name) {
  const key = Object.keys(response.headers).find(
    (candidate) => candidate.toLowerCase() === name.toLowerCase(),
  );
  return key ? response.headers[key] : '';
}

function parseResult(response, id) {
  if (response.status !== 200) return null;

  try {
    const messages = String(responseHeader(response, 'Content-Type')).includes('text/event-stream')
      ? String(response.body)
        .replace(/\r\n/g, '\n')
        .split('\n\n')
        .map((event) => event
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).replace(/^ /, ''))
          .join('\n'))
        .filter((data) => data.trim())
        .map((data) => JSON.parse(data))
      : [response.json()];
    const message = messages.find((value) => value && value.id === id);
    return message && message.jsonrpc === '2.0' && !message.error
      ? message.result
      : null;
  } catch (_) {
    return null;
  }
}

export default function () {
  let requestId = 0;
  let sessionId = '';

  function requestParams(name) {
    return {
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json, text/event-stream',
        'MCP-Protocol-Version': protocolVersion,
        Authorization: `Bearer ${token}`,
        ...(sessionId ? { 'Mcp-Session-Id': sessionId } : {}),
      },
      timeout: '5s',
      redirects: 0,
      tags: { name },
    };
  }

  function rpc(method, params) {
    requestId += 1;
    const response = http.post(
      endpoint,
      JSON.stringify({ jsonrpc: '2.0', id: requestId, method, params }),
      requestParams(method),
    );
    if (method === 'initialize') {
      sessionId = responseHeader(response, 'Mcp-Session-Id');
    }
    return { response, result: parseResult(response, requestId) };
  }

  try {
    const initialization = rpc('initialize', {
      protocolVersion,
      capabilities: { tools: {} },
      clientInfo: { name: 'k6-contextforge-single-lifecycle', version: '1.0' },
    });
    if (!check(initialization, {
      'MCP initialized': (value) => value.result?.protocolVersion === protocolVersion,
    })) {
      fail('MCP initialization failed');
    }

    const notification = http.post(
      endpoint,
      JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }),
      requestParams('notifications/initialized'),
    );
    if (!check(notification, {
      'initialized accepted': (response) => response.status === 202,
    })) {
      fail('Initialized notification failed');
    }

    const tools = rpc('tools/list', {});
    if (!check(tools, {
      'tool is listed': (value) => Array.isArray(value.result?.tools)
        && value.result.tools.some((tool) => tool.name === toolName),
    })) {
      fail('Tool discovery failed');
    }

    const invocation = rpc('tools/call', {
      name: toolName,
      arguments: { timezone: 'UTC' },
    });
    if (!check(invocation, {
      'tool call succeeded': (value) => value.result?.isError !== true
        && Array.isArray(value.result?.content)
        && value.result.content.some(
          (part) => part.type === 'text' && Number.isFinite(Date.parse(part.text)),
        ),
    })) {
      fail('Tool invocation failed');
    }
  } finally {
    if (sessionId) {
      const response = http.del(endpoint, null, requestParams('session/delete'));
      check(response, {
        'session closed': (value) => [200, 202, 204].includes(value.status),
      });
    }
  }
}
