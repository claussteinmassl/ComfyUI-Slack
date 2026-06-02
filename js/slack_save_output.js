import { app } from "../../scripts/app.js";

// On both Slack send nodes, the local-save widgets only matter when "Save
// output" is on, and the absolute base path only when "Absolute path" is the
// chosen location. Grey out the widgets that don't apply so the UI reflects
// what actually takes effect.
const TARGET = new Set(["SlackSendImage", "SlackSendVideo", "SlackSendText", "SlackSendAudio"]);

app.registerExtension({
    name: "comfyui-slack.save_output",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET.has(nodeData.name)) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            orig?.apply(this, arguments);
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
