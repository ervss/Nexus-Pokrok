// Background service worker
// Currently not heavily used as we moved logic to popup.js for direct user interaction
// But kept for future context menu expansion

chrome.runtime.onInstalled.addListener(() => {
    console.log("Nexus Quantum Bridge Installed");
});
