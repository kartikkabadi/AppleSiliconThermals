.pragma library

function boundedText(value, limit) {
    return typeof value === "string" ? value.replace(/[\u0000-\u0008\u000b-\u001f\u007f]/g, "").slice(0, limit) : ""
}
function number(value, low, high) {
    return typeof value === "number" && isFinite(value) && value >= low && value <= high ? value : null
}
function escapeMarkup(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;")
}
function parse(raw) {
    if (typeof raw !== "string" || raw.length > 65536) throw new Error("Invalid telemetry size")
    var data = JSON.parse(raw)
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error("Invalid telemetry object")
    if (typeof data.is_apple_silicon !== "boolean" || (typeof data.has_fan !== "boolean" && !data.error)) throw new Error("Missing hardware state")
    var mode = ["auto", "manual", "unknown"].indexOf(data.mode) >= 0 ? data.mode : "unknown"
    var fans = [], input = Array.isArray(data.fans) ? data.fans.slice(0, 32) : [], indices = ({})
    var completeFans = Array.isArray(data.fans) && data.fans.length <= 32
    for (var i = 0; i < input.length; i++) {
        var fan = input[i]
        if (!fan || typeof fan !== "object") { completeFans = false; continue }
        var index = number(fan.index, 1, 999)
        if (index === null || Math.floor(index) !== index || indices[index]) { completeFans = false; continue }
        indices[index] = true
        fans.push({index: index, label: boundedText(fan.label, 64), rpm: number(fan.rpm, 0, 100000),
            min: number(fan.min, 1, 100000), max: number(fan.max, 1, 100000), target: number(fan.target, 0, 100000)})
    }
    var sensors = ({}), keys = ["nand", "battery", "regulator", "wifi"]
    var sourceSensors = data.sensors && typeof data.sensors === "object" && !Array.isArray(data.sensors) ? data.sensors : ({})
    for (var j = 0; j < keys.length; j++) sensors[keys[j]] = number(sourceSensors[keys[j]], -100, 250)
    var warnings = Array.isArray(data.warnings) ? data.warnings.slice(0, 8).map(function(value) { return boundedText(value, 160) }).filter(function(value) { return value !== "" }) : []
    var min = number(data.fan_min, 1000, 7999), max = number(data.fan_max, 1000, 7999)
    var error = boundedText(data.error, 80)
    return {isAppleSilicon: data.is_apple_silicon === true, hasFan: data.has_fan === true,
        deviceModel: boundedText(data.device_model, 128), fans: fans, fanCount: fans.length,
        fanRpm: number(data.fan_rpm, 0, 100000), fanTarget: number(data.fan_target, 0, 100000),
        fanMin: min, fanMax: max, mode: mode, sensors: sensors,
        maxTemp: number(data.max_temp, -100, 250), powerWatts: number(data.power_watts, 0, 100000),
        error: error, errorMessage: boundedText(data.error_message, 240),
        warnings: warnings,
        controlError: boundedText(data.control_error, 240),
        generation: /^[0-9a-f]{32}$/.test(data.broker_generation) ? data.broker_generation : "",
        leaseOwned: data.lease_owned === true,
        controlAvailable: data.control_available === true,
        controlEnabled: !error && completeFans && data.control_available === true && data.has_fan === true && data.fan_control_enabled === true && fans.length > 0 && min !== null && max !== null && min <= max
            && fans.every(function(fan) { return fan.min !== null && fan.max !== null && fan.min <= fan.max && fan.min >= 1000 && fan.max <= 7999 })}
}
