import { app } from "../../scripts/app.js";

// On every Slack send node, the local-save widgets (save_output + the two that
// configure it) are pushed to the bottom so they read as one trailing group,
// and greyed out when they don't apply: save_location/output_folder only matter
// when "Save output" is on, and output_folder only in "Absolute path" mode.
const TARGET = new Set(["SlackSendImage", "SlackSendVideo", "SlackSendText", "SlackSendAudio"]);
const SAVE_WIDGETS = ["save_output", "save_location", "output_folder"];

function moveToEnd(node, names) {
    if (!node.widgets) return;
    const moved = [];
    for (const n of names) {
        const i = node.widgets.findIndex((w) => w.name === n);
        if (i !== -1) moved.push(node.widgets.splice(i, 1)[0]);
    }
    node.widgets.push(...moved);  // re-appended in `names` order
}

app.registerExtension({
    name: "comfyui-slack.save_output",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET.has(nodeData.name)) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            orig?.apply(this, arguments);

            // Make the save group the last widgets on the node.
            moveToEnd(this, SAVE_WIDGETS);

            const find = (n) => this.widgets?.find((w) => w.name === n);
            const save = find("save_output");
            const loc = find("save_location");
            const folder = find("output_folder");
            if (!save || !loc || !folder) return;

            const refresh = () => {
                const on = !!save.value;
                loc.disabled = !on;
                folder.disabled = !on || loc.value !== "Absolute path";
            };
            for (const w of [save, loc]) {
                const cb = w.callback;
                w.callback = function () {
                    const r = cb?.apply(this, arguments);
                    refresh();
                    return r;
                };
            }
            refresh();
        };
    },
});
