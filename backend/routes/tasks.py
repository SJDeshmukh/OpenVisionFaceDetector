from flask import Blueprint, jsonify
from celery_app import celery

tasks_bp = Blueprint('tasks_bp', __name__)

@tasks_bp.route('/tasks/<task_id>', methods=['GET'])
def get_status(task_id):
    if not celery:
        return jsonify({"state": "ERROR", "status": "Celery not initialized"}), 500
        
    task_result = celery.AsyncResult(task_id)
    result = {
        "task_id": task_id,
        "state": task_result.state,
    }
    
    if task_result.state == 'FAILURE':
        result['status'] = str(task_result.info)
    elif task_result.state == 'SUCCESS':
        result['result'] = task_result.get()
        
    return jsonify(result)
