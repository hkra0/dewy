// 轻量 UI 反馈。无依赖。

/** 让 role="button" 的元素支持 Enter/Space。
 *
 *  原生 <button> 自带这个行为，但摄像头预览是 <img>、照片查看器和补光灯卡片
 *  是 <div>，都只有 onclick。用一个委托到 document 的监听器统一兜住，
 *  连 dashboard.js 每轮重新生成的灯卡片也一并覆盖，无需在渲染处重复绑定。
 *
 *  只认 role="button"：普通 div 加了 onclick 但没声明 role，说明它本来
 *  也没打算被当成控件，不该抢 Enter/Space。 */
export function initKeyboardActivation() {
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        const el = e.target.closest && e.target.closest('[role="button"]');
        if (!el) return;
        e.preventDefault();   // 空格默认是翻页
        el.click();
    });
}

/** 拼进 innerHTML 的文本必须先过这里。
 *
 *  额外指标的标签来自字段名，而字段名可能来自 MQTT 节点上报的 JSON——
 *  那是网络上来的数据，不该被当作可信标记直接插进 DOM。 */
export function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
}

export function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerText = message;
    container.appendChild(toast);
    setTimeout(() => {
        if (toast.parentNode) {
            toast.parentNode.removeChild(toast);
        }
    }, 3000);
}
