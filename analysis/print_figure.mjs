// Print one paper figure (an HTML page) to a one-page vector PDF of a given width; the page height is the content's.
// Usage: node analysis/print_figure.mjs figure.html figure.pdf 6.75
// Chromium comes with Node Playwright (preinstalled in the cloud session; elsewhere: npm i playwright).
import { createRequire } from "module";
import path from "path";
import { pathToFileURL } from "url";

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require("playwright");
} catch {
  playwright = require(path.join(process.env.NODE_PATH || "/opt/node-tools/node_modules", "playwright"));
}

const [, , input, output, widthIn] = process.argv;
const width = Number(widthIn || "6.75");
const browser = await playwright.chromium.launch();
const page = await browser.newPage({ viewport: { width: Math.round(width * 96), height: 800 } });
await page.emulateMedia({ media: "screen" });
await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: "load" });
await page.evaluate(() => document.fonts.ready);
const height = await page.evaluate(() => Math.ceil(document.querySelector("#fig").getBoundingClientRect().height));
await page.pdf({ path: output, width: `${width}in`, height: `${height + 2}px`, printBackground: true,
                 margin: { top: 0, right: 0, bottom: 0, left: 0 }, pageRanges: "1" });
await browser.close();
console.log(`${output}: ${width} in x ${((height + 2) / 96).toFixed(2)} in`);
