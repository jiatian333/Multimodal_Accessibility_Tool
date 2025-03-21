from flask import Flask, send_from_directory
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/data/<path:filename>')
def serve_geojson(filename):
    return send_from_directory("data", filename)

if __name__ == '__main__':
    app.run(debug=True)