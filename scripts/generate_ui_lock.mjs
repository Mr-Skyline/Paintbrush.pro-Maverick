#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.cwd();
const LOCK_PATH = path.join(ROOT, 'scripts', 'ui_lock.json');

const UI_FILES = [
  'src/index.css',
  'src/components/WorkspaceLayout.tsx',
  'src/components/TraceWindow.tsx',
  'src/components/AgentTracePanel.tsx',
  'src/components/TraceViewerPanel.tsx',
  'src/components/ReviewPanel.tsx',
  'src/components/ToolbarOST.tsx',
  'src/components/CanvasWorkspace.tsx',
  'src/components/RightSidebarProperties.tsx',
  'src/components/BoostDialog.tsx',
  'src/components/StatusBar.tsx',
  'src/components/VoiceControls.tsx',
  'src/components/SidebarLeft.tsx',
  'src/components/ConditionEditorModal.tsx',
  'src/screens/NewProjectScreen.tsx',
  'src/screens/DesktopInvoiceScreen.tsx',
  'src/screens/ProjectListScreen.tsx',
];

function sha256ForFile(absPath) {
  const buf = fs.readFileSync(absPath);
  return crypto.createHash('sha256').update(buf).digest('hex');
}

function main() {
  const fileHashes = {};
  for (const relPath of UI_FILES) {
    const absPath = path.join(ROOT, relPath);
    if (!fs.existsSync(absPath)) {
      continue;
    }
    fileHashes[relPath] = sha256ForFile(absPath);
  }

  const payload = {
    version: 1,
    generatedAt: new Date().toISOString(),
    note:
      'UI lock baseline. Update intentionally via: npm run ui:lock:update',
    files: fileHashes,
  };

  fs.writeFileSync(LOCK_PATH, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  console.log(`updated_ui_lock ${LOCK_PATH}`);
}

main();
