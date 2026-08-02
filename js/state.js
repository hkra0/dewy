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

/** 某个节点的硬件能力。由服务端 /api/nodes 算好，前端不再翻原始配置。
 *
 *  水泵/灯的执行器 id 是可配的（auto_water.actuator_id 等），相机也可能
 *  以别的形式声明——这些规则只应存在于服务端一处。节点信息还没取回来时
 *  返回全 false，调用方据此隐藏对应界面。
 */
export function nodeCaps(dev = state.currentDevice) {
    const info = state.availableNodes[dev];
    return (info && info.capabilities) || { camera: false, pump: false, light: false };
}
