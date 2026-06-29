import { app } from "../../scripts/app.js";

// When a Slack Thread Start node is wired into a send node's thread_ts input,
// the thread already fixes the destination channel — so the node's own channel
// field is redundant (and the Python side ignores it, recovering the channel
// from the thread reference). Grey the channel widget out while thread_ts is
// connected so it can't be edited or mistaken for the real destination, and
// re-enable it the moment the link is removed.
const TARGET = new Set([
    "SlackSendImage",
    "SlackSendVideo",
    "SlackSendText",
    "SlackSendAudio",
]);

function threadConnected(node) {
    const input = node.inputs?.find((i) => i.name === "thread_ts");
    return !!(input && input.link != null);
}

function refreshChannel(node) {
    const channel = node.widgets?.find((w) => w.name === "channel");
    if (channel) channel.disabled = threadConnected(node);
}

app.registerExtension({
    name: "comfyui-slack.disable_channel_on_thread",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET.has(nodeData.name)) return;

        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origCreated?.apply(this, arguments);
            refreshChannel(this);
        };

        // Fires on every connect/disconnect (including link restoration on graph
        // load); re-reads the current link state, so we don't filter by slot.
        const origConn = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const r = origConn?.apply(this, arguments);
            refreshChannel(this);
            return r;
        };
    },
});
