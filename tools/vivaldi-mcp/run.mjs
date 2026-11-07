// Launch only a dedicated Vivaldi profile, then attach Chrome DevTools MCP over loopback CDP.
import { spawn } from 'node:child_process';
import { constants } from 'node:fs';
import { access, chmod, mkdir, readFile, readlink, unlink } from 'node:fs/promises';
import { homedir, hostname } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const directory = fileURLToPath(new URL('.', import.meta.url));
const cli = join(directory, 'node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js');
let browser;
let server;
let stopping = false;
function stop() {
  stopping = true;
  server?.kill('SIGTERM');
  browser?.kill('SIGTERM');
}
process.on('SIGTERM', stop);
process.on('SIGINT', stop);

try {
  await access(cli);
  let binary;
  const candidates = process.env.VIVALDI_BINARY ? [process.env.VIVALDI_BINARY] : [
    '/opt/vivaldi/vivaldi', '/usr/bin/vivaldi-stable', '/usr/bin/vivaldi',
    '/snap/bin/vivaldi.vivaldi-stable',
  ];
  for (const candidate of candidates) {
    try { await access(candidate, constants.X_OK); binary = candidate; break; } catch {}
  }
  if (!binary) throw new Error('Vivaldi not found; set VIVALDI_BINARY to its executable');
  const state = binary.startsWith('/snap/')
    ? join(homedir(), 'snap/vivaldi/common/dream1-piper-mcp')
    : join(process.env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'dream1-piper/vivaldi-mcp');
  const profile = join(state, 'profile');
  for (const path of [state, profile, join(state, 'output')]) {
    await mkdir(path, { recursive: true, mode: 0o700 });
    await chmod(path, 0o700);
  }
  const lock = await readlink(join(profile, 'SingletonLock')).catch(error => {
    if (error.code !== 'ENOENT') throw error;
    return '';
  });
  if (lock) {
    const match = lock.match(/^(.*)-(\d+)$/);
    if (!match || match[1] !== hostname()) throw new Error('MCP profile is locked by another host');
    let running = true;
    try { process.kill(Number(match[2]), 0); } catch (error) {
      if (error.code === 'ESRCH') running = false;
      else throw error;
    }
    if (running) throw new Error('The dedicated MCP profile is already open; close that window/session first');
    // Chromium itself recovers its stale singleton lock when that PID no longer exists.
  }
  const portFile = join(profile, 'DevToolsActivePort');
  await unlink(portFile).catch(error => { if (error.code !== 'ENOENT') throw error; });
  browser = spawn(binary, [
    `--user-data-dir=${profile}`, '--remote-debugging-address=127.0.0.1',
    '--remote-debugging-port=0', '--no-first-run', '--no-default-browser-check',
    'data:text/html,<title>Vivaldi MCP</title><p>Ready</p>',
  ], { stdio: ['ignore', 'ignore', 'inherit'] });
  const browserFailure = new Promise((_, reject) => {
    browser.once('error', reject);
    browser.once('exit', code => reject(new Error(`Dedicated Vivaldi exited (${code})`)));
  });
  const ready = async () => {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
      try {
        const port = Number((await readFile(portFile, 'utf8')).split('\n')[0]);
        if (!Number.isInteger(port) || port <= 0 || port > 65535) throw new Error('Invalid CDP port');
        const endpoint = `http://127.0.0.1:${port}`;
        const response = await fetch(`${endpoint}/json/version`, { signal: AbortSignal.timeout(1000) });
        if (response.ok && (await response.json()).webSocketDebuggerUrl) return endpoint;
      } catch {}
      await delay(100);
    }
    throw new Error('Vivaldi did not initialize its browser tabs within 30 seconds');
  };
  const endpoint = await Promise.race([ready(), browserFailure]);
  server = spawn(process.execPath, [cli, '--browserUrl', endpoint,
    '--no-usage-statistics', '--no-performance-crux', ...process.argv.slice(2),
  ], { stdio: 'inherit', env: { ...process.env, CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS: '1' } });
  const code = await Promise.race([
    new Promise((resolve, reject) => { server.once('exit', resolve); server.once('error', reject); }),
    browserFailure,
  ]);
  process.exitCode = code ?? 1;
} catch (error) {
  if (!stopping) {
    console.error(`Vivaldi MCP: ${error.message}`);
    process.exitCode = 1;
  }
} finally {
  stop();
}
