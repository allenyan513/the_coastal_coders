// Draws the QR code for slides and print. The app draws its own, so this is only for use outside it.
// Usage: pnpm qr [url]
import { mkdirSync, writeFileSync } from "node:fs";
import { deflateSync, crc32 } from "node:zlib";
import qrcode from "qrcode-generator";

const url = process.argv[2] ?? "https://coastalaction.ligangyan.com/start";
const out = new URL("../../demo/qr/", import.meta.url);
const QUIET = 4;  // the blank margin a scanner needs, in QR squares
const PIXELS = 24;  // PNG pixels per QR square, sharp on a projected slide

const qr = qrcode(0, "M");
qr.addData(url);
qr.make();
const count = qr.getModuleCount();
const side = count + QUIET * 2;
const dark = (row, col) => row >= 0 && col >= 0 && row < count && col < count && qr.isDark(row, col);

function chunk(type, data) {
  const body = Buffer.concat([Buffer.from(type), data]);
  const size = Buffer.alloc(4);
  size.writeUInt32BE(data.length);
  const check = Buffer.alloc(4);
  check.writeUInt32BE(crc32(body));
  return Buffer.concat([size, body, check]);
}

function png() {
  const width = side * PIXELS;
  const lines = [];
  for (let row = -QUIET; row < count + QUIET; row++) {
    const line = Buffer.alloc(width + 1, 255);  // grayscale, one byte a pixel, after a filter byte
    line[0] = 0;
    for (let col = -QUIET; col < count + QUIET; col++) {
      if (dark(row, col)) line.fill(0, 1 + (col + QUIET) * PIXELS, 1 + (col + QUIET + 1) * PIXELS);
    }
    for (let i = 0; i < PIXELS; i++) lines.push(line);
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(width, 4);
  header[8] = 8;  // bits per pixel
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(Buffer.concat(lines))),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

function svg() {
  let path = "";
  for (let row = 0; row < count; row++) {
    for (let col = 0; col < count; col++) if (dark(row, col)) path += `M${col} ${row}h1v1h-1z`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${-QUIET} ${-QUIET} ${side} ${side}" shape-rendering="crispEdges"><rect x="${-QUIET}" y="${-QUIET}" width="${side}" height="${side}" fill="#fff"/><path d="${path}"/></svg>\n`;
}

mkdirSync(out, { recursive: true });
writeFileSync(new URL("start.png", out), png());
writeFileSync(new URL("start.svg", out), svg());
console.log(`${url} -> tidecount/demo/qr/start.png and start.svg`);
