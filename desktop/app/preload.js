'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('wt', {
  start: (opts) => ipcRenderer.invoke('agent:start', opts),
  stop: () => ipcRenderer.invoke('agent:stop'),
  send: (msg) => ipcRenderer.invoke('agent:send', msg),
  onEvents: (fn) => ipcRenderer.on('agent:events', (_e, evs) => fn(evs)),
  onExit: (fn) => ipcRenderer.on('agent:exit', (_e, info) => fn(info)),
  findCity: (q) => ipcRenderer.invoke('city:find', q),
  readTiles: (offset, length) => ipcRenderer.invoke('tiles:read', offset, length),
  icon: (p) => ipcRenderer.invoke('icon:get', p),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (patch) => ipcRenderer.invoke('settings:set', patch),
  setTheme: (mode) => ipcRenderer.invoke('win:theme', mode),
  info: () => ipcRenderer.invoke('app:info'),
  checkUpdate: () => ipcRenderer.invoke('update:check'),
  saveReport: (o) => ipcRenderer.invoke('report:save', o),
  openReport: (p) => ipcRenderer.invoke('report:open', p),
  showReport: (p) => ipcRenderer.invoke('report:show', p),
  platform: process.platform,
});
