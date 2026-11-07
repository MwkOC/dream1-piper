// End-to-end MCP/browser check on a synthetic local page, without account access.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const child = spawn('bash', [fileURLToPath(new URL('run.sh', import.meta.url))], {
  stdio: ['pipe', 'pipe', 'inherit'],
});
const pending = new Map();
let nextId = 0;
const lines = createInterface({ input: child.stdout });
lines.on('line', line => {
  const message = JSON.parse(line);
  if (message.id != null && pending.has(message.id)) {
    const callback = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) callback.reject(new Error(JSON.stringify(message.error)));
    else callback.resolve(message.result);
  }
});
child.on('exit', code => {
  for (const callback of pending.values()) callback.reject(new Error(`MCP exited: ${code}`));
  pending.clear();
});

function request(method, params) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`MCP timeout: ${method}`));
    }, 45000);
    pending.set(id, {
      resolve: value => { clearTimeout(timer); resolve(value); },
      reject: error => { clearTimeout(timer); reject(error); },
    });
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n');
  });
}

async function call(name, args = {}) {
  const result = await request('tools/call', { name, arguments: args });
  const text = result.content?.filter(item => item.type === 'text').map(item => item.text).join('\n') ?? '';
  assert(!result.isError, text);
  return text;
}

try {
  const init = await request('initialize', {
    protocolVersion: '2024-11-05', capabilities: {},
    clientInfo: { name: 'vivaldi-mcp-smoke', version: '0.1.0' },
  });
  assert(init.serverInfo);
  child.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
  const list = await request('tools/list', {});
  assert(list.tools.some(tool => tool.name === 'new_page'));
  const html = '<title>Vivaldi MCP test</title><label>Name<input id="name"></label><button onclick="document.getElementById(\'result\').textContent=\'OK \'+document.getElementById(\'name\').value">Check</button><p id="result"></p>';
  const created = await call('new_page', { url: `data:text/html,${encodeURIComponent(html)}` });
  const pageId = Number(created.match(/^(\d+):.*\[selected\]/m)?.[1]);
  assert(Number.isInteger(pageId), created);
  const snapshot = await call('take_snapshot', { pageId });
  assert(snapshot.includes('Vivaldi MCP test'));
  const input = snapshot.match(/uid=([^\s]+) textbox/)?.[1];
  const button = snapshot.match(/uid=([^\s]+) button "Check"/)?.[1];
  assert(input && button, snapshot);
  await call('click', { pageId, uid: input });
  await call('type_text', { pageId, text: 'Piper' });
  const filled = await call('take_snapshot', { pageId });
  assert(filled.includes('Piper'), filled);
  await call('click', { pageId, uid: button });
  const result = await call('take_snapshot', { pageId });
  assert(result.includes('OK Piper'), result);
  console.log(`PASS: ${init.serverInfo.name}; ${list.tools.length} tools; real Vivaldi navigation, typing and click`);
} finally {
  // Closing the server closes only the separate MCP browser, not the user's Vivaldi.
  child.stdin.end();
  child.kill('SIGTERM');
  lines.close();
}
