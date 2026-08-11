from flask import Blueprint, jsonify, request, render_template

from app.config import DEFAULT_NODE_ID
from app.database import (
    get_node_details,
    get_node_status,
    get_nodes,
    get_recent_measurements,
    save_measurements,
)


routes = Blueprint("routes", __name__)


@routes.route("/")
def home():
    return render_template("index.html")


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


@routes.route("/api/nodes/<node_id>")
def node_details(node_id):
    details = get_node_details(node_id)
    if details is None:
        return jsonify({"error": "Node not found", "node_id": node_id}), 404
    return jsonify(details)


@routes.route("/api/node-status")
def node_status():
    node_id = request.args.get("node_id", DEFAULT_NODE_ID)
    return jsonify(get_node_status(node_id=node_id))
