"""HTTP transport for HA Maintenance Hub backend services."""

from __future__ import annotations

import json
import mimetypes
import re
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any

try:
    from .errors import ApiError
except ImportError:  # pragma: no cover - direct execution in the app container
    from errors import ApiError


def create_handler(backend: Any) -> type[BaseHTTPRequestHandler]:
    """Bind the transport layer to a backend module with the service functions."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "HaMaintenanceHub/1.9.0"

        def log_message(self, format_string: str, *args: Any) -> None:
            print(f"{self.address_string()} - {format_string % args}", flush=True)

        def send_bytes(
            self,
            status: int,
            body: bytes,
            content_type: str,
            extra_headers: dict[str, str] | None = None,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; script-src 'self'",
            )
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, value: Any) -> None:
            self.send_bytes(
                status,
                backend.json_bytes(value),
                "application/json; charset=utf-8",
            )

        def read_json(self, max_size: int | None = None) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Ungueltige Anfragegroesse.") from exc
            if length > (max_size or backend.MAX_FILE_SIZE + 16_384):
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Die Anfrage ist zu gross.")
            try:
                value = json.loads(self.rfile.read(length) or b"{}")
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "Ungueltiges JSON.") from exc
            if not isinstance(value, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "Ein JSON-Objekt wird erwartet.")
            return value

        def route(self) -> tuple[str, dict[str, list[str]]]:
            parsed = urllib.parse.urlsplit(self.path)
            return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

        def do_GET(self) -> None:  # noqa: N802
            try:
                path, query = self.route()
                if path == "/health":
                    self.send_json(HTTPStatus.OK, {"status": "ok"})
                elif path == "/api/files":
                    self.send_json(HTTPStatus.OK, backend.list_files())
                elif path == "/api/file":
                    self.send_json(HTTPStatus.OK, backend.read_file(query.get("path", [""])[0]))
                elif path == "/api/configuration":
                    self.send_json(HTTPStatus.OK, backend.read_configuration())
                elif path == "/api/backups":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.backup_history(
                            query.get("scope", [""])[0],
                            query.get("path", [""])[0],
                        ),
                    )
                elif path == "/api/backups/overview":
                    self.send_json(HTTPStatus.OK, backend.backup_overview())
                elif path == "/api/backups/integrity":
                    self.send_json(HTTPStatus.OK, backend.backup_integrity())
                elif path == "/api/backup/diff":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.backup_diff(
                            query.get("scope", [""])[0],
                            query.get("path", [""])[0],
                            query.get("id", [""])[0],
                        ),
                    )
                elif path == "/api/git/history":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.git_history(
                            query.get("scope", [""])[0],
                            query.get("path", [""])[0],
                        ),
                    )
                elif path == "/api/git/diff":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.git_diff(
                            query.get("scope", [""])[0],
                            query.get("path", [""])[0],
                            query.get("commit", [""])[0],
                        ),
                    )
                elif path == "/api/git/branches":
                    self.send_json(HTTPStatus.OK, backend.git_branches())
                elif path == "/api/package-conflicts":
                    self.send_json(HTTPStatus.OK, backend.package_conflict_analysis())
                elif path == "/api/dependencies":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.script_dependency_analysis(query.get("path", [""])[0]),
                    )
                elif path == "/api/ha-objects":
                    self.send_json(HTTPStatus.OK, backend.home_assistant_objects())
                elif path == "/api/blueprints":
                    self.send_json(HTTPStatus.OK, backend.list_blueprints())
                elif path == "/api/blueprint":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.read_blueprint(query.get("path", [""])[0]),
                    )
                elif path == "/api/documentation":
                    self.send_json(HTTPStatus.OK, backend.documentation_overview())
                elif path == "/api/security":
                    self.send_json(HTTPStatus.OK, backend.security_scan())
                elif path == "/api/lint":
                    self.send_json(HTTPStatus.OK, backend.lint_scan())
                elif path == "/api/compatibility":
                    self.send_json(HTTPStatus.OK, backend.compatibility_scan())
                elif path == "/api/graph":
                    self.send_json(HTTPStatus.OK, backend.global_graph())
                elif path == "/api/security/push-warning":
                    self.send_json(HTTPStatus.OK, backend.security_push_warning())
                elif path == "/api/secrets":
                    self.send_json(HTTPStatus.OK, backend.secrets_overview())
                elif path == "/api/preflight":
                    self.send_json(HTTPStatus.OK, backend.preflight())
                elif path == "/api/maintenance/status":
                    self.send_json(HTTPStatus.OK, backend.maintenance_status())
                elif path == "/api/maintenance/history":
                    self.send_json(HTTPStatus.OK, backend.maintenance_history())
                elif path == "/api/entity-health":
                    self.send_json(HTTPStatus.OK, backend.entity_health())
                elif path == "/api/database":
                    self.send_json(HTTPStatus.OK, backend.database_overview())
                elif path == "/api/database/health":
                    self.send_json(HTTPStatus.OK, backend.database_health())
                elif path == "/api/database/entities":
                    self.send_json(HTTPStatus.OK, backend.database_entities())
                elif path == "/api/database/statistics":
                    self.send_json(HTTPStatus.OK, backend.database_statistics())
                elif path == "/api/database/yaml-compare":
                    self.send_json(HTTPStatus.OK, backend.database_yaml_compare())
                elif path == "/api/traces":
                    self.send_json(HTTPStatus.OK, backend.trace_index())
                elif path == "/api/trace":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.trace_detail(
                            query.get("domain", [""])[0],
                            query.get("itemId", [""])[0],
                            query.get("runId", [""])[0],
                        ),
                    )
                elif path == "/api/resource":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.read_resource(query.get("path", [""])[0]),
                    )
                elif path == "/api/dashboard":
                    self.send_json(HTTPStatus.OK, backend.configuration_quality_dashboard())
                elif path == "/api/system/health":
                    self.send_json(HTTPStatus.OK, backend.system_health())
                elif path == "/api/settings":
                    self.send_json(HTTPStatus.OK, backend.load_settings())
                elif path == "/api/trash":
                    self.send_json(HTTPStatus.OK, backend.trash_history())
                elif path == "/api/git/remote":
                    self.send_json(HTTPStatus.OK, backend.git_remote_status())
                elif path == "/api/export":
                    filename, archive = backend.export_packages(
                        query.get("scope", ["all"])[0],
                        query.get("path", [""])[0],
                        query.get("category", [""])[0],
                    )
                    self.send_bytes(
                        HTTPStatus.OK,
                        archive,
                        "application/zip",
                        {"Content-Disposition": f'attachment; filename="{filename}"'},
                    )
                elif path == "/api/helpers":
                    self.send_json(HTTPStatus.OK, backend.helper_data())
                elif path.startswith("/static/"):
                    self.serve_static(path.removeprefix("/static/"))
                elif path == "/":
                    self.serve_index()
                else:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
            except ApiError as exc:
                self.send_json(exc.status, {"error": exc.message, **exc.details})
            except Exception as exc:  # pragma: no cover - final request boundary
                print(f"Unhandled error: {exc!r}", flush=True)
                self.send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Interner Serverfehler."})

        def do_POST(self) -> None:  # noqa: N802
            try:
                path, _ = self.route()
                body = self.read_json(
                    backend.import_request_size_limit() if path.startswith("/api/import/") else None
                )
                if path == "/api/files":
                    result = backend.write_file(
                        body.get("path", ""),
                        body.get("content", ""),
                        None,
                        body.get("category", backend.DEFAULT_CATEGORY),
                        create=True,
                        tags=body.get("tags"),
                    )
                    self.send_json(HTTPStatus.CREATED, result)
                elif path == "/api/rename":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.rename_file(
                            body.get("path", ""),
                            body.get("newPath", ""),
                            body.get("version"),
                        ),
                    )
                elif path == "/api/validate":
                    self.send_json(HTTPStatus.OK, backend.validate_yaml(body.get("content", "")))
                elif path == "/api/analyze":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.analyze_yaml(body.get("content", ""), body.get("path", "")),
                    )
                elif path == "/api/flow":
                    self.send_json(HTTPStatus.OK, backend.flow_analysis(body))
                elif path == "/api/impact":
                    self.send_json(HTTPStatus.OK, backend.save_impact(body))
                elif path == "/api/review/preview":
                    self.send_json(HTTPStatus.OK, backend.review_preview(body))
                elif path == "/api/review/apply":
                    self.send_json(HTTPStatus.OK, backend.apply_review(body))
                elif path == "/api/dashboard/finding":
                    self.send_json(HTTPStatus.OK, backend.update_dashboard_finding_state(body))
                elif path == "/api/script/rename-preview":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.preview_script_rename(
                            body.get("path", ""),
                            body.get("oldId", ""),
                            body.get("newId", ""),
                        ),
                    )
                elif path == "/api/script/rename":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.rename_script_with_references(
                            body.get("path", ""),
                            body.get("oldId", ""),
                            body.get("newId", ""),
                            body.get("stateVersion", ""),
                        ),
                    )
                elif path == "/api/search-replace/preview":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.search_replace_preview(
                            body.get("search"),
                            body.get("replacement"),
                            body.get("caseSensitive", True),
                        ),
                    )
                elif path == "/api/search-replace/apply":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.apply_search_replace(
                            body.get("search"),
                            body.get("replacement"),
                            body.get("caseSensitive", True),
                            body.get("stateVersion"),
                        ),
                    )
                elif path == "/api/entity-refactor/preview":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.entity_refactor_preview(
                            body.get("oldEntity", ""),
                            body.get("newEntity", ""),
                        ),
                    )
                elif path == "/api/entity-refactor/apply":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.apply_entity_refactor(
                            body.get("oldEntity", ""),
                            body.get("newEntity", ""),
                            body.get("stateVersion"),
                        ),
                    )
                elif path == "/api/refactor/preview":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.refactor_preview(
                            body.get("kind", ""),
                            body.get("oldValue", ""),
                            body.get("newValue", ""),
                        ),
                    )
                elif path == "/api/refactor/apply":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.apply_refactor(
                            body.get("kind", ""),
                            body.get("oldValue", ""),
                            body.get("newValue", ""),
                            body.get("stateVersion"),
                        ),
                    )
                elif path == "/api/template/render":
                    self.send_json(HTTPStatus.OK, backend.render_template(body))
                elif path == "/api/maintenance/run":
                    self.send_json(HTTPStatus.CREATED, backend.run_maintenance(body.get("triggeredBy", "manual")))
                elif path == "/api/database/query":
                    self.send_json(HTTPStatus.OK, backend.database_query(body))
                elif path == "/api/secrets":
                    self.send_json(HTTPStatus.OK, backend.upsert_secret(body))
                elif path == "/api/secrets/convert":
                    self.send_json(HTTPStatus.OK, backend.convert_plaintext_secret(body))
                elif path == "/api/blueprints/import":
                    self.send_json(
                        HTTPStatus.CREATED,
                        backend.import_blueprint(body.get("path", ""), body.get("content", "")),
                    )
                elif path == "/api/blueprints/from-yaml":
                    self.send_json(
                        HTTPStatus.CREATED,
                        backend.create_blueprint_from_yaml(
                            body.get("domain", ""),
                            body.get("name", ""),
                            body.get("content", ""),
                            body.get("path", ""),
                        ),
                    )
                elif path == "/api/blueprints/instantiate":
                    self.send_json(
                        HTTPStatus.CREATED,
                        backend.instantiate_blueprint(
                            body.get("blueprintPath", ""),
                            body.get("packagePath", ""),
                            body.get("objectId", ""),
                            body.get("alias", ""),
                            body.get("inputs"),
                            body.get("inputsText", ""),
                        ),
                    )
                elif path == "/api/documentation/write":
                    self.send_json(HTTPStatus.OK, backend.write_documentation())
                elif path == "/api/configuration/enable-packages":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.enable_packages(body.get("content", ""), body.get("version")),
                    )
                elif path == "/api/configuration/migration-preview":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.configuration_migration_preview(
                            body.get("content", ""),
                            body.get("packageName", "configuration_import"),
                        ),
                    )
                elif path == "/api/configuration/migrate":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.migrate_configuration(
                            body.get("content", ""),
                            body.get("version"),
                            body.get("packageName", "configuration_import"),
                        ),
                    )
                elif path == "/api/configuration/check":
                    self.send_json(HTTPStatus.OK, backend.check_home_assistant_configuration())
                elif path == "/api/backup/restore":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.restore_backup(
                            body.get("scope", ""),
                            body.get("path", ""),
                            body.get("id", ""),
                            body.get("version"),
                        ),
                    )
                elif path == "/api/backups/pin":
                    self.send_json(HTTPStatus.OK, backend.set_backup_pin(body.get("id", ""), body.get("pinned", False)))
                elif path == "/api/backups/snapshot":
                    self.send_json(HTTPStatus.CREATED, backend.create_backup_snapshot(body))
                elif path == "/api/backups/snapshot/restore-preview":
                    self.send_json(HTTPStatus.OK, backend.snapshot_restore_preview(body.get("id", "")))
                elif path == "/api/backups/snapshot/restore":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.restore_snapshot(body.get("id", ""), body.get("stateVersion")),
                    )
                elif path == "/api/backups/database":
                    self.send_json(HTTPStatus.CREATED, backend.create_database_backup())
                elif path == "/api/trash/restore":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.restore_trash_file(
                            body.get("id", ""),
                            body.get("path", ""),
                            body.get("overwrite", False),
                            body.get("version"),
                        ),
                    )
                elif path == "/api/git/restore":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.restore_git_version(
                            body.get("scope", ""),
                            body.get("path", ""),
                            body.get("commit", ""),
                            body.get("version"),
                        ),
                    )
                elif path == "/api/git/branches/create":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.create_git_branch(body.get("branch", "")),
                    )
                elif path == "/api/git/branches/switch":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.switch_git_branch(body.get("branch", "")),
                    )
                elif path == "/api/git/branches/compare":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.branch_merge_preview(body.get("branch", "")),
                    )
                elif path == "/api/git/branches/merge":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.merge_git_branch(
                            body.get("branch", ""), body.get("stateVersion")
                        ),
                    )
                elif path == "/api/git/remote/sync":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.synchronize_git_remote(body.get("action", "sync")),
                    )
                elif path == "/api/import/preview":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.preview_package_import(body.get("archive")),
                    )
                elif path == "/api/import/apply":
                    self.send_json(
                        HTTPStatus.OK,
                        backend.apply_package_import(
                            body.get("archive"),
                            body.get("strategy", "skip"),
                            body.get("archiveVersion"),
                            body.get("destinationVersion"),
                        ),
                    )
                elif path == "/api/reload":
                    backend.home_assistant_request("services/script/reload", method="POST")
                    self.send_json(HTTPStatus.OK, {"message": "Skripte wurden neu geladen."})
                elif path == "/api/ha-object/run":
                    self.send_json(HTTPStatus.OK, backend.run_home_assistant_object(body))
                else:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
            except ApiError as exc:
                self.send_json(exc.status, {"error": exc.message, **exc.details})

        def do_PUT(self) -> None:  # noqa: N802
            try:
                path, _ = self.route()
                body = self.read_json()
                if path == "/api/file":
                    result = backend.write_file(
                        body.get("path", ""),
                        body.get("content", ""),
                        body.get("version"),
                        body.get("category", backend.DEFAULT_CATEGORY),
                        create=False,
                        tags=body.get("tags"),
                    )
                elif path == "/api/configuration":
                    result = backend.write_configuration(
                        body.get("content", ""), body.get("version")
                    )
                elif path == "/api/resource":
                    result = backend.write_resource(
                        body.get("path", ""),
                        body.get("content", ""),
                        body.get("version"),
                    )
                elif path == "/api/git/remote":
                    result = backend.update_git_remote(body)
                elif path == "/api/settings":
                    result = backend.update_settings(body)
                else:
                    raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
                self.send_json(HTTPStatus.OK, result)
            except ApiError as exc:
                self.send_json(exc.status, {"error": exc.message, **exc.details})

        def do_DELETE(self) -> None:  # noqa: N802
            try:
                path, _ = self.route()
                if path == "/api/git/remote":
                    self.send_json(HTTPStatus.OK, backend.remove_git_remote())
                    return
                if path == "/api/secrets":
                    body = self.read_json()
                    self.send_json(HTTPStatus.OK, backend.delete_secret(body.get("name", "")))
                    return
                if path == "/api/trash":
                    body = self.read_json()
                    self.send_json(
                        HTTPStatus.OK,
                        backend.purge_trash(body.get("id", ""), body.get("path", "")),
                    )
                    return
                if path == "/api/dashboard/finding":
                    body = self.read_json()
                    self.send_json(HTTPStatus.OK, backend.restore_dashboard_finding_state(body))
                    return
                if path != "/api/file":
                    raise ApiError(HTTPStatus.NOT_FOUND, "Unbekannter Endpunkt.")
                body = self.read_json()
                git_result = backend.delete_file(body.get("path", ""), body.get("version"))
                self.send_json(
                    HTTPStatus.OK,
                    {"message": "Datei wurde in den Papierkorb verschoben.", "git": git_result},
                )
            except ApiError as exc:
                self.send_json(exc.status, {"error": exc.message, **exc.details})

        def serve_index(self) -> None:
            template = (backend.STATIC_ROOT / "index.html").read_text(encoding="utf-8")
            ingress = self.headers.get("X-Ingress-Path", "").rstrip("/")
            if not ingress.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]*", ingress):
                ingress = ""
            html = template.replace("__BASE_PATH__", f"{ingress}/")
            self.send_bytes(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

        def serve_static(self, raw_name: str) -> None:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", raw_name):
                raise ApiError(HTTPStatus.NOT_FOUND, "Datei nicht gefunden.")
            path = backend.STATIC_ROOT / raw_name
            try:
                body = path.read_bytes()
            except FileNotFoundError as exc:
                raise ApiError(HTTPStatus.NOT_FOUND, "Datei nicht gefunden.") from exc
            content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_bytes(HTTPStatus.OK, body, f"{content_type}; charset=utf-8")

    return Handler
