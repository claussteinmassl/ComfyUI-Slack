import { app } from "../../scripts/app.js";

// thread_ts and user_id are only ever set by the Slack listener (it injects the
// real thread timestamp + triggering user id into the API graph at runtime).
// They're useless — and easy to mis-fill — when a human drives the node, so we
// hide their widgets in the editor. The inputs stay declared on the node, so the
// listener's injection keeps working untouched; we only collapse the widgets so
// they aren't drawn or editable, while preserving their (empty) value.
const TARGET = new Set(["SlackSendImage", "SlackSendVideo"]);
const HIDE = ["thread_ts", "user_id"];

function hideWidget(widget) {
    if (!widget || widget.type === "hidden-slack") return;
    widget.origType = widget.type;
    widget.origComputeSize = widget.computeSize;
    widget.origSerializeValue = widget.serializeValue;
    // Collapse to zero height (-4 cancels the inter-widget margin) and stop it
    // being drawn/edited; keep serializing the real value so nothing is lost.
    widget.computeSize = () => [0, -4];
    widget.serializeValue = () =>
        widget.origSerializeValue ? widget.origSerializeValue() : widget.value;
    widget.type = "hidden-slack";
}

app.registerExtension({
    name: "comfyui-slack.hide_listener_fields",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!TARGET.has(nodeData.name)) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            orig?.apply(this, arguments);
            for (const name of HIDE) {
                hideWidget(this.widgets?.find((w) => w.name === name));
            }
            // Recompute size now that those widgets take no space.
            if (this.computeSize) this.setSize(this.computeSize());
        };
    },
});
