#!/usr/bin/env node
/**
 * Invoice review utility:
 * - Reads invoices from PDF/image files
 * - Extracts text/OCR
 * - Matches invoice lines against local product database prices
 * - Flags mismatched prices
 * - Groups results by Project / PO
 * - Writes JSON outputs + a PDF review report
 *
 * Usage:
 *   node scripts/review-invoices.mjs --invoices "./invoices" --db "./data/product-prices.json"
 */
import fs from 'fs';
import path from 'path';
import process from 'process';
import ExcelJS from 'exceljs';
import { createWorker } from 'tesseract.js';
import { PDFDocument, StandardFonts, rgb } from 'pdf-lib';
import * as pdfjs from 'pdfjs-dist/legacy/build/pdf.mjs';

const SUPPORTED_EXTENSIONS = new Set([
  '.pdf',
  '.jpg',
  '.jpeg',
  '.png',
  '.webp',
  '.tif',
  '.tiff',
]);

const DEFAULTS = {
  invoices: './invoices',
  db: './data/product-prices.json',
  output: './output/invoice-review',
  tolerance: 0.009,
  extractOnly: false,
  files: [],
};

function parseArgs(argv) {
  const args = { ...DEFAULTS };
  for (let i = 2; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === '--invoices') {
      args.invoices = argv[i + 1];
      i += 1;
      continue;
    }
    if (arg === '--db') {
      args.db = argv[i + 1];
      i += 1;
      continue;
    }
    if (arg === '--out') {
      args.output = argv[i + 1];
      i += 1;
      continue;
    }
    if (arg === '--tolerance') {
      args.tolerance = Number(argv[i + 1]);
      i += 1;
      continue;
    }
    if (arg === '--files') {
      args.files.push(argv[i + 1]);
      i += 1;
      continue;
    }
    if (arg === '--extract-only') {
      args.extractOnly = true;
      continue;
    }
    if (arg === '--help' || arg === '-h') {
      args.help = true;
    }
  }

  args.files = args.files
    .flatMap((entry) => String(entry).split(','))
    .map((entry) => entry.trim())
    .filter(Boolean);
  return args;
}

function printHelp() {
  console.log(`
Invoice reviewer

Required:
  --invoices <path>   Folder containing invoices (PDF/JPG/JPEG/PNG/TIFF/WEBP)
  --db <path>         Product price database JSON (required unless --extract-only)

Optional:
  --files <paths>     Specific files to process (repeat flag or comma-separated list)
  --out <path>        Output folder (default: ${DEFAULTS.output})
  --tolerance <num>   Allowed price delta before flagging (default: ${DEFAULTS.tolerance})
  --extract-only      Parse invoice metadata + item lines without DB comparison

JSON schema for database file:
[
  {
    "sku": "LMBR-2X4X8",
    "name": "Lumber 2x4x8",
    "unitPrice": 4.99,
    "aliases": ["2x4x8 lumber", "stud 2x4 8"]
  }
]
  `.trim());
}

function ensureDir(dirPath) {
  fs.mkdirSync(dirPath, { recursive: true });
}

function walkFiles(dir) {
  const output = [];
  if (!fs.existsSync(dir)) return output;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      output.push(...walkFiles(full));
      continue;
    }
    if (SUPPORTED_EXTENSIONS.has(path.extname(entry.name).toLowerCase())) {
      output.push(full);
    }
  }
  return output;
}

function normalizeText(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function parseMoney(value) {
  if (!value) return Number.NaN;
  const clean = String(value).replace(/[$,\s]/g, '');
  const parsed = Number(clean);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function parsePriceCandidates(line) {
  const matches = line.match(/\$?\d{1,3}(?:,\d{3})*(?:\.\d{2})|\$?\d+\.\d{2}/g) || [];
  return matches.map(parseMoney).filter((n) => Number.isFinite(n) && n > 0);
}

function cleanCapturedValue(value) {
  if (!value) return '';
  return value
    .replace(/\s+/g, ' ')
    .replace(/\b(?:CHARGE|INVOICE|ORDER|DATE|TIME|PAGE)\b.*$/i, '')
    .trim();
}

function extractProjectAndPo(text) {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  const extractFromLine = (pattern) => {
    const line = lines.find((candidate) => pattern.test(candidate));
    if (!line) return '';
    const match = line.match(pattern);
    return cleanCapturedValue(match?.[1] || '');
  };

  const project =
    extractFromLine(/^Project(?:\s*Name)?\s*[:#-]\s*(.+)$/i) ||
    extractFromLine(/^PO\/Job Name\s*:\s*(.+)$/i) ||
    extractFromLine(/^JOB\s+(.+)$/i) ||
    'UNASSIGNED_PROJECT';

  const po =
    extractFromLine(/^PO#\s+(.+)$/i) ||
    extractFromLine(/^PO#\s*[:\-]\s*(.+)$/i) ||
    extractFromLine(/^PO\s*[:\-]\s*(.+)$/i) ||
    extractFromLine(/^P\.O\.\s*#?\s*[:\-]?\s*(.+)$/i) ||
    extractFromLine(/^Purchase\s*Order#?\s*[:\-]?\s*(.+)$/i) ||
    extractFromLine(/^Order\s*#\s*(.+)$/i) ||
    extractFromLine(/^Invoice Number\(s\)\s*#\s*(.+)$/i) ||
    'UNASSIGNED_PO';

  return {
    project,
    po,
  };
}

async function extractTextFromPdf(filePath) {
  const data = fs.readFileSync(filePath);
  const loadingTask = pdfjs.getDocument({ data: new Uint8Array(data) });
  const pdf = await loadingTask.promise;
  const textParts = [];
  for (let pageNo = 1; pageNo <= pdf.numPages; pageNo += 1) {
    const page = await pdf.getPage(pageNo);
    const content = await page.getTextContent();
    const lineParts = [];
    for (const item of content.items) {
      const token = (item.str || '').trim();
      if (token) lineParts.push(token);
      if (item.hasEOL) lineParts.push('\n');
      else if (token) lineParts.push(' ');
    }
    const pageText = lineParts.join('').replace(/[ \t]+\n/g, '\n').trim();
    textParts.push(pageText);
  }
  return textParts.join('\n');
}

let sharedWorker = null;
async function getWorker() {
  if (sharedWorker) return sharedWorker;
  sharedWorker = await createWorker('eng');
  return sharedWorker;
}

async function extractTextFromImage(filePath) {
  const worker = await getWorker();
  const result = await worker.recognize(filePath);
  return result.data.text || '';
}

async function extractText(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === '.pdf') return extractTextFromPdf(filePath);
  return extractTextFromImage(filePath);
}

function loadDatabase(dbPath) {
  const raw = fs.readFileSync(dbPath, 'utf8');
  const parsed = JSON.parse(raw);
  if (!Array.isArray(parsed)) {
    throw new Error('Database JSON must be an array of products.');
  }
  return parsed.map((item) => ({
    sku: String(item.sku || '').trim(),
    name: String(item.name || '').trim(),
    unitPrice: Number(item.unitPrice),
    aliases: Array.isArray(item.aliases) ? item.aliases.map(String) : [],
  }));
}

function buildProductMatchers(products) {
  return products.map((product) => {
    const nameNorm = normalizeText(product.name);
    const aliasNorm = product.aliases.map(normalizeText).filter(Boolean);
    const skuNorm = normalizeText(product.sku);
    return { ...product, nameNorm, aliasNorm, skuNorm };
  });
}

function lineMentionsProduct(lineNorm, product) {
  if (!lineNorm) return false;
  if (product.skuNorm && lineNorm.includes(product.skuNorm)) return true;
  if (product.nameNorm && lineNorm.includes(product.nameNorm)) return true;
  return product.aliasNorm.some((a) => lineNorm.includes(a));
}

function parseInvoiceLineItems(text) {
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.replace(/\s+/g, ' ').trim())
    .filter(Boolean);

  const extracted = [];
  const seen = new Set();

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const compactSkuMatch = line.match(
      /^SKU\s+([A-Z0-9-]+)\s+(\d+)\s+\$?(-?\d+\.\d{2})\s+\$?(-?\d+\.\d{2})\s+\$?(-?\d+\.\d{2})\s+\$?(-?\d+\.\d{2})/i
    );
    if (compactSkuMatch) {
      const sku = compactSkuMatch[1];
      const qty = Number(compactSkuMatch[2]);
      const unitPrice = parseMoney(compactSkuMatch[3]);
      const key = `${sku}|${qty}|${unitPrice}|${line}`;
      if (!seen.has(key) && Number.isFinite(unitPrice)) {
        seen.add(key);
        extracted.push({
          sku,
          quantity: Number.isFinite(qty) ? qty : null,
          observedPrice: unitPrice,
          sourceLine: line,
        });
      }
      continue;
    }

    const skuOnlyMatch = line.match(/^SKU\s+([A-Z0-9-]+)$/i);
    if (skuOnlyMatch && i + 1 < lines.length) {
      const nextLine = lines[i + 1];
      const amountMatch = nextLine.match(
        /^(\d+)\s+\$?(-?\d+\.\d{2})\s+\$?(-?\d+\.\d{2})\s+\$?(-?\d+\.\d{2})\s+\$?(-?\d+\.\d{2})/i
      );
      if (amountMatch) {
        const sku = skuOnlyMatch[1];
        const qty = Number(amountMatch[1]);
        const unitPrice = parseMoney(amountMatch[2]);
        const key = `${sku}|${qty}|${unitPrice}|${nextLine}`;
        if (!seen.has(key) && Number.isFinite(unitPrice)) {
          seen.add(key);
          extracted.push({
            sku,
            quantity: Number.isFinite(qty) ? qty : null,
            observedPrice: unitPrice,
            sourceLine: `${line} | ${nextLine}`,
          });
        }
      }
      continue;
    }

    const sherwinLikeRow = line.match(
      /^\S+\s+\S+(?:\s+\S+)+\s+(\d+)\s+(-?\d+\.\d{2})\s+(-?\d+\.\d{2})$/i
    );
    if (sherwinLikeRow) {
      const tokens = line.split(/\s+/);
      const skuCandidate =
        tokens.find((token) => /^[A-Z]\d[A-Z0-9]{4,}$/i.test(token)) ||
        tokens.find((token) => /^\d{3,5}-\d{4,6}$/i.test(token)) ||
        '';
      const qty = Number(sherwinLikeRow[1]);
      const unitPrice = parseMoney(sherwinLikeRow[2]);
      const key = `${skuCandidate}|${qty}|${unitPrice}|${line}`;
      if (!seen.has(key) && Number.isFinite(unitPrice)) {
        seen.add(key);
        extracted.push({
          sku: skuCandidate,
          quantity: Number.isFinite(qty) ? qty : null,
          observedPrice: unitPrice,
          sourceLine: line,
        });
      }
    }
  }

  return extracted;
}

function findLineItemsAndMismatches(text, products, tolerance, sourceFile) {
  const parsedItems = parseInvoiceLineItems(text);
  const lines = text
    .split(/\r?\n/)
    .map((l) => l.replace(/\s+/g, ' ').trim())
    .filter(Boolean);
  const findings = [];
  const seen = new Set();
  const productsBySku = new Map(
    products
      .filter((product) => product.skuNorm)
      .map((product) => [product.skuNorm, product])
  );

  for (const parsed of parsedItems) {
    const skuNorm = normalizeText(parsed.sku || '');
    const product = skuNorm ? productsBySku.get(skuNorm) : null;
    if (!product || !Number.isFinite(product.unitPrice)) continue;
    const diff = parsed.observedPrice - product.unitPrice;
    if (Math.abs(diff) <= tolerance) continue;
    const key = `${sourceFile}|${product.sku}|${parsed.sourceLine}`;
    if (seen.has(key)) continue;
    seen.add(key);
    findings.push({
      sku: product.sku,
      productName: product.name,
      expectedPrice: Number(product.unitPrice.toFixed(2)),
      observedPrice: Number(parsed.observedPrice.toFixed(2)),
      difference: Number(diff.toFixed(2)),
      sourceLine: parsed.sourceLine,
    });
  }

  for (const line of lines) {
    const lineNorm = normalizeText(line);
    const prices = parsePriceCandidates(line);
    if (!prices.length) continue;

    for (const product of products) {
      if (!lineMentionsProduct(lineNorm, product)) continue;
      if (!Number.isFinite(product.unitPrice)) continue;
      const observed = prices[0];
      const diff = observed - product.unitPrice;
      if (Math.abs(diff) <= tolerance) continue;

      const key = `${sourceFile}|${product.sku}|${line}`;
      if (seen.has(key)) continue;
      seen.add(key);

      findings.push({
        sku: product.sku,
        productName: product.name,
        expectedPrice: Number(product.unitPrice.toFixed(2)),
        observedPrice: Number(observed.toFixed(2)),
        difference: Number(diff.toFixed(2)),
        sourceLine: line,
      });
    }
  }

  return findings;
}

function groupKey(project, po) {
  return `${project}__${po}`;
}

function groupResults(items) {
  const map = new Map();
  for (const item of items) {
    const key = groupKey(item.project, item.po);
    if (!map.has(key)) {
      map.set(key, {
        project: item.project,
        po: item.po,
        invoiceCount: 0,
        flaggedCount: 0,
        invoices: [],
      });
    }
    const group = map.get(key);
    group.invoiceCount += 1;
    group.flaggedCount += item.flaggedItems.length;
    group.invoices.push({
      file: item.file,
      flaggedItems: item.flaggedItems,
    });
  }
  return Array.from(map.values()).sort((a, b) =>
    `${a.project}${a.po}`.localeCompare(`${b.project}${b.po}`)
  );
}

function buildCandidateProducts(invoiceResults) {
  const map = new Map();
  for (const invoice of invoiceResults) {
    for (const item of invoice.parsedItems || []) {
      const sku = String(item.sku || '').trim();
      if (!sku) continue;
      if (!Number.isFinite(item.observedPrice)) continue;
      const key = `${sku}|${item.observedPrice.toFixed(2)}`;
      if (map.has(key)) continue;
      map.set(key, {
        sku,
        name: sku,
        unitPrice: Number(item.observedPrice.toFixed(2)),
        aliases: [],
      });
    }
  }
  return Array.from(map.values()).sort((a, b) => a.sku.localeCompare(b.sku));
}

async function writePdfReport(grouped, outPath) {
  const pdf = await PDFDocument.create();
  const font = await pdf.embedFont(StandardFonts.Helvetica);
  const fontBold = await pdf.embedFont(StandardFonts.HelveticaBold);

  let page = pdf.addPage([792, 612]);
  let y = 580;
  const marginX = 36;
  const lineHeight = 14;

  function newPage() {
    page = pdf.addPage([792, 612]);
    y = 580;
  }

  function writeLine(text, options = {}) {
    const {
      size = 10,
      bold = false,
      color = rgb(0, 0, 0),
      indent = 0,
    } = options;
    if (y < 40) newPage();
    page.drawText(text, {
      x: marginX + indent,
      y,
      size,
      font: bold ? fontBold : font,
      color,
      maxWidth: 720 - indent,
    });
    y -= lineHeight;
  }

  writeLine('Invoice Price Variance Report', { size: 15, bold: true });
  writeLine(`Generated: ${new Date().toISOString()}`, { size: 10 });
  y -= 4;

  if (!grouped.length) {
    writeLine('No mismatched prices found.', {
      size: 12,
      bold: true,
      color: rgb(0, 0.4, 0),
    });
  }

  for (const group of grouped) {
    writeLine(
      `Project: ${group.project} | PO: ${group.po} | Invoices: ${group.invoiceCount} | Flags: ${group.flaggedCount}`,
      { size: 11, bold: true, color: rgb(0.12, 0.12, 0.45) }
    );
    for (const invoice of group.invoices) {
      if (!invoice.flaggedItems.length) continue;
      writeLine(`Invoice: ${invoice.file}`, { size: 10, bold: true, indent: 8 });
      for (const item of invoice.flaggedItems) {
        const line = `- ${item.sku || '(no sku)'} ${item.productName}: DB ${item.expectedPrice.toFixed(2)} | Invoice ${item.observedPrice.toFixed(2)} | Diff ${item.difference.toFixed(2)}`;
        writeLine(line, { size: 9, indent: 18 });
      }
      y -= 4;
    }
    y -= 6;
  }

  fs.writeFileSync(outPath, await pdf.save());
}

async function writeXlsxReport(grouped, summary, outPath) {
  const workbook = new ExcelJS.Workbook();
  workbook.creator = 'Paintbrush.pro';
  workbook.created = new Date();

  const summarySheet = workbook.addWorksheet('Summary');
  summarySheet.properties.defaultRowHeight = 20;
  summarySheet.columns = [
    { header: 'Metric', key: 'metric', width: 38 },
    { header: 'Value', key: 'value', width: 28 },
  ];
  summarySheet.mergeCells('A1:B1');
  summarySheet.getCell('A1').value = 'Skyline Invoice Variance Review';
  summarySheet.getCell('A1').font = {
    bold: true,
    size: 16,
    color: { argb: 'FFFFFFFF' },
  };
  summarySheet.getCell('A1').alignment = { horizontal: 'center', vertical: 'middle' };
  summarySheet.getCell('A1').fill = {
    type: 'pattern',
    pattern: 'solid',
    fgColor: { argb: 'FF0F2744' },
  };
  summarySheet.getRow(1).height = 28;

  summarySheet.mergeCells('A2:B2');
  summarySheet.getCell('A2').value = 'Executive Summary';
  summarySheet.getCell('A2').font = { bold: true, size: 11, color: { argb: 'FF0F2744' } };
  summarySheet.getCell('A2').alignment = { horizontal: 'left', vertical: 'middle' };
  summarySheet.getRow(2).height = 20;

  const summaryHeader = summarySheet.getRow(4);
  summaryHeader.values = ['Metric', 'Value'];
  summaryHeader.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  summaryHeader.fill = {
    type: 'pattern',
    pattern: 'solid',
    fgColor: { argb: 'FF1F3A5F' },
  };
  summaryHeader.alignment = { vertical: 'middle', horizontal: 'left' };

  summarySheet.addRows([
    { metric: 'Generated At', value: new Date(summary.createdAt).toLocaleString() },
    { metric: 'Invoices Scanned', value: summary.scannedInvoices },
    { metric: 'Flagged Groups', value: summary.flaggedGroups },
    { metric: 'Flagged Items', value: summary.totalFlaggedItems },
    { metric: 'Mode', value: summary.extractOnly ? 'Extract Only' : 'Comparison' },
  ]);
  summarySheet.eachRow((row, rowNumber) => {
    row.alignment = { vertical: 'middle', horizontal: 'left' };
    if (rowNumber > 4) {
      row.getCell(2).font = { bold: true };
    }
    if (rowNumber >= 4) {
      row.eachCell((cell) => {
        cell.border = {
          top: { style: 'thin', color: { argb: 'FFD8DEE8' } },
          left: { style: 'thin', color: { argb: 'FFD8DEE8' } },
          bottom: { style: 'thin', color: { argb: 'FFD8DEE8' } },
          right: { style: 'thin', color: { argb: 'FFD8DEE8' } },
        };
      });
    }
  });

  const detailSheet = workbook.addWorksheet('Flagged Items');
  detailSheet.properties.defaultRowHeight = 20;
  detailSheet.columns = [
    { header: 'Project', key: 'project', width: 28 },
    { header: 'PO', key: 'po', width: 26 },
    { header: 'Invoice File', key: 'invoiceFile', width: 44 },
    { header: 'SKU', key: 'sku', width: 16 },
    { header: 'Product Name', key: 'productName', width: 32 },
    { header: 'DB Price', key: 'expectedPrice', width: 12 },
    { header: 'Invoice Price', key: 'observedPrice', width: 14 },
    { header: 'Difference', key: 'difference', width: 12 },
    { header: 'Source Line', key: 'sourceLine', width: 72 },
  ];
  detailSheet.mergeCells('A1:I1');
  detailSheet.getCell('A1').value = 'Flagged Invoice Price Variances';
  detailSheet.getCell('A1').font = { bold: true, size: 14, color: { argb: 'FFFFFFFF' } };
  detailSheet.getCell('A1').alignment = {
    horizontal: 'left',
    vertical: 'middle',
  };
  detailSheet.getCell('A1').fill = {
    type: 'pattern',
    pattern: 'solid',
    fgColor: { argb: 'FF0F2744' },
  };
  detailSheet.getRow(1).height = 24;

  detailSheet.getRow(2).values = [
    'Generated',
    new Date(summary.createdAt).toLocaleString(),
    '',
    '',
    '',
    '',
    '',
    '',
    '',
  ];
  detailSheet.getRow(2).font = { italic: true, color: { argb: 'FF334155' } };

  const columnHeader = detailSheet.getRow(3);
  columnHeader.values = [
    'Project',
    'PO',
    'Invoice File',
    'SKU',
    'Product Name',
    'DB Price',
    'Invoice Price',
    'Difference',
    'Source Line',
  ];
  columnHeader.font = { bold: true, color: { argb: 'FFFFFFFF' } };
  columnHeader.fill = {
    type: 'pattern',
    pattern: 'solid',
    fgColor: { argb: 'FF1F3A5F' },
  };
  columnHeader.alignment = { vertical: 'middle', horizontal: 'left' };
  detailSheet.views = [{ state: 'frozen', ySplit: 3 }];
  detailSheet.autoFilter = 'A3:I3';
  detailSheet.pageSetup = {
    orientation: 'landscape',
    fitToPage: true,
    fitToWidth: 1,
    fitToHeight: 0,
    horizontalCentered: true,
    margins: {
      left: 0.3,
      right: 0.3,
      top: 0.4,
      bottom: 0.4,
      header: 0.2,
      footer: 0.2,
    },
  };

  if (!grouped.length) {
    detailSheet.addRow({});
    detailSheet.addRow({
      project: 'No flagged items found.',
      po: '',
      invoiceFile: '',
      sku: '',
      productName: '',
      expectedPrice: '',
      observedPrice: '',
      difference: '',
      sourceLine: '',
    });
  } else {
    detailSheet.addRow({});
    for (const group of grouped) {
      for (const invoice of group.invoices) {
        for (const item of invoice.flaggedItems) {
          detailSheet.addRow({
            project: group.project,
            po: group.po,
            invoiceFile: invoice.file,
            sku: item.sku || '',
            productName: item.productName || '',
            expectedPrice: item.expectedPrice,
            observedPrice: item.observedPrice,
            difference: item.difference,
            sourceLine: item.sourceLine || '',
          });
        }
      }
    }
  }

  detailSheet.eachRow((row, rowNumber) => {
    row.alignment = { vertical: 'top', wrapText: true };
    if (rowNumber > 3) {
      row.getCell('F').numFmt = '$#,##0.00';
      row.getCell('G').numFmt = '$#,##0.00';
      row.getCell('H').numFmt = '$#,##0.00;[Red]-$#,##0.00';
      if (rowNumber % 2 === 0) {
        row.fill = {
          type: 'pattern',
          pattern: 'solid',
          fgColor: { argb: 'FFF4F7FC' },
        };
      }
      row.eachCell((cell) => {
        cell.border = {
          top: { style: 'thin', color: { argb: 'FFE3E8F1' } },
          left: { style: 'thin', color: { argb: 'FFE3E8F1' } },
          bottom: { style: 'thin', color: { argb: 'FFE3E8F1' } },
          right: { style: 'thin', color: { argb: 'FFE3E8F1' } },
        };
      });
      const diffValue = Number(row.getCell('H').value || 0);
      if (Number.isFinite(diffValue) && Math.abs(diffValue) >= 10) {
        row.getCell('H').fill = {
          type: 'pattern',
          pattern: 'solid',
          fgColor: { argb: 'FFFEE2E2' },
        };
        row.getCell('H').font = { bold: true, color: { argb: 'FF991B1B' } };
      }
    }
  });

  await workbook.xlsx.writeFile(outPath);
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    printHelp();
    return;
  }
  const invoiceDir = path.resolve(args.invoices);
  const outDir = path.resolve(args.output);
  const explicitFiles = args.files.map((filePath) => path.resolve(filePath));
  const dbPath = args.db ? path.resolve(args.db) : null;

  if (!explicitFiles.length && !fs.existsSync(invoiceDir)) {
    throw new Error(`Invoice directory not found: ${invoiceDir}`);
  }
  if (!args.extractOnly && (!dbPath || !fs.existsSync(dbPath))) {
    throw new Error(`Database file not found: ${dbPath}`);
  }
  if (!Number.isFinite(args.tolerance) || args.tolerance < 0) {
    throw new Error('Tolerance must be a non-negative number.');
  }

  ensureDir(outDir);
  const files = explicitFiles.length
    ? explicitFiles.filter((filePath) => fs.existsSync(filePath))
    : walkFiles(invoiceDir);
  if (!files.length) {
    console.log('No supported invoice files found.');
    return;
  }

  const products = args.extractOnly
    ? []
    : buildProductMatchers(loadDatabase(dbPath));
  const invoiceResults = [];

  console.log(`Found ${files.length} invoice files.`);
  for (const filePath of files) {
    console.log(`Processing ${path.basename(filePath)}...`);
    const text = await extractText(filePath);
    const { project, po } = extractProjectAndPo(text);
    const parsedItems = parseInvoiceLineItems(text);
    const flaggedItems = args.extractOnly
      ? []
      : findLineItemsAndMismatches(text, products, args.tolerance, filePath);
    invoiceResults.push({
      file: path.relative(process.cwd(), filePath),
      project,
      po,
      parsedItems,
      flaggedItems,
    });
  }

  if (sharedWorker) {
    await sharedWorker.terminate();
  }

  const grouped = groupResults(invoiceResults).filter((g) =>
    args.extractOnly ? true : g.flaggedCount > 0
  );
  const summary = {
    scannedInvoices: invoiceResults.length,
    flaggedGroups: grouped.length,
    totalFlaggedItems: grouped.reduce((acc, g) => acc + g.flaggedCount, 0),
    extractOnly: args.extractOnly,
    createdAt: new Date().toISOString(),
  };

  const rawResultPath = path.join(outDir, 'invoice-review-results.json');
  const groupedPath = path.join(outDir, 'flagged-by-project-or-po.json');
  const candidateDbPath = path.join(outDir, 'candidate-product-prices.json');
  const pdfPath = path.join(outDir, 'flagged-items-by-project-or-po.pdf');
  const xlsxPath = path.join(outDir, 'flagged-items-by-project-or-po.xlsx');
  fs.writeFileSync(rawResultPath, JSON.stringify(invoiceResults, null, 2));
  fs.writeFileSync(groupedPath, JSON.stringify({ summary, grouped }, null, 2));
  fs.writeFileSync(
    candidateDbPath,
    JSON.stringify(buildCandidateProducts(invoiceResults), null, 2)
  );
  if (!args.extractOnly) {
    await writePdfReport(grouped, pdfPath);
    await writeXlsxReport(grouped, summary, xlsxPath);
  }

  console.log('\nReview complete.');
  console.log(`Scanned invoices: ${summary.scannedInvoices}`);
  console.log(`Flagged groups: ${summary.flaggedGroups}`);
  console.log(`Flagged items: ${summary.totalFlaggedItems}`);
  console.log(`JSON (raw): ${rawResultPath}`);
  console.log(`JSON (grouped): ${groupedPath}`);
  console.log(`JSON (candidate DB): ${candidateDbPath}`);
  if (args.extractOnly) {
    console.log('PDF report skipped in --extract-only mode.');
  } else {
    console.log(`PDF report: ${pdfPath}`);
    console.log(`XLSX report: ${xlsxPath}`);
  }
}

main().catch(async (err) => {
  if (sharedWorker) await sharedWorker.terminate();
  console.error(`Invoice review failed: ${err?.message || err}`);
  process.exit(1);
});
