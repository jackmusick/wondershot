import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

if (process.platform !== 'darwin') throw new Error('macOS build requires a Mac');
const debug = process.argv.includes('--debug');
const signingConfig = process.env.APPLE_SIGNING_IDENTITY
  ? ['--config', JSON.stringify({ bundle: { macOS: { signingIdentity: process.env.APPLE_SIGNING_IDENTITY } } })] : [];
execFileSync('npx', ['tauri', 'build', ...(debug ? ['--debug'] : []), '--bundles', 'app', ...signingConfig], { stdio: 'inherit' });
const app = resolve(`target/${debug ? 'debug' : 'release'}/bundle/macos/Wondershot.app`);
if (!existsSync(app)) throw new Error(`Missing app: ${app}`);
// For local development, bind the whole bundle to a stable designated
// requirement. Linker-only signatures identify each rebuild by its code hash.
// Production distributions should set APPLE_SIGNING_IDENTITY to Developer ID.
if (!process.env.APPLE_SIGNING_IDENTITY) {
  execFileSync('codesign', ['--force', '--sign', '-', '--identifier', 'io.github.jackmusick.wondershot', '--requirements', '=designated => identifier "io.github.jackmusick.wondershot"', app], { stdio: 'inherit' });
}
execFileSync('codesign', ['--verify', '--strict', app], { stdio: 'inherit' });
console.log(`Verified macOS app: ${app}`);
