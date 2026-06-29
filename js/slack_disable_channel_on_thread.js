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
    if (!channel) return;
    const disabled = threadConnected(node);
    // Two widget render paths read two different flags: canvas (litegraph)
    // widgets honour widget.disabled, Vue/DOM widgets honour
    // widget.options.disabled. Set both so the field greys out regardless.
    channel.disabled = disabled;
    channel.options = channel.options || {};
    channel.options.disabled = disabled;
    node.setDirtyCanvas?.(true, true);
}

app.registerExtension({
    name: "comfyui-slack.disable_channel_on_thread",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET.has(nodeData.name)) return;

        const origCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            origCreated?.apply(this, arguments);

            // Chain the connection watcher onto the instance: ComfyUI installs
            // its own instance-level onConnectionsChange, so an instance chain is
            // the reliable place to react (a prototype override can be shadowed).
            const instConn = this.onConnectionsChange;
            this.onConnectionsChange = function () {
                const r = instConn?.apply(this, arguments);
                refreshChannel(this);
                return r;
            };

            refreshChannel(this);
        };
    },

    // Links are restored after node creation when loading a saved graph; sync
    // every target node once the graph is fully configured.
    afterConfigureGraph() {
        for (const node of app.graph?._nodes || []) {
            if (TARGET.has(node.comfyClass)) refreshChannel(node);
        }
    },
});
