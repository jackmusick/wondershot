#!/usr/bin/env node
import { execFileSync } from 'node:child_process';
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { deflateSync, inflateSync } from 'node:zlib';

const CANVAS = 1024;
const PLATE = 824;
const TRAY = 64;
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
    execFileSync(process.execPath, ['node_modules/@tauri-apps/cli/tauri.js', 'icon', pngPath, '-o', outDir, '--ios-color', '#08090b'], { stdio: 'inherit' });
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

// Windows displays the full ICO canvas in small taskbar slots. Generate from
// the original artwork, rather than inheriting the macOS Dock safe area.
if (args.allIcons || args.windowsIco) {
  const path = resolve(args.windowsIco ?? join(dirname(pngPath), 'icon.ico'));
  mkdirSync(dirname(path), { recursive: true });
  writeWindowsIco(path, source);
  console.log(`Windows ICO: ${path}`);
}

if (args.allIcons || args.trayDir) {
  const trayDir = resolve(args.trayDir ?? dirname(pngPath));
  mkdirSync(trayDir, { recursive: true });
  const template = renderTrayTemplate(source);
  writePng(join(trayDir, 'tray-template.png'), TRAY, TRAY, template.rgba);
  const color = renderTrayColor(source);
  writePng(join(trayDir, 'tray.png'), TRAY, TRAY, color.rgba);
  console.log(`tray icons: ${trayDir}`);
}

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

// macOS menu-bar icons are template images: only alpha matters and AppKit
// tints them to match the bar. Keep the bright brackets and spark, drop the
// dark tile, and crop tightly so the glyph fills the status-item height.
function renderTrayTemplate(source) {
  // The tile's bevel catches a light highlight along its edge; only the inner
  // area holds the emblem.
  const tile = alphaBounds(source);
  const inset = Math.round(Math.max(tile.maxX - tile.minX, tile.maxY - tile.minY) * 0.08);
  const mask = { width: source.width, height: source.height, rgba: Buffer.alloc(source.rgba.length) };
  for (let y = tile.minY + inset; y <= tile.maxY - inset; y += 1) {
    for (let x = tile.minX + inset; x <= tile.maxX - inset; x += 1) {
      const i = (y * source.width + x) * 4;
      const brightness = Math.max(source.rgba[i], source.rgba[i + 1], source.rgba[i + 2]);
      const coverage = Math.min(1, Math.max(0, (brightness - 90) / 80));
      mask.rgba[i + 3] = Math.round(coverage * source.rgba[i + 3]);
    }
  }
  return fitSquare(mask, boundsWhere(mask, (offset) => mask.rgba[offset + 3] > 128), 0);
}

// Linux and Windows trays show full-color icons; cropping away the app icon's
// safe-area margin makes the tile fill the tray slot like neighboring icons.
function renderTrayColor(source) {
  return fitSquare(source, alphaBounds(source), 0);
}

function fitSquare(image, bounds, padding, size = TRAY) {
  const side = Math.max(bounds.maxX - bounds.minX + 1, bounds.maxY - bounds.minY + 1);
  const minX = Math.round((bounds.minX + bounds.maxX - side + 1) / 2);
  const minY = Math.round((bounds.minY + bounds.maxY - side + 1) / 2);
  const cropped = { width: side, height: side, rgba: Buffer.alloc(side * side * 4) };
  for (let y = 0; y < side; y += 1) {
    for (let x = 0; x < side; x += 1) {
      const sx = minX + x, sy = minY + y;
      if (sx < bounds.minX || sy < bounds.minY || sx > bounds.maxX || sy > bounds.maxY) continue;
      image.rgba.copy(cropped.rgba, (y * side + x) * 4, (sy * image.width + sx) * 4, (sy * image.width + sx) * 4 + 4);
    }
  }
  const inner = size - padding * 2;
  const fitted = resizeArea(cropped, inner, inner);
  const canvas = Buffer.alloc(size * size * 4);
  blit(fitted, canvas, padding, padding, size);
  return { width: size, height: size, rgba: canvas };
}

function writeWindowsIco(path, source) {
  // Include intermediate DPI sizes so Windows need not enlarge a smaller frame.
  // Tauri embeds entries()[0] as the running window icon, rather than picking
  // a size. Lead with the largest frame to avoid a tiny native HICON.
  const sizes = [256, 128, 96, 64, 48, 40, 32, 24, 20, 16];
  const bounds = alphaBounds(source);
  const frames = sizes.map((size) => {
    const image = fitSquare(source, bounds, Math.max(1, Math.round(size / 64)), size);
    return encodePng(size, size, image.rgba);
  });
  const directory = Buffer.alloc(6 + sizes.length * 16);
  directory.writeUInt16LE(1, 2); // ICO, rather than cursor
  directory.writeUInt16LE(sizes.length, 4);
  let offset = directory.length;
  sizes.forEach((size, index) => {
    const entry = 6 + index * 16;
    directory[entry] = directory[entry + 1] = size === 256 ? 0 : size;
    directory.writeUInt16LE(1, entry + 4);
    directory.writeUInt16LE(32, entry + 6);
    directory.writeUInt32LE(frames[index].length, entry + 8);
    directory.writeUInt32LE(offset, entry + 12);
    offset += frames[index].length;
  });
  writeFileSync(path, Buffer.concat([directory, ...frames]));
}

// Large downscales need area averaging; bilinear sampling skips most source
// pixels and leaves jagged edges at tray sizes. Color is alpha-weighted so
// transparent pixels do not darken antialiased edges.
function resizeArea(image, width, height) {
  const rgba = Buffer.alloc(width * height * 4);
  const scaleX = image.width / width;
  const scaleY = image.height / height;
  for (let y = 0; y < height; y += 1) {
    const y0 = Math.floor(y * scaleY);
    const y1 = Math.max(y0 + 1, Math.floor((y + 1) * scaleY));
    for (let x = 0; x < width; x += 1) {
      const x0 = Math.floor(x * scaleX);
      const x1 = Math.max(x0 + 1, Math.floor((x + 1) * scaleX));
      let r = 0, g = 0, b = 0, a = 0, count = 0;
      for (let sy = y0; sy < y1; sy += 1) {
        for (let sx = x0; sx < x1; sx += 1) {
          const offset = (sy * image.width + sx) * 4;
          const alpha = image.rgba[offset + 3];
          r += image.rgba[offset] * alpha;
          g += image.rgba[offset + 1] * alpha;
          b += image.rgba[offset + 2] * alpha;
          a += alpha;
          count += 1;
        }
      }
      const target = (y * width + x) * 4;
      if (a > 0) {
        rgba[target] = Math.round(r / a);
        rgba[target + 1] = Math.round(g / a);
        rgba[target + 2] = Math.round(b / a);
      }
      rgba[target + 3] = Math.round(a / count);
    }
  }
  return { width, height, rgba };
}

function boundsWhere(image, matches) {
  let minX = image.width, minY = image.height, maxX = -1, maxY = -1;
  for (let y = 0; y < image.height; y += 1) {
    for (let x = 0; x < image.width; x += 1) {
      if (!matches((y * image.width + x) * 4)) continue;
      minX = Math.min(minX, x); minY = Math.min(minY, y);
      maxX = Math.max(maxX, x); maxY = Math.max(maxY, y);
    }
  }
  if (maxX < minX) fail('no matching pixels in source icon');
  return { minX, minY, maxX, maxY };
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
  writeFileSync(path, encodePng(width, height, rgba));
}

function encodePng(width, height, rgba) {
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
  return Buffer.concat([
    signature,
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', deflateSync(rows, { level: 9 })),
    pngChunk('IEND', Buffer.alloc(0))
  ]);
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
    else if (arg === '--tray-dir') parsed.trayDir = argv[++i];
    else if (arg === '--windows-ico') parsed.windowsIco = argv[++i];
    else if (arg === '--help' || arg === '-h') {
      console.log(`Usage: node ${basename(process.argv[1])} [--source icon.png] [--png out.png] [--icns out.icns] [--no-icns] [--all-icons] [--tray-dir dir] [--windows-ico out.ico]`);
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
