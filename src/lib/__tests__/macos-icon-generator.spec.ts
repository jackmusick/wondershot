import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { inflateSync } from 'node:zlib';
import { describe, expect, test } from 'vitest';

describe('macOS icon generator', () => {
  test('builds a 1024 template source with deterministic safe-area bounds', () => {
    const out = join(tmpdir(), `wondershot-macos-icon-${Date.now()}.png`);
    execFileSync('node', [
      'scripts/generate-macos-icon.mjs',
      '--source',
      'src-tauri/icons/icon.png',
      '--png',
      out,
      '--no-icns'
    ]);

    const measured = measureAlphaBounds(out);

    expect(measured.width).toBe(1024);
    expect(measured.height).toBe(1024);
    expect(measured.contentWidth).toBe(824);
    expect(measured.contentHeight).toBe(824);
    expect(measured.minX).toBe(100);
    expect(measured.minY).toBe(100);
  });

  test('centers the foreground artwork inside the macOS template', () => {
    const out = join(tmpdir(), `wondershot-macos-icon-centered-${Date.now()}.png`);
    execFileSync('node', [
      'scripts/generate-macos-icon.mjs',
      '--source',
      'src-tauri/icons/icon.png',
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
      'src-tauri/icons/icon.png',
      '--png',
      out,
      '--no-icns'
    ]);

    const measured = measurePixelBounds(out, (r, g, b, a) => a > 8 && r > 220 && g > 220 && b > 220);

    expect(measured.contentHeight).toBeLessThanOrEqual(560);
  });
});

function measureAlphaBounds(path: string) {
  return measurePixelBounds(path, (_r, _g, _b, a) => a > 8);
}

function measurePixelBounds(
  path: string,
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

function readPng(path: string) {
  const file = readFileSync(path);
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
