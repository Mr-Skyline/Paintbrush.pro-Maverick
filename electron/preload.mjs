import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('desktopApi', {
  pickInvoiceFiles: () => ipcRenderer.invoke('invoice:pickFiles'),
  pickDbFile: () => ipcRenderer.invoke('invoice:pickDb'),
  pickDbCreatePath: () => ipcRenderer.invoke('invoice:pickDbCreatePath'),
  pickOutputDirectory: () => ipcRenderer.invoke('invoice:pickOutput'),
  runReview: (options) => ipcRenderer.invoke('invoice:run', options),
  readDb: (dbPath) => ipcRenderer.invoke('invoice:readDb', dbPath),
  writeDb: (dbPath, products) =>
    ipcRenderer.invoke('invoice:writeDb', dbPath, products),
  writeDbAuto: (dbPath, products) =>
    ipcRenderer.invoke('invoice:writeDbAuto', dbPath, products),
  createDb: (dbPath, initialProducts) =>
    ipcRenderer.invoke('invoice:createDb', dbPath, initialProducts),
  getResults: (outDir) => ipcRenderer.invoke('invoice:getResults', outDir),
  openPath: (targetPath) => ipcRenderer.invoke('invoice:openPath', targetPath),
  pickTakeoffInput: () => ipcRenderer.invoke('takeoff:pickInput'),
  pickTakeoffOutputDirectory: () => ipcRenderer.invoke('takeoff:pickOutput'),
  runTakeoff: (options) => ipcRenderer.invoke('takeoff:run', options),
});
