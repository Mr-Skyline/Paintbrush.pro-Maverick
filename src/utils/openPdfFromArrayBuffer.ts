import * as pdfjsLib from 'pdfjs-dist';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import pdfWorker from 'pdfjs-dist/build/pdf.worker.mjs?url';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker;

/**
 * Open a PDF in pdf.js without detaching the caller's ArrayBuffer.
 * pdf.js can transfer the underlying buffer to a worker; a copy keeps React state
 * and IndexedDB-backed buffers valid for Boost, re-renders, and second opens.
 */
export async function openPdfFromArrayBuffer(
  data: ArrayBuffer
): Promise<PDFDocumentProxy> {
  const bytes = new Uint8Array(data.slice(0));
  return pdfjsLib.getDocument({ data: bytes }).promise;
}
