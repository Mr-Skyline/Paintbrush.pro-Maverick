interface DesktopInvoiceRunOptions {
  files: string[];
  dbPath: string;
  outDir: string;
  tolerance: number;
  extractOnly: boolean;
}

interface DesktopInvoiceRunResult {
  ok: boolean;
  exitCode: number;
  stdout: string;
  stderr: string;
}

interface DesktopProductRecord {
  sku: string;
  name: string;
  unitPrice: number;
  aliases: string[];
}

interface DesktopDbReadResult {
  ok: boolean;
  error?: string;
  products?: DesktopProductRecord[];
}

interface DesktopDbWriteResult {
  ok: boolean;
  cancelled?: boolean;
  error?: string;
  products?: DesktopProductRecord[];
}

interface DesktopDbCreateResult {
  ok: boolean;
  error?: string;
  dbPath?: string;
  products?: DesktopProductRecord[];
}

interface DesktopInvoiceResultsPayload {
  raw: unknown;
  grouped: unknown;
  candidateDb: unknown;
  files: {
    raw: string;
    grouped: string;
    candidateDb: string;
    pdf: string;
    xlsx: string;
  };
}

interface DesktopDisplayInfo {
  id: number;
  isPrimary: boolean;
  label: string;
  bounds: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

type DesktopMonitorPreference = 'primary' | 'secondary' | `id:${number}` | `index:${number}`;

interface DesktopMonitorPreferenceResult {
  ok: boolean;
  error?: string;
  monitorPreference?: string;
  appliedDisplay?: {
    id: number;
    bounds: {
      x: number;
      y: number;
      width: number;
      height: number;
    };
  } | null;
}

interface DesktopApi {
  pickInvoiceFiles: () => Promise<string[]>;
  pickDbFile: () => Promise<string | null>;
  pickDbCreatePath: () => Promise<string | null>;
  pickOutputDirectory: () => Promise<string | null>;
  runReview: (options: DesktopInvoiceRunOptions) => Promise<DesktopInvoiceRunResult>;
  readDb: (dbPath: string) => Promise<DesktopDbReadResult>;
  writeDb: (dbPath: string, products: DesktopProductRecord[]) => Promise<DesktopDbWriteResult>;
  writeDbAuto: (dbPath: string, products: DesktopProductRecord[]) => Promise<DesktopDbWriteResult>;
  createDb: (
    dbPath: string,
    initialProducts: DesktopProductRecord[]
  ) => Promise<DesktopDbCreateResult>;
  getResults: (outDir: string) => Promise<DesktopInvoiceResultsPayload>;
  openPath: (targetPath: string) => Promise<boolean>;
  listDisplays: () => Promise<DesktopDisplayInfo[]>;
  getMonitorPreference: () => Promise<string>;
  setMonitorPreference: (
    preference: DesktopMonitorPreference
  ) => Promise<DesktopMonitorPreferenceResult>;
  sendWallControl: (message: {
    source?: string;
    type?: string;
    value?: unknown;
  }) => Promise<{ ok: boolean; error?: string }>;
  onWallControl: (
    handler: (payload: { source?: string; type?: string; value?: unknown }) => void
  ) => () => void;
}

interface Window {
  desktopApi?: DesktopApi;
}
