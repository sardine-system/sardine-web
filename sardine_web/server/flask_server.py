from __future__ import annotations

import contextlib
import json
import logging
import mimetypes
import os
import platform
import subprocess
import webbrowser
from pathlib import Path
from threading import Thread
from typing import TYPE_CHECKING, Any

from appdirs import user_data_dir
from flask import (
    Flask,
    Response,
    jsonify,
    request,
    send_from_directory,
)
from flask_cors import CORS
from pygtail import Pygtail
from rich import print

if TYPE_CHECKING:
    from sardine.console import AsyncIOInteractiveConsole

# Monkey-patching to prevent some initial printing
# More info can be found here: https://gist.github.com/daryltucker/e40c59a267ea75db12b1
import flask.cli

flask.cli.show_server_banner = lambda *args: None
logging.getLogger("werkzeug").disabled = True
mimetypes.add_type("text/css", ".css")


APP_NAME, APP_AUTHOR = "Sardine", "Bubobubobubo"
USER_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))
LOG_FILE = USER_DIR / "sardine.log"
FILENAMES = [f"buffer{i}.py" for i in range(1, 10)]

# We need to create the log file if it doesn't already exist
Path(LOG_FILE).touch(exist_ok=True)

__all__ = ("WebServer",)


class WebServer:
    """
    This is a small Flask WebServer serving the Sardine Code Editor. This web server is
    also charged of loading / dispatching locally stored buffer files that act as a
    temporary memory for the editor. Files are stored in plain-text in the Sardine conf-
    iguration folder under the buffers/folder.
    """

    def __init__(self, host: str = "localhost", port: int = 8000):
        self.host, self.port = host, port
        self.reset_log_file()
        self.local_files = self.load_buffer_files()

    def reset_log_file(self) -> None:
        """Reset the log file on application start. Writing to the file
        and immediately closing is effectively erasing the content."""
        with contextlib.suppress(FileNotFoundError):
            os.truncate(LOG_FILE, 0)

    def check_buffer_files(self) -> None:
        """This function will check the integrity of the buffer folder."""
        buffer_folder = USER_DIR / "buffers"
        for filename in FILENAMES:
            buffer_file = buffer_folder / filename
            buffer_file.touch()

    def load_buffer_files(self) -> dict[str, str] | None:
        """
        Loading buffer files from a local folder. If the folder doesn't exist, this
        function will automatically create it and load empty files for the first round.
        If the folder exists, read files in their current state
        """
        buffer_files: dict[str, str] = {}

        # Creating the folder to store text files if it doesn't exist
        buffer_folder = USER_DIR / "buffers"
        if not buffer_folder.is_dir():
            try:
                buffer_folder.mkdir()
                for filename in FILENAMES:
                    print(f"Creating {filename}")
                    buffer_file = buffer_folder / filename
                    buffer_file.touch()
                    buffer_files[filename] = filename
                return buffer_files
            except OSError:
                print("[red]Fishery was not able to create web editor files![/red]")
                exit()
        # If it already exists, read files from the folder
        else:
            self.check_buffer_files()
            buffer_folder = Path(USER_DIR / "buffers")
            for file in os.listdir(buffer_folder):
                # .DS_Store files on MacOS killing the mood
                if str(file).startswith("."):
                    continue
                path = (buffer_folder / file).as_posix()
                with open(path, "r", encoding="utf-8") as buffer:
                    buffer_files[file] = buffer.read()
            return buffer_files

    def start(self, console: AsyncIOInteractiveConsole) -> None:
        app = server_factory(console)

        # Start the application
        app.run(
            host=self.host,
            port=self.port,
            use_reloader=False,
            debug=False,
        )

    def start_in_thread(self, console: AsyncIOInteractiveConsole) -> None:
        # FIXME: daemon=True is not a good idea because we can't perform
        #        any cleanup, however the alternative is users having to
        #        SIGKILL the hanging process which is no better.
        #        This webserver should be re-written to run as a subprocess.
        Thread(target=self.start, args=(console,), daemon=True).start()

    def open_in_browser(self):
        address = f"http://{self.host}:{self.port}"
        print(f"[red]Opening embedded editor at: [yellow]{address}[/yellow][/red]")
        webbrowser.open(address)


def server_factory(console: AsyncIOInteractiveConsole) -> Flask:
    app = Flask(__name__, static_folder="../client/dist")
    app.logger.disabled = True  # Disable some of the logging
    CORS(app, resources={r"/*": {"origins": "*"}})

    @app.route("/save", methods=["POST"])
    def save_files_to_disk() -> str:
        try:
            data = request.get_json(silent=False)
            if data:
                for key, content in data.items():
                    path = USER_DIR / "buffers" / f"{key}"
                    with open(path, "w", encoding="utf-8") as new_file:
                        # This is where you are supposed to do something about
                        # formatting.
                        new_file.write(
                            "\n".join(content) if isinstance(content, list) else content
                        )
                return "OK"
        except Exception as e:
            print(e)
        finally:
            return "FAILED"

    @app.post("/open_folder")
    def open_folder() -> str:
        """Open Sardine Default Folder using the default file Explorer"""

        def showFileExplorer(path: str) -> None:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", path])

        # Open the file explorer
        showFileExplorer(str(USER_DIR))

        return "OK"

    @app.post("/execute")
    def execute() -> dict[str, Any]:
        code: str = request.json["code"]  # type: ignore
        try:
            # If `code` contains multiple statements, an exception occurs but
            # code.InteractiveInterpreter.runsource swallows it.
            # This means `console`s buffer will fill up with garbage and break
            # any subsequent correctly-formed statements.
            # So, reset the buffer first.
            console.resetbuffer()
            console.push(code)
            return {"code": code}
        except Exception as e:
            # Due to the above, there's no way to send a SyntaxError back to the client.
            return {"error": str(e)}

    # Serve App
    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve(path: str) -> Response:
        assert app.static_folder is not None
        if path != "" and os.path.exists(app.static_folder + "/" + path):
            return send_from_directory(app.static_folder, path)
        else:
            return send_from_directory(app.static_folder, "index.html")

    @app.route("/log")
    def progress_log() -> Response:
        def generate():
            try:
                unread_lines = Pygtail(
                    str(LOG_FILE),
                    every_n=1,
                    full_lines=True,
                    encoding="utf-8",
                )
                for line in unread_lines:
                    yield "data:" + str(line) + "\n\n"
                if unread_lines.length == 0:
                    yield "data:" + str("") + "\n\n"
            except Exception as e:
                yield "data: An error occured while reading the logfile\n\n"

        return Response(generate(), mimetype="text/plain")

    @app.route("/config")
    def get_config() -> Response:
        try:
            with open(USER_DIR / "config.json", "r") as f:
                config_data = json.load(f)["config"]
            response = jsonify(config_data)
        except Exception as e:
            print("Error while reading config.json:", e)
            response = jsonify({"error": "Internal server error"})
            response.status_code = 500
        return response

    @app.route("/save_config", methods=["POST"])
    def save_config():
        data = request.get_json()
        wrapped_data = {"config": data}

        with open(USER_DIR / "config.json", "w") as f:
            json.dump(wrapped_data, f)

        return "OK"

    @app.route("/text_files", methods=["GET"])
    def get_text_files() -> Response:
        files = {}
        for file_name in os.listdir(USER_DIR / "buffers"):
            if file_name.endswith(".py"):
                buffer_directory = USER_DIR / "buffers"
                with open((buffer_directory / file_name).as_posix(), "r") as f:
                    files[file_name] = f.read()
        files = jsonify(files)
        files.headers.add("Access-Control-Allow-Origin", "*")
        return files

    return app
