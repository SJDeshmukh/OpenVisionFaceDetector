import logging
from flask import jsonify
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

def register_error_handlers(app):
    @app.errorhandler(ValidationError)
    def handle_pydantic_validation_error(e):
        logger.warning(f"Validation error: {e.errors()}")
        return jsonify({
            "error": "Validation Error",
            "details": e.errors(),
            "code": "VALIDATION_ERROR"
        }), 400

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(e):
        logger.error(f"Database error: {str(e)}")
        return jsonify({
            "error": "Database error occurred",
            "code": "DATABASE_ERROR"
        }), 500

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({
            "error": "Resource not found",
            "code": "NOT_FOUND"
        }), 404

    @app.errorhandler(403)
    def handle_forbidden(e):
        return jsonify({
            "error": "Access forbidden",
            "code": "FORBIDDEN"
        }), 403

    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        logger.exception(f"Unhandled exception: {str(e)}")
        return jsonify({
            "error": "An internal server error occurred",
            "code": "INTERNAL_SERVER_ERROR"
        }), 500
