// Print an HTML file to PDF with Chromium (Node Playwright, preinstalled in the cloud session).
// Usage: node analysis/print_pdf.mjs reports/pilot/report.html reports/pilot/report.pdf
import { createRequire } from "module";
import path from "path";
import { pathToFileURL } from "url";

const require = createRequire(import.meta.url);
let playwright;
try {
  playwright = require("playwright");
} catch {
  // global install location in the Claude Code cloud image
  playwright = require(path.join(process.env.NODE_PATH || "/opt/node-tools/node_modules", "playwright"));
}

const [, , input, output] = process.argv;
const browser = await playwright.chromium.launch();
const page = await browser.newPage();
await page.goto(pathToFileURL(path.resolve(input)).href, { waitUntil: "load" });
await page.pdf({ path: output, format: "Letter", printBackground: true, preferCSSPageSize: true });
await browser.close();
