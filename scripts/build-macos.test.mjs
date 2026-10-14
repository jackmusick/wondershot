import assert from 'node:assert/strict';
import test from 'node:test';

import { tauriBuildArgs } from './build-macos.mjs';

test('builds a signed app and DMG in one Tauri invocation', () => {
  const args = tauriBuildArgs({ signingIdentity: 'Developer ID Application: Example' });

  assert.deepEqual(args.slice(0, 5), ['tauri', 'build', '--bundles', 'app,dmg', '--config']);
  assert.match(args.at(args.indexOf('--config') + 1), /Developer ID Application: Example/);
});

test('uses Tauri ad-hoc signing for local builds', () => {
  const args = tauriBuildArgs();

  assert.deepEqual(args.slice(0, 5), ['tauri', 'build', '--bundles', 'app,dmg', '--config']);
  assert.match(args.at(args.indexOf('--config') + 1), /"signingIdentity":"-"/);
});

test('uses non-interactive Tauri builds for CI and local scripting', () => {
  const args = tauriBuildArgs();

  assert.ok(args.includes('--ci'));
  assert.deepEqual(args.slice(-2), ['--', '--locked']);
});
