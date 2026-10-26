import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { inflateSync } from 'node:zlib';
import { describe, expect, test } from 'vitest';

describe('macOS icon generator', () => {
  test('gives Windows taskbar and DPI frames their own tight safe area', () => {
    const dir = mkdtempSync(join(tmpdir(), 'wondershot-windows-icon-'));
    try {
      const icoPath = join(dir, 'icon.ico');
      const pngPath = join(dir, 'icon.png');
      execFileSync('node', [
        'scripts/generate-macos-icon.mjs', '--png', pngPath,
        '--no-icns', '--windows-ico', icoPath
      ]);
      const ico = readFileSync(icoPath);
      const sizes = [256, 128, 96, 64, 48, 40, 32, 24, 20, 16];
      expect(ico.readUInt16LE(2)).toBe(1);
      expect(ico.readUInt16LE(4)).toBe(sizes.length);
      // Tauri uses the first directory entry for the running window icon.
      expect(readPng(ico.subarray(ico.readUInt32LE(18), ico.readUInt32LE(18) + ico.readUInt32LE(14)))).toMatchObject({ width: 256, height: 256 });
      for (const [index, size] of sizes.entries()) {
        const entry = 6 + index * 16;
        expect(ico[entry] || 256).toBe(size);
        expect(ico[entry + 1] || 256).toBe(size);
        const length = ico.readUInt32LE(entry + 8);
        const offset = ico.readUInt32LE(entry + 12);
        const frame = ico.subarray(offset, offset + length);
        const bounds = measureAlphaBounds(frame);
        expect(bounds.width).toBe(size);
        expect(bounds.height).toBe(size);
        expect(bounds.contentWidth).toBeGreaterThanOrEqual(size - 2 * Math.max(1, Math.round(size / 64)));
        expect(bounds.contentHeight).toBeGreaterThanOrEqual(size * 0.8);
        expect(bounds.minX).toBeGreaterThanOrEqual(1);
        expect(bounds.minY).toBeGreaterThanOrEqual(1);
        expect(Math.abs(bounds.centerX - (size - 1) / 2)).toBeLessThanOrEqual(0.5);
        expect(Math.abs(bounds.centerY - (size - 1) / 2)).toBeLessThanOrEqual(0.5);
      }
      // macOS/Linux keep their existing source even when generating the ICO.
      expect(measureAlphaBounds(pngPath).contentWidth).toBe(824);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test('builds a 1024 template source with deterministic safe-area bounds', () => {
    const out = join(tmpdir(), `wondershot-macos-icon-${Date.now()}.png`);
    execFileSync('node', [
      'scripts/generate-macos-icon.mjs',
      '--source',
      'assets/branding/wondershot-icon-master.png',
      '--png',
      out,
      '--no-icns'
    ]);

    const measured = measureAlphaBounds(out);

    expect(measured.width).toBe(1024);
    expect(measured.height).toBe(1024);
    expect(measured.contentWidth).toBe(824);
    expect(measured.contentHeight).toBeLessThanOrEqual(824);
    expect(measured.contentHeight).toBeGreaterThan(790);
    expect(measured.minX).toBe(100);
    expect(Math.abs(measured.centerY - 512)).toBeLessThanOrEqual(1);
  });

  test('preserves the teal brackets on the dark tile without a spectrum rim', () => {
    const out = join(tmpdir(), `wondershot-plain-rim-${Date.now()}.png`);
    execFileSync('node', ['scripts/generate-macos-icon.mjs', '--png', out, '--no-icns']);
    const teal = measurePixelBounds(out, (r, g, b, a) => a > 128 && r < 120 && g > 180 && b > 180);
    const red = measurePixelBounds(out, (r, g, b, a) => a > 128 && r > 180 && g < 120 && b < 120);
    const green = measurePixelBounds(out, (r, g, b, a) => a > 128 && g > 180 && r < 120 && b < 120);
    const magenta = measurePixelBounds(out, (r, g, b, a) => a > 128 && r > 180 && b > 180 && g < 120);
    expect(teal.contentHeight).toBeGreaterThan(400);
    for (const color of [red, green, magenta]) expect(color.contentHeight).toBeLessThanOrEqual(0);
  });

  test('builds tightly cropped tray icons: a monochrome macOS template and a color tile', () => {
    const dir = join(tmpdir(), `wondershot-tray-${Date.now()}`);
    execFileSync('node', [
      'scripts/generate-macos-icon.mjs',
      '--png',
      join(dir, 'icon.png'),
      '--no-icns',
      '--tray-dir',
      dir
    ]);

    const template = join(dir, 'tray-template.png');
    const glyph = measureAlphaBounds(template);
    expect(glyph.width).toBe(64);
    expect(glyph.contentWidth).toBeGreaterThanOrEqual(62);
    expect(glyph.contentHeight).toBeGreaterThanOrEqual(62);
    const colored = measurePixelBounds(template, (r, g, b, a) => a > 8 && (r > 0 || g > 0 || b > 0));
    expect(colored.contentWidth).toBeLessThanOrEqual(0);
    // The spark sits in an empty middle ring, not on a filled tile.
    const ring = measurePixelBounds(template, (_r, _g, _b, a) => a > 64);
    expect(ring.contentWidth).toBeGreaterThan(0);
    expect(readPng(template).rgba[(32 * 64 + 12) * 4 + 3]).toBe(0);

    const tile = measureAlphaBounds(join(dir, 'tray.png'));
    expect(tile.width).toBe(64);
    expect(tile.contentWidth).toBeGreaterThanOrEqual(62);
    expect(measurePixelBounds(join(dir, 'tray.png'), (r, g, b, a) => a > 128 && r < 120 && g > 180 && b > 180).contentWidth).toBeGreaterThan(30);
  });

  test('centers the foreground artwork inside the macOS template', () => {
    const out = join(tmpdir(), `wondershot-macos-icon-centered-${Date.now()}.png`);
    execFileSync('node', [
      'scripts/generate-macos-icon.mjs',
      '--source',
      'assets/branding/wondershot-icon-master.png',
      '--png',
      out,
      '--no-icns'
    ]);

    const measured = measurePixelBounds(out, (r, g, b, a) => a > 8 && r > 220 && g > 220 && b > 220);

    expect(Math.abs(measured.centerX - 512)).toBeLessThanOrEqual(2);
  });

  test('keeps the foreground artwork optically smaller than the macOS plate', () => {
    const out = join(tmpdir(), `wondershot-macos-icon-foreground-${Date.now()}.png`);
    execFileSync('node', [
      'scripts/generate-macos-icon.mjs',
      '--source',
      'assets/branding/wondershot-icon-master.png',
      '--png',
      out,
      '--no-icns'
    ]);

    const measured = measurePixelBounds(out, (r, g, b, a) => a > 8 && r > 220 && g > 220 && b > 220);

    expect(measured.contentHeight).toBeLessThanOrEqual(560);
  });
});

function measureAlphaBounds(path: string | Buffer) {
  return measurePixelBounds(path, (_r, _g, _b, a) => a > 8);
}

function measurePixelBounds(
  path: string | Buffer,
  matches: (r: number, g: number, b: number, a: number) => boolean
) {
  const png = readPng(path);
  let minX = png.width;
  let minY = png.height;
  let maxX = -1;
  let maxY = -1;

  for (let y = 0; y < png.height; y += 1) {
    for (let x = 0; x < png.width; x += 1) {
      const offset = (y * png.width + x) * 4;
      if (
        matches(
          png.rgba[offset],
          png.rgba[offset + 1],
          png.rgba[offset + 2],
          png.rgba[offset + 3]
        )
      ) {
        minX = Math.min(minX, x);
        minY = Math.min(minY, y);
        maxX = Math.max(maxX, x);
        maxY = Math.max(maxY, y);
      }
    }
  }

  return {
    width: png.width,
    height: png.height,
    minX,
    minY,
    centerX: (minX + maxX) / 2,
    centerY: (minY + maxY) / 2,
    contentWidth: maxX - minX + 1,
    contentHeight: maxY - minY + 1
  };
}

function readPng(path: string | Buffer) {
  const file = Buffer.isBuffer(path) ? path : readFileSync(path);
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (!file.subarray(0, 8).equals(signature)) throw new Error(`Not a PNG: ${path}`);

  let offset = 8;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idat: Buffer[] = [];

  while (offset < file.length) {
    const length = file.readUInt32BE(offset);
    offset += 4;
    const type = file.subarray(offset, offset + 4).toString('ascii');
    offset += 4;
    const body = file.subarray(offset, offset + length);
    offset += length + 4;

    if (type === 'IHDR') {
      width = body.readUInt32BE(0);
      height = body.readUInt32BE(4);
      colorType = body[9];
    } else if (type === 'IDAT') {
      idat.push(body);
    } else if (type === 'IEND') {
      break;
    }
  }

  const channels = colorType === 6 ? 4 : 3;
  if (![3, 4].includes(channels)) throw new Error(`Unsupported PNG color type: ${colorType}`);
  const stride = width * channels;
  const raw = inflateSync(Buffer.concat(idat));
  const rgba = Buffer.alloc(width * height * 4);
  const prior = Buffer.alloc(stride);
  let input = 0;

  for (let y = 0; y < height; y += 1) {
    const filter = raw[input];
    input += 1;
    const row = Buffer.from(raw.subarray(input, input + stride));
    input += stride;

    for (let x = 0; x < stride; x += 1) {
      const left = x >= channels ? row[x - channels] : 0;
      const up = prior[x] ?? 0;
      const upLeft = x >= channels ? prior[x - channels] : 0;
      let value = row[x];
      if (filter === 1) value = (value + left) & 255;
      else if (filter === 2) value = (value + up) & 255;
      else if (filter === 3) value = (value + Math.floor((left + up) / 2)) & 255;
      else if (filter === 4) {
        const p = left + up - upLeft;
        const pa = Math.abs(p - left);
        const pb = Math.abs(p - up);
        const pc = Math.abs(p - upLeft);
        value = (value + (pa <= pb && pa <= pc ? left : pb <= pc ? up : upLeft)) & 255;
      } else if (filter !== 0) {
        throw new Error(`Unsupported PNG filter: ${filter}`);
      }
      row[x] = value;
    }

    row.copy(prior);
    for (let x = 0; x < width; x += 1) {
      const src = x * channels;
      const dst = (y * width + x) * 4;
      rgba[dst] = row[src];
      rgba[dst + 1] = row[src + 1];
      rgba[dst + 2] = row[src + 2];
      rgba[dst + 3] = channels === 4 ? row[src + 3] : 255;
    }
  }

  return { width, height, rgba };
}
