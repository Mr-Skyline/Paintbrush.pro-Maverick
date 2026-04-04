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
  listDisplays: () => ipcRenderer.invoke('window:listDisplays'),
  getMonitorPreference: () => ipcRenderer.invoke('window:getMonitorPreference'),
  setMonitorPreference: (preference) =>
    ipcRenderer.invoke('window:setMonitorPreference', preference),
  sendWallControl: (message) => ipcRenderer.invoke('wall:control', message),
  onWallControl: (handler) => {
    const listener = (_event, payload) => handler(payload);
    ipcRenderer.on('wall:control', listener);
    return () => ipcRenderer.removeListener('wall:control', listener);
  },
});
