import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';

export function tauriBuildArgs({ debug = false, signingIdentity = process.env.APPLE_SIGNING_IDENTITY ?? '-' } = {}) {
  // Tauri signs the app before it creates the DMG. Re-signing the app after
  // `tauri build` would leave the DMG with a stale, differently signed copy.
  const signingConfig = JSON.stringify({ bundle: { macOS: { signingIdentity } } });
  return [
    'tauri',
    'build',
    ...(debug ? ['--debug'] : []),
    '--bundles',
    'app,dmg',
    '--config',
    signingConfig,
    '--ci',
    '--',
    '--locked',
  ];
}

export function buildMacos({ debug = false, signingIdentity } = {}) {
  if (process.platform !== 'darwin') throw new Error('macOS build requires a Mac');

  execFileSync('npx', tauriBuildArgs({ debug, signingIdentity }), { stdio: 'inherit' });

  const profile = debug ? 'debug' : 'release';
  const app = resolve(`target/${profile}/bundle/macos/Wondershot.app`);
  const dmgDirectory = resolve(`target/${profile}/bundle/dmg`);
  if (!existsSync(app)) throw new Error(`Missing app: ${app}`);
  if (!existsSync(dmgDirectory) || !readdirSync(dmgDirectory).some((entry) => entry.endsWith('.dmg'))) {
    throw new Error(`Missing DMG under: ${dmgDirectory}`);
  }

  execFileSync('codesign', ['--verify', '--strict', '--deep', app], { stdio: 'inherit' });
  console.log(`Verified signed macOS app and DMG: ${app}`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  buildMacos({ debug: process.argv.includes('--debug') });
}
