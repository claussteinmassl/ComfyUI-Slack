import { app } from "../../scripts/app.js";

// user_id is only ever set by the Slack listener (it injects the triggering
// user id into the API graph at runtime). It's useless — and easy to mis-fill —
// when a human drives the node, so we hide its widget in the editor. The input
// stays declared on the node, so the listener's injection keeps working
// untouched; we only collapse the widget so it isn't drawn or editable, while
// preserving its (empty) value.
//
// thread_ts is intentionally NOT hidden: it's a connectable socket (forceInput)
// so a Slack Thread Start node can be wired into it to group send nodes in one
// thread. The listener still injects it as a literal value all the same.
const TARGET = new Set([
    "SlackSendImage",
    "SlackSendVideo",
    "SlackSendText",
    "SlackSendAudio",
]);
const HIDE = ["user_id"];

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
