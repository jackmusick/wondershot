#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { deflateSync, inflateSync } from 'node:zlib';

const CANVAS = 1024;
const PLATE = 824;
const args = parseArgs(process.argv.slice(2));
const sourcePath = resolve(args.source ?? 'assets/branding/wondershot-icon-master.png');
const pngPath = resolve(args.png ?? 'src-tauri/icons/icon.png');
const icnsPath = args.icns === false ? undefined : resolve(args.icns ?? 'src-tauri/icons/icon.icns');

if (!existsSync(sourcePath)) {
  fail(`source icon not found: ${sourcePath}`);
}

const source = readPng(sourcePath);
const output = renderMacosIcon(source);
mkdirSync(dirname(pngPath), { recursive: true });
writePng(pngPath, CANVAS, CANVAS, output);

if (icnsPath) {
  const outDir = mkdtempSync(join(tmpdir(), 'wondershot-tauri-icons-'));
  try {
    execFileSync('node_modules/.bin/tauri', ['icon', pngPath, '-o', outDir, '--ios-color', '#08090b'], { stdio: 'inherit' });
    const generated = join(outDir, 'icon.icns');
    if (!existsSync(generated)) fail(`Tauri icon generation did not create ${generated}`);
    if (args.allIcons) cpSync(outDir, dirname(icnsPath), { recursive: true });
    else writeFileSync(icnsPath, readFileSync(generated));
  } finally {
    rmSync(outDir, { recursive: true, force: true });
  }
}

// Tauri also writes a 512px icon.png; retain our full-resolution 1024px source.
if (args.allIcons) writePng(pngPath, CANVAS, CANVAS, output);

console.log(`macOS icon source: ${pngPath}`);
if (icnsPath) console.log(`macOS ICNS: ${icnsPath}`);

// The approved artwork already includes its tile and spectrum rim. Preserve
// every color instead of extracting a white silhouette onto the old teal plate.
function renderMacosIcon(source) {
  const bounds = alphaBounds(source);
  const width = bounds.maxX - bounds.minX + 1;
  const height = bounds.maxY - bounds.minY + 1;
  const cropped = { width, height, rgba: Buffer.alloc(width * height * 4) };
  for (let y = 0; y < height; y += 1) {
    const start = ((bounds.minY + y) * source.width + bounds.minX) * 4;
    source.rgba.copy(cropped.rgba, y * width * 4, start, start + width * 4);
  }
  const factor = PLATE / Math.max(width, height);
  const fitted = resizeBilinear(cropped, Math.round(width * factor), Math.round(height * factor));
  const canvas = Buffer.alloc(CANVAS * CANVAS * 4);
  blit(fitted, canvas, Math.floor((CANVAS - fitted.width) / 2), Math.floor((CANVAS - fitted.height) / 2), CANVAS);
  return canvas;
}

function alphaBounds(source) {
  let minX = source.width, minY = source.height, maxX = -1, maxY = -1;
  for (let y = 0; y < source.height; y += 1) {
    for (let x = 0; x < source.width; x += 1) {
      if (source.rgba[(y * source.width + x) * 4 + 3] <= 8) continue;
      minX = Math.min(minX, x); minY = Math.min(minY, y);
      maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
    }
  }
  if (maxX < minX) fail('source icon is fully transparent');
  return { minX, minY, maxX, maxY };
}

function resizeBilinear(image, width, height) {
  const rgba = Buffer.alloc(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    const sourceY = image.height === 1 ? 0 : (y / (height - 1)) * (image.height - 1);
    const y0 = Math.floor(sourceY);
    const y1 = Math.min(image.height - 1, y0 + 1);
    const yWeight = sourceY - y0;
    for (let x = 0; x < width; x += 1) {
      const sourceX = image.width === 1 ? 0 : (x / (width - 1)) * (image.width - 1);
      const x0 = Math.floor(sourceX);
      const x1 = Math.min(image.width - 1, x0 + 1);
      const xWeight = sourceX - x0;
      const targetOffset = (y * width + x) * 4;

      for (let channel = 0; channel < 4; channel += 1) {
        const top =
          image.rgba[(y0 * image.width + x0) * 4 + channel] * (1 - xWeight) +
          image.rgba[(y0 * image.width + x1) * 4 + channel] * xWeight;
        const bottom =
          image.rgba[(y1 * image.width + x0) * 4 + channel] * (1 - xWeight) +
          image.rgba[(y1 * image.width + x1) * 4 + channel] * xWeight;
        rgba[targetOffset + channel] = Math.round(top * (1 - yWeight) + bottom * yWeight);
      }
    }
  }
  return { width, height, rgba };
}

function blit(source, target, left, top, targetWidth) {
  for (let y = 0; y < source.height; y += 1) {
    for (let x = 0; x < source.width; x += 1) {
      const sourceOffset = (y * source.width + x) * 4;
      const alpha = source.rgba[sourceOffset + 3] / 255;
      if (alpha <= 0) continue;

      const targetOffset = ((top + y) * targetWidth + left + x) * 4;
      const inverse = 1 - alpha;
      target[targetOffset] = Math.round(source.rgba[sourceOffset] * alpha + target[targetOffset] * inverse);
      target[targetOffset + 1] = Math.round(source.rgba[sourceOffset + 1] * alpha + target[targetOffset + 1] * inverse);
      target[targetOffset + 2] = Math.round(source.rgba[sourceOffset + 2] * alpha + target[targetOffset + 2] * inverse);
      target[targetOffset + 3] = Math.max(target[targetOffset + 3], source.rgba[sourceOffset + 3]);
    }
  }
}

function readPng(path) {
  const file = readFileSync(path);
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (!file.subarray(0, 8).equals(signature)) fail(`not a PNG: ${path}`);

  let offset = 8;
  let width = 0;
  let height = 0;
  let colorType = 0;
  const idat = [];

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
  if (![3, 4].includes(channels)) fail(`unsupported PNG color type: ${colorType}`);
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
        fail(`unsupported PNG filter: ${filter}`);
      }
      row[x] = value;
    }

    row.copy(prior);
    for (let x = 0; x < width; x += 1) {
      const sourceOffset = x * channels;
      const targetOffset = (y * width + x) * 4;
      rgba[targetOffset] = row[sourceOffset];
      rgba[targetOffset + 1] = row[sourceOffset + 1];
      rgba[targetOffset + 2] = row[sourceOffset + 2];
      rgba[targetOffset + 3] = channels === 4 ? row[sourceOffset + 3] : 255;
    }
  }

  return { width, height, rgba };
}

function writePng(path, width, height, rgba) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 6;
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;

  const rows = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) {
    rows[y * (width * 4 + 1)] = 0;
    rgba.copy(rows, y * (width * 4 + 1) + 1, y * width * 4, (y + 1) * width * 4);
  }

  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  writeFileSync(path, Buffer.concat([
    signature,
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', deflateSync(rows, { level: 9 })),
    pngChunk('IEND', Buffer.alloc(0))
  ]));
}

function pngChunk(type, data) {
  const typeBuffer = Buffer.from(type);
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0);
  typeBuffer.copy(out, 4);
  data.copy(out, 8);
  out.writeUInt32BE(crc32(Buffer.concat([typeBuffer, data])), 8 + data.length);
  return out;
}

function crc32(buffer) {
  let crc = ~0;
  for (const byte of buffer) {
    crc ^= byte;
    for (let i = 0; i < 8; i += 1) {
      crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
    }
  }
  return ~crc >>> 0;
}

function parseArgs(argv) {
  const parsed = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--all-icons') parsed.allIcons = true;
    else if (arg === '--no-icns') parsed.icns = false;
    else if (arg === '--source') parsed.source = argv[++i];
    else if (arg === '--png') parsed.png = argv[++i];
    else if (arg === '--icns') parsed.icns = argv[++i];
    else if (arg === '--help' || arg === '-h') {
      console.log(`Usage: node ${basename(process.argv[1])} [--source icon.png] [--png out.png] [--icns out.icns] [--no-icns] [--all-icons]`);
      process.exit(0);
    } else {
      fail(`unknown argument: ${arg}`);
    }
  }
  return parsed;
}

function fail(message) {
  console.error(message);
  process.exit(1);
}
