from flask import Flask, send_from_directory

app = Flask(__name__)

@app.route('/data/<path:filename>')
def serve_geojson(filename):
    return send_from_directory("data", filename)

if __name__ == '__main__':
    app.run(debug=True)