import { contextBridge } from 'electron';
contextBridge.exposeInMainWorld('electronAPI', {
  BoxManage_start: () => {},
  CalibrationTask_run: () => {},
});
