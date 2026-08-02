// 跨模块共享的可变状态与本地存储键。
//
// 用一个可变对象而不是导出 let：ES 模块的导入绑定是只读的，
// 导出对象的属性才能被各模块直接赋值。

export const STORAGE_KEY = 'robin_viewer_key';
export const WATER_KEY = 'robin_water_key';

export const state = {
    currentTab: 'environment',
    currentHistType: '24h',
    currentDevice: 'main',
    availableNodes: {},
    // 相机拍摄期间禁止切灯，避免与补光冲突
    isCameraSyncing: false,
    isHDSyncing: false,
};

export const getViewerKey = () => localStorage.getItem(STORAGE_KEY) || '';
export const getWaterKey = () => localStorage.getItem(WATER_KEY);
