from functools import wraps
from flask import request, jsonify
from pydantic import ValidationError, BaseModel
from typing import Type

def validate_request(schema: Type[BaseModel]):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Handle both JSON and Form data
                if request.is_json:
                    data = request.get_json()
                else:
                    data = request.args.to_dict() if request.method == 'GET' else request.form.to_dict()
                
                # Validate
                validated_data = schema(**data)
                
                # Pass validated data to the function
                return f(validated_data, *args, **kwargs)
            except ValidationError as e:
                return jsonify({
                    "error": "Validation Error",
                    "details": e.errors()
                }), 400
        return decorated_function
    return decorator
