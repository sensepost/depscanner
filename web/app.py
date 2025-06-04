import logging.config
import sys
import os

# Add the parent directory of 'depscanner' to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask, render_template, request, redirect, url_for, flash, Response, send_file, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime
from depscanner import DepScanner
from depscanner import DepScannerDaemon
from depscanner import MongoManager
import logging
import yaml

####################
# Helper Functions #
####################
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def read_config_file():
    """Read the configuration file and return its content."""
    config_file_path = os.path.join(os.path.dirname(__file__), "../config.yml")
    if os.path.exists(config_file_path):
        with open(config_file_path, "r") as file:
            config = yaml.safe_load(file)
            return config
    else:
        print(f"Configuration file {config_file_path} not found.")
        return {}

def setup_logging():
    logging_config = {}
    with open("logging.yml","r") as lf:
        logging_config = yaml.safe_load(lf)
    # Load config
    logging.config.dictConfig(logging_config)


###################
# Setup variables #
###################
UPLOAD_FOLDER = "uploads/"
ALLOWED_EXTENSIONS = {"txt"}
LOG_FILE_PATH = "logs/depscanner.log"  # Replace with the actual log file path

daemon = DepScannerDaemon()

app = Flask(__name__, template_folder="templates")
app.secret_key = "KSapJDFIOd0-sYH837KLkdj89-dk"  # For flashing messages
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["LOG_FILE_PATH"] = LOG_FILE_PATH
# Read the configuration file
config = read_config_file()

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initiate the loging configuration
setup_logging()

####################
# Routes and Views #
####################

@app.route("/", methods=["GET", "POST"])
def index():
    return render_template("index.html")

@app.route("/upload", methods=["POST", "GET"])
def upload():
    if request.method == "POST":
        file = request.files.get("file")
        filename = secure_filename(file.filename)
        file_type = request.form.get("file_type")

        if not file or not allowed_file(file.filename):
            flash(f"Invalid file format. Allowed file types: {ALLOWED_EXTENSIONS}.", "danger")
            return redirect(url_for("upload"))

        # Extract the folder where this file is going to be saved
        if file_type == "organizations":
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], "organizations", filename)
        elif file_type == "repositories":
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], "repositories", filename)
        elif file_type == "domains":
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], "domains", filename)
        else:
            flash("Invalid file type.", "danger")
            return redirect(url_for("upload"))

        file.save(filepath)

        flash(f"File {filename} uploaded to {filepath}", "success")
        return redirect(url_for("upload"))
    elif request.method == "GET":
        return render_template("upload.html")
    else:
        flash(f"Method {request.method} not allowed")
        return redirect(url_for("index"))

@app.route("/missing-packages")
def missing_packages():
    """Display the missing packages from the database."""
    mongo_config = config.get("mongo",{})
    mongomgr = MongoManager(        
        host = mongo_config["host"],
        port = int(mongo_config["port"]),
        database = mongo_config["database"],
        username = mongo_config["username"],
        password = mongo_config["password"],
    )
    pypi_packages = list(mongomgr.get_packages(present=False,registry="pypi.org"))
    npm_packages = list(mongomgr.get_packages(present=False,registry="registry.npmjs.org"))
    go_packages = list(mongomgr.get_packages(present=False,registry="go.dev"))
    ruby_packages = list(mongomgr.get_packages(present=False,registry="rubygems.org"))
    return render_template(
        "missing_packages.html", 
        pypi_packages=pypi_packages,
        npm_packages=npm_packages,
        go_packages=go_packages,
        ruby_packages=ruby_packages
    )

@app.route("/run", methods=["POST", "GET"])
def run():
    if request.method == "GET":
        file_type = request.args.get("file_type")
        if file_type is None:
            return render_template("run.html", files=[])
        else:
            if file_type == "organizations":
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "organizations")
            elif file_type == "repositories":
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "repositories")
            elif file_type == "domains":
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "domains")
            else:
                flash("Invalid file type.", "warning")
                return redirect(url_for("upload"))
            
        # Check if the DepScanner daemon is running to show the progress bar
        if daemon.running:
            flash("A scan is already running. Go to <a href='/logs'>logs</a> to see how it is going", "warning")
            return render_template("run.html", files=os.listdir(folder), progress=daemon.get_progress())
        else:
            return render_template("run.html", files=os.listdir(folder))
    elif request.method == "POST":
        file_type = request.form.get("file_type")
        if file_type is None:
            return render_template("run.html", files=[])
        else:
            if file_type == "organizations":
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "organizations")
            elif file_type == "repositories":
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "repositories")
            elif file_type == "domains":
                folder = os.path.join(app.config["UPLOAD_FOLDER"], "domains")
            else:
                flash("Invalid file type.", "warning")
                return redirect(url_for("upload"))
            
        # Get the selected file and type
        file_name = request.form.get("file_name")
        file_type = request.form.get("file_type")
        discord_webhook = request.form.get("discordWebhook")
        github_token = request.form.get("githubToken")
        num_stars = int(request.form.get("numStars")) if len(request.form.get("numStars")) else 0
        force = request.form.get("forceRefresh", "false").lower() == "on"

        if not file_name or not file_type or not github_token:
            flash("Github Token and file name are required to run.", "danger")
            return redirect(url_for("run"))

        if not os.path.exists(file_name):
            flash(f"File {file_name} does not exist.", "danger")
            return redirect(url_for("run"))

        # Create the DepScanner instance
        daemon.dep_scanner = DepScanner(
            gh_token=github_token,
            webhook_url=discord_webhook,
            force=force,
            stars=num_stars,
            organisation_file=os.path.join(os.path.dirname(__file__), file_name) if file_type == "organizations" else None,
            repositories_file=os.path.join(os.path.dirname(__file__), file_name) if file_type == "repositories" else None,
            domains_file=os.path.join(os.path.dirname(__file__), file_name) if file_type == "domains" else None,
            logger=logging.getLogger('depScannerThread'),
            config=os.path.join(os.path.dirname(__file__), "../config.yml"),
        )

        # Start the DepScanner daemon
        if not daemon.running:
            daemon.start()
            flash("Scan started successfully.", "success")
            # Update the button text to "Stop Scan" and percentage bar to 0%
            return render_template("run.html", files=os.listdir(folder), file_type=file_type, progress=0)
    else:
        return redirect("index.html")

@app.route("/get-files", methods=["POST"])
def get_files():
    file_type = request.json.get("file_type")
    folder_mapping = {
        "organizations": "uploads/organizations/",
        "repositories": "uploads/repositories/",
        "domains": "uploads/domains/"
    }
    folder = folder_mapping.get(file_type, "")
    if not folder or not os.path.exists(folder):
        return jsonify({"files": []})

    files = []
    for file_name in os.listdir(folder):
        file_path = os.path.join(folder, file_name)
        if os.path.isfile(file_path):
            # Ignore the hiden files that start with dot
            if not file_name.startswith("."):
                files.append({
                    "name": file_name,
                    "size": os.path.getsize(file_path),  # File size in bytes
                    "date": datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M:%S'),  # Last modified date
                    "path": file_path  # Full file path
                })

    return jsonify({"files": files})

@app.route("/logs", methods=["GET"])
def logs():    
    log_files = []
    for root, dirs, files in os.walk("logs"):
        for file in files:
            if ".log" in file:
                log_files.append(os.path.join(root, file))
    return render_template("logs.html", log_files=log_files)

@app.route("/logs/files", methods=["GET"])
def list_logs():
    log_files = []
    for root, dirs, files in os.walk("logs"):
        for file in files:
            if ".log" in file:
                log_files.append(os.path.join(root, file))
    return render_template("logs.html", log_files=log_files)


@app.route("/logs/tail", methods=["GET"])
def tail_logs():
    offset = int(request.args.get("offset", 0))  # Get the offset from the query parameter
    log_file = request.args.get("file", LOG_FILE_PATH)  # Get the log file from the query parameter
    log_content = ""
    new_offset = offset

    if (os.path.exists(log_file)):
        with open(log_file, "r") as f:
            f.seek(offset)  # Move to the specified offset
            log_content = f.read()  # Read the new content
            new_offset = f.tell()  # Get the new offset

    return jsonify({"content": log_content, "new_offset": new_offset})

@app.route("/delete-file", methods=["POST"])
def delete_file():
    file_path = request.json.get("file_path")
    if not file_path:
        flash("File path is required.", "danger")
        return redirect(request.referrer)

    # Ensure the file is within the allowed directories
    allowed_directories = [
        os.path.join(app.config["UPLOAD_FOLDER"], "domains"),
        os.path.join(app.config["UPLOAD_FOLDER"], "repositories"),
        os.path.join(app.config["UPLOAD_FOLDER"], "organizations")
    ]

    if not any(file_path.startswith(directory) for directory in allowed_directories):
        flash("Invalid file path specified.", "danger")
        return redirect(request.referrer)

    # Ensure the file has a .txt extension
    if not file_path.endswith(".txt"):
        flash("Only .txt files are allowed.", "danger")
        return redirect(request.referrer)

    # Check if the file exists and delete it
    if os.path.exists(file_path):
        os.remove(file_path)
        flash(f"File '{file_path}' deleted successfully.", "success")
        return redirect(request.referrer)
    else:
        flash(f"File '{file_path}' not found.", "danger")
    return redirect(request.referrer)

@app.route("/scan/stop", methods=["POST"])
def stop_scan():
    """Stop the DepScanner daemon."""
    if daemon.running:
        daemon.stop()
        return jsonify({"message": "Scan stopped"}), 200
    else:
        return jsonify({"message": "No scan is currently running"}), 400

@app.route("/status", methods=["GET"])
def status():
    """Get the status of the DepScanner daemon."""
    return jsonify({"status": daemon.get_status()}), 200

@app.route("/scan/progress", methods=["GET"])
def get_scan_progress():
    """Get the current scan progress"""
    return jsonify(daemon.get_progress())

@app.route("/scan/status", methods=["GET"])
def get_scan_status():
    """Get the current scan progress"""
    return jsonify(daemon.get_status())

@app.route("/scan/auth", methods=['GET'])
def get_scan_authenticated():
    """Return the current user authenticated to github"""
    return jsonify(daemon.authenticated_as())

@app.route("/logs/download", methods=["GET"])
def download_log():
    """Download the selected log file."""
    def valid_log_file(path):
        # Ensure the file is within the logs/ folder
        logs_folder = os.path.abspath("logs")
        file_path = os.path.abspath(path)
        if not file_path.startswith(logs_folder):
            return False

        # Ensure the file name matches the pattern .log or .log.<number>
        file_name = os.path.basename(file_path)
        if not (file_name.endswith(".log") or file_name.startswith(".log.")):
            return False

        return True

    file_name = request.args.get("file")
    if not file_name:
        return "File name is required", 400

    if not os.path.exists(file_name) or not valid_log_file(file_name):
        flash("Invalid file")
        return redirect(url_for("logs"))
    else:
        return send_file(file_name, as_attachment=True)

if __name__ == "__main__":
    app.run(debug=True)