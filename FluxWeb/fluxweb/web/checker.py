"""Plan-JSON validator.

This is an internal admin tool. It was previously an unauthenticated endpoint
that read an entire uploaded file into memory and parsed it, which made it a
free denial-of-service lever (audit H-17, L-45).
"""

from __future__ import annotations

import json

from flask import Blueprint, flash, render_template, request

from fluxweb.web.helpers import admin_required

bp = Blueprint("checker", __name__)

MAX_UPLOAD_BYTES = 512 * 1024

REQUIRED_TYPES = {
    "price": (int, float),
    "memory": int,
    "cpu": int,
    "disk": int,
    "egg_id": int,
    "features": list,
}


@bp.route("/checker", methods=["GET", "POST"])
@admin_required
def check_plans_json():
    results = None

    if request.method == "POST":
        file = request.files.get("plans_file")
        if not file or not file.filename:
            flash("No file selected.", "error")
            return render_template("checker.html", results=None)

        raw = file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            flash(f"File is too large (limit {MAX_UPLOAD_BYTES // 1024} KB).", "error")
            return render_template("checker.html", results=None)

        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            flash(f"Invalid JSON file: {exc}", "error")
            return render_template("checker.html", results=None)

        if not isinstance(data, list):
            flash("JSON root must be an array (list) of plan objects.", "error")
            return render_template("checker.html", results=None)

        results = []
        for index, item in enumerate(data):
            errors: list[str] = []
            if not isinstance(item, dict):
                errors.append("Item is not a dictionary/object.")
                name = f"Invalid Item (Index {index})"
            else:
                name = item.get("name", f"Unknown Plan (Index {index})")
                if "name" not in item:
                    errors.append("Missing required field: 'name'")
                for field, expected in REQUIRED_TYPES.items():
                    if field in item and not isinstance(item[field], expected):
                        label = (
                            "a number"
                            if field == "price"
                            else ("a list/array" if field == "features" else "an integer")
                        )
                        errors.append(f"'{field}' should be {label}.")

            results.append(
                {
                    "index": index + 1,
                    "name": name,
                    "status": "Pass" if not errors else "Fail",
                    "errors": errors,
                }
            )

    return render_template("checker.html", results=results)
