import http from 'k6/http';
import { check, sleep } from 'k6';
import execution from 'k6/execution';
import { Counter, Rate, Trend } from 'k6/metrics';

const endpoint = __ENV.CF_MCP_ENDPOINT;
const toolName = __ENV.CF_TOOL_NAME;
const token = __ENV.CF_TEST_TOKEN;
const users = Number(__ENV.BENCH_USERS || '10');
const duration = Number(__ENV.BENCH_SECONDS || '60');
const spawnRate = Number(__ENV.BENCH_SPAWN_RATE || '5');
const rampMs = Math.ceil(users / spawnRate * 1000);
const protocolVersion = '2025-11-25';

if (!endpoint || !toolName || !token) {
  throw new Error('CF_MCP_ENDPOINT, CF_TOOL_NAME, and CF_TEST_TOKEN are required');
}
if (
  !Number.isInteger(users) || users < 1 || users > 125
  || !Number.isFinite(duration) || duration < 2 || duration > 60
  || !Number.isFinite(spawnRate) || spawnRate <= 0
  || rampMs >= duration * 1000
) {
  throw new Error('Invalid or excessive benchmark settings');
}
const timezones = [
  'UTC',
  'America/New_York',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Paris',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Australia/Sydney',
  'America/Chicago',
  'Europe/Dublin',
  'Europe/Berlin',
  'Asia/Singapore',
];

const workloadRequests = new Counter('workload_requests');
const workloadFailed = new Rate('workload_failed');
const toolCalls = new Counter('tool_calls');
const toolSuccesses = new Counter('tool_successes');
const toolFailed = new Rate('tool_failed');
const toolLatency = new Trend('tool_latency_ms', true);
const clientsInitialized = new Counter('clients_initialized');

export const options = {
  scenarios: {
    tools: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: `${rampMs}ms`, target: users },
        { duration: `${duration * 1000 - rampMs}ms`, target: users },
      ],
      gracefulStop: '12s',
    },
  },
  thresholds: {
    checks: ['rate==1'],
    workload_requests: ['count>0'],
    tool_calls: ['count>0'],
    workload_failed: [{ threshold: 'rate==0', abortOnFail: true, delayAbortEval: '5s' }],
    http_req_failed: [{ threshold: 'rate==0', abortOnFail: true, delayAbortEval: '5s' }],
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
  const deadline = execution.scenario.startTime + duration * 1000;
  if (Date.now() >= deadline) {
    sleep(0.1);
    return;
  }

  let sessionId = '';
  let requestId = 0;

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
      clientInfo: { name: 'k6-contextforge-smoke', version: '1.0' },
    });
    if (!check(initialization, {
      'MCP initialized': (result) => result.result?.protocolVersion === protocolVersion,
    })) {
      execution.test.abort('MCP initialization failed');
      return;
    }
    clientsInitialized.add(1);

    const notification = http.post(
      endpoint,
      JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }),
      requestParams('notifications/initialized'),
    );
    if (!check(notification, {
      'initialized accepted': (response) => response.status === 202,
    })) {
      execution.test.abort('Initialized notification failed');
      return;
    }

    while (Date.now() < deadline) {
      const callTool = Math.random() < 20 / 21;
      const method = callTool ? 'tools/call' : 'tools/list';
      const params = callTool
        ? {
          name: toolName,
          arguments: {
            timezone: timezones[Math.floor(Math.random() * timezones.length)],
          },
        }
        : {};
      const { response, result } = rpc(method, params);
      const valid = Boolean(result) && (callTool
        ? result.isError !== true
          && Array.isArray(result.content)
          && result.content.some(
            (part) => part.type === 'text' && Number.isFinite(Date.parse(part.text)),
          )
        : Array.isArray(result.tools)
          && result.tools.some((tool) => tool.name === toolName));

      workloadRequests.add(1);
      workloadFailed.add(!valid);
      check(valid, { 'workload MCP result valid': (value) => value });

      if (callTool) {
        toolCalls.add(1);
        toolFailed.add(!valid);
        toolLatency.add(response.timings.duration);
        toolSuccesses.add(valid ? 1 : 0);
      }

      sleep(0.02 + Math.random() * 0.08);
    }
  } finally {
    if (sessionId) {
      const response = http.del(endpoint, null, requestParams('session/delete'));
      check([200, 202, 204].includes(response.status), {
        'session closed': (closed) => closed,
      });
    }
  }
}

export function handleSummary(data) {
  const metric = (name) => data.metrics[name]?.values || {};
  const result = {
    users,
    spawn_rate: spawnRate,
    ramp_ms: rampMs,
    workload_seconds: duration,
    tool_name: toolName,
    tool_calls: metric('tool_calls').count || 0,
    successful_tool_calls: metric('tool_successes').count || 0,
    tool_rps_over_configured_window: (metric('tool_calls').count || 0) / duration,
    workload_requests: metric('workload_requests').count || 0,
    workload_rps_over_configured_window:
      (metric('workload_requests').count || 0) / duration,
    workload_failed: metric('workload_failed'),
    tool_failed: metric('tool_failed'),
    tool_latency_ms: metric('tool_latency_ms'),
    http_req_failed: metric('http_req_failed'),
    clients_initialized: metric('clients_initialized').count || 0,
    actual_test_duration_ms: data.state.testRunDurationMs,
    checks: metric('checks'),
    thresholds: Object.fromEntries(
      Object.entries(data.metrics)
        .filter(([, value]) => value.thresholds)
        .map(([name, value]) => [name, value.thresholds]),
    ),
  };

  return { stdout: `BENCHMARK_RESULT\n${JSON.stringify(result, null, 2)}\n` };
}
