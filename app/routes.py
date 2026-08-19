import math

from flask import Blueprint, jsonify, request, render_template

from app.config import DEFAULT_NODE_ID
from app.database import (
    create_definition,
    delete_definition,
    get_capabilities,
    get_node_capabilities,
    get_node_details,
    get_nodes_overview,
    get_node_status,
    get_nodes,
    get_node_organization,
    list_definitions,
    mutate_organization,
    get_recent_measurements,
    save_measurements,
    replace_expected_capabilities,
    rename_definition,
    update_node_registry,
)


routes = Blueprint("routes", __name__)


@routes.route("/")
def home():
    return render_template("index.html")


@routes.route("/nodes")
def nodes_page():
    return render_template("nodes.html")


@routes.route("/fleet/organization")
def fleet_organization_page():
    return render_template("fleet_organization.html")


@routes.route("/nodes/<node_id>")
def node_details_page(node_id):
    if get_node_details(node_id) is None:
        return render_template("node_details.html", node_id=node_id), 404
    return render_template("node_details.html", node_id=node_id)


@routes.route("/nodes/<node_id>/technical")
def node_technical_page(node_id):
    if get_node_details(node_id) is None:
        return render_template("node_technical.html", node_id=node_id), 404
    return render_template("node_technical.html", node_id=node_id)


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


def _validated_name_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or set(payload) != {"name"}:
        raise ValueError("Request must contain only name")
    name = payload["name"]
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    return name.strip()


@routes.route("/api/groups", methods=["GET", "POST"])
@routes.route("/api/tags", methods=["GET", "POST"])
def organization_definitions():
    kind = "group" if request.path.endswith("groups") else "tag"
    if request.method == "GET":
        return jsonify(list_definitions(kind))
    try:
        return jsonify(create_definition(kind, _validated_name_payload())), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@routes.route("/api/groups/<int:definition_id>", methods=["PATCH", "DELETE"])
@routes.route("/api/tags/<int:definition_id>", methods=["PATCH", "DELETE"])
def organization_definition(definition_id):
    kind = "group" if "/groups/" in request.path else "tag"
    if request.method == "DELETE":
        if not delete_definition(kind, definition_id):
            return jsonify({"error": f"{kind.title()} not found"}), 404
        return jsonify({"status": "deleted"})
    try:
        updated = rename_definition(kind, definition_id, _validated_name_payload())
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not updated:
        return jsonify({"error": f"{kind.title()} not found"}), 404
    return jsonify(next(item for item in list_definitions(kind) if item["id"] == definition_id))


def _validated_membership_payload(bulk=False):
    payload = request.get_json(silent=True)
    allowed = {"node_ids", "kind", "definition_ids", "operation"} if bulk else {
        "kind", "definition_ids", "operation"
    }
    if not isinstance(payload, dict) or set(payload) != allowed:
        raise ValueError(f"Request must contain only {', '.join(sorted(allowed))}")
    node_ids = payload.get("node_ids") if bulk else None
    definition_ids = payload.get("definition_ids")
    if bulk and (not isinstance(node_ids, list) or not node_ids or
                 any(not isinstance(item, str) or not item for item in node_ids)):
        raise ValueError("node_ids must be a non-empty list of strings")
    if (not isinstance(definition_ids, list) or not definition_ids or
            any(isinstance(item, bool) or not isinstance(item, int) for item in definition_ids)):
        raise ValueError("definition_ids must be a non-empty list of integer IDs")
    if payload.get("kind") not in {"group", "tag"}:
        raise ValueError("kind must be group or tag")
    if payload.get("operation") not in {"add", "remove"}:
        raise ValueError("operation must be add or remove")
    return node_ids, payload["kind"], definition_ids, payload["operation"]


@routes.route("/api/nodes/<node_id>/organization", methods=["GET", "POST"])
def node_organization(node_id):
    organization = get_node_organization(node_id)
    if organization is None:
        return jsonify({"error": "Node not found", "node_id": node_id}), 404
    if request.method == "GET":
        return jsonify(organization)
    try:
        _, kind, definition_ids, operation = _validated_membership_payload()
        mutate_organization([node_id], kind, definition_ids, operation)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify(get_node_organization(node_id))


@routes.route("/api/fleet/organization", methods=["POST"])
def bulk_organization():
    try:
        node_ids, kind, definition_ids, operation = _validated_membership_payload(bulk=True)
        mutate_organization(node_ids, kind, definition_ids, operation)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except LookupError as error:
        return jsonify({"error": str(error)}), 404
    return jsonify({"status": "updated", "node_ids": node_ids})


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
