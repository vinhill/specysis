import os
import json
from flask import Flask, jsonify, send_from_directory, redirect, url_for


app = Flask(__name__, static_folder='static')

@app.route('/')
def index():
    # Redirect / to /static/index.html
    return redirect(url_for('static', filename='index.html'))

@app.route('/api/graph')
def get_definitions():
    # Return the definitions JSON
    if not os.path.exists('graph.json'):
        return jsonify({"error": "No graph.json found. Please run parse_spec.py first."}), 404
    with open('graph.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    return jsonify(data)

@app.route('/static/<path:filename>')
def serve_static(filename):
    # Serve any static files by name
    return send_from_directory(app.static_folder, filename)

if __name__ == '__main__':
    # Run the server
    app.run(debug=True, port=5000)
