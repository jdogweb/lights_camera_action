import atexit
from flask import Flask
from flask_cors import CORS
from motor import setup as motor_setup, cleanup as motor_cleanup
from routes import bp

app = Flask(__name__)
CORS(app)
app.register_blueprint(bp)

motor_setup()
atexit.register(motor_cleanup)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=False)
