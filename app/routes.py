import math

from flask import Blueprint, jsonify, request, render_template

from app.config import DEFAULT_NODE_ID
from app.database import (
    get_capabilities,
    get_node_capabilities,
    get_node_details,
    get_nodes_overview,
    get_node_status,
    get_nodes,
    get_recent_measurements,
    save_measurements,
    replace_expected_capabilities,
    update_node_registry,
)


routes = Blueprint("routes", __name__)


@routes.route("/")
def home():
    return render_template("index.html")


@routes.route("/nodes")
def nodes_page():
    return render_template("nodes.html")


@routes.route("/nodes/<node_id>")
def node_details_page(node_id):
    if get_node_details(node_id) is None:
        return render_template("node_details.html", node_id=node_id), 404
    return render_template("node_details.html", node_id=node_id)


@routes.route("/api/data", methods=["POST"])
def receive_data():
    data = request.get_json()

    if not data:
        return jsonify({"error": "Missing JSON payload"}), 400

    node_id = data.get("node_id")
    readings = data.get("readings")

    if not node_id:
        return jsonify({"error": "Missing node_id"}), 400

    if not readings or not isinstance(readings, dict):
        return jsonify({"error": "Missing or invalid readings object"}), 400

    try:
        saved = save_measurements(node_id, readings)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except Exception as error:
        return jsonify({"error": "Server error", "details": str(error)}), 500

    return jsonify({
        "status": "saved",
        "node_id": node_id,
        "saved": saved
    })


@routes.route("/api/readings")
def readings():
    node_id = request.args.get("node_id", DEFAULT_NODE_ID)
    return jsonify(get_recent_measurements(node_id=node_id))


@routes.route("/api/nodes")
def nodes():
    return jsonify(get_nodes())


@routes.route("/api/nodes/overview")
def nodes_overview():
    return jsonify(get_nodes_overview())


@routes.route("/api/capabilities")
def capabilities():
    return jsonify(get_capabilities())


@routes.route("/api/nodes/<node_id>/capabilities", methods=["PUT"])
def node_capabilities(node_id):
    if get_node_capabilities(node_id) is None:
        return jsonify({"error": "Node not found", "node_id": node_id}), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"expected"}:
        return jsonify({"error": "Request must contain only a complete expected set"}), 400
    expected = payload["expected"]
    if not isinstance(expected, list) or any(not isinstance(key, str) for key in expected):
        return jsonify({"error": "expected must be a list of capability keys"}), 400
    try:
        replace_expected_capabilities(node_id, expected)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    return jsonify(get_node_capabilities(node_id))


REGISTRY_FIELDS = {"name", "location", "category", "latitude", "longitude", "enabled"}


def validate_registry_update(payload):
    if not isinstance(payload, dict) or not payload:
        raise ValueError("Request body must be a non-empty JSON object")

    unsupported = set(payload) - REGISTRY_FIELDS
    if unsupported:
        raise ValueError(f"Unsupported field(s): {', '.join(sorted(unsupported))}")

    values = {}
    for field, value in payload.items():
        if field == "name":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("name must be a non-empty string")
            values[field] = value.strip()
        elif field in {"location", "category"}:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{field} must be a string or null")
            values[field] = value.strip() or None if isinstance(value, str) else None
        elif field in {"latitude", "longitude"}:
            if isinstance(value, bool) or (
                value is not None and not isinstance(value, (int, float))
            ):
                raise ValueError(f"{field} must be a finite number or null")
            if value is not None:
                if not math.isfinite(value):
                    raise ValueError(f"{field} must be a finite number or null")
                limit = 90 if field == "latitude" else 180
                if not -limit <= value <= limit:
                    raise ValueError(f"{field} must be between {-limit} and {limit}")
            values[field] = value
        elif field == "enabled":
            if not isinstance(value, bool):
                raise ValueError("enabled must be a boolean")
            values[field] = value
    return values


@routes.route("/api/nodes/<node_id>", methods=["GET", "PATCH"])
def node_details(node_id):
    details = get_node_details(node_id)
    if details is None:
        return jsonify({"error": "Node not found", "node_id": node_id}), 404

    if request.method == "PATCH":
        try:
            values = validate_registry_update(request.get_json(silent=True))
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        update_node_registry(node_id, values)
        details = get_node_details(node_id)
    return jsonify(details)


@routes.route("/api/node-status")
def node_status():
    node_id = request.args.get("node_id", DEFAULT_NODE_ID)
    return jsonify(get_node_status(node_id=node_id))
