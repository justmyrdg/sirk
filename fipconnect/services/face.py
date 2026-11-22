"""Face recognition: image checks, the local Node face service, and
encryption of stored face templates."""

import atexit
import base64
import binascii
import hashlib
import hmac
import io
import json
import logging
import math
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from PIL import Image, UnidentifiedImageError

from fipconnect.config import ROOT

LOGGER = logging.getLogger(__name__)
FACE_MODEL = "vladmandic-face-api-128"
FACE_SERVICE_LOCK = threading.Lock()
FACE_SERVICE_PROCESS = None
LEGACY_FACE_SERVICE_ERRORS = {
    "Hindi mabasa ang camera capture. Subukan ulit.": (
        "Could not read the camera capture. Please try again."
    ),
    "Masyadong malaki o invalid ang camera capture.": (
        "The camera capture is too large or invalid."
    ),
    "JPEG o PNG na camera capture lang ang puwede.": (
        "Only JPEG or PNG camera captures are supported."
    ),
    "Masyadong mataas ang resolution ng camera capture.": (
        "The camera capture resolution is too high."
    ),
    "Dapat iisa lang ang mukha sa camera.": (
        "Only one face may be in the camera frame."
    ),
    "Hindi makilala ang mukha. Tumingin sa camera at subukan ulit.": (
        "Face not recognized. Look at the camera and try again."
    ),
    "Hindi nakabuo ng valid na JavaScript face template.": (
        "Could not create a valid JavaScript face template."
    ),
    "Hindi tugma ang naka-save na face template sa JavaScript model.": (
        "The saved face template is incompatible with the JavaScript model."
    ),
}


def validate_face_image(encoded_image):
    if not isinstance(encoded_image, str):
        raise ValueError("A camera capture is required for facial recognition.")
    try:
        image_bytes = base64.b64decode(encoded_image, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("Could not read the camera capture. Please try again.") from error
    if not image_bytes or len(image_bytes) > 700_000:
        raise ValueError("The camera capture is too large. Please try again.")
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format not in {"JPEG", "PNG"}:
                raise ValueError("Only JPEG or PNG camera captures are supported.")
            if image.width * image.height > 4_000_000:
                raise ValueError("The camera capture resolution is too high.")
            image.verify()
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
            raise ValueError("Could not read the camera capture. Please try again.") from error
    return encoded_image


def face_service_token(secret):
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    return hmac.new(
            secret_bytes,
            b"FIPConnect server-side JavaScript face recognition",
            hashlib.sha256,
    ).hexdigest()


def translate_face_service_error(message):
    return LEGACY_FACE_SERVICE_ERRORS.get(message, message)


def face_service_ready(service_url, token):
    request = urllib.request.Request(
            f"{service_url.rstrip('/')}/health",
            headers={"Authorization": f"Bearer {token}"},
    )
    try:
            with urllib.request.urlopen(request, timeout=1) as response:
                health = json.loads(response.read())
                return response.status == 200 and health.get("ready") is True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return False


def ensure_face_service(service_url, token):
    global FACE_SERVICE_PROCESS
    parsed_url = urllib.parse.urlsplit(service_url)
    if parsed_url.scheme != "http" or parsed_url.hostname not in {
            "127.0.0.1",
            "localhost",
    }:
            raise RuntimeError("Face recognition service must run on this computer.")
    if not parsed_url.port:
            raise RuntimeError("Face recognition service URL must include a port.")
    with FACE_SERVICE_LOCK:
            if face_service_ready(service_url, token):
                return
            if FACE_SERVICE_PROCESS is None or FACE_SERVICE_PROCESS.poll() is not None:
                node = shutil.which("node")
                if not node:
                    raise RuntimeError(
                        "Node.js is required for facial recognition. Install it, then restart the app."
                    )
                environment = os.environ.copy()
                environment["FIPCONNECT_FACE_SERVICE_TOKEN"] = token
                environment["FIPCONNECT_FACE_SERVICE_PORT"] = str(parsed_url.port)
                FACE_SERVICE_PROCESS = subprocess.Popen(
                    [node, str(ROOT / "face_service.cjs")],
                    cwd=ROOT,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                )
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if FACE_SERVICE_PROCESS.poll() is not None:
                    FACE_SERVICE_PROCESS = None
                    # Another worker may have started the service first, so
                    # this process could not take the port. Use theirs.
                    if face_service_ready(service_url, token):
                        return
                    raise RuntimeError(
                        "Could not start the JavaScript face recognition service. Check the server log."
                    )
                if face_service_ready(service_url, token):
                    return
                time.sleep(0.2)
            raise RuntimeError(
                "The JavaScript face recognition models are not ready yet. Please try again."
            )


def stop_face_service():
    global FACE_SERVICE_PROCESS
    with FACE_SERVICE_LOCK:
            if FACE_SERVICE_PROCESS is not None and FACE_SERVICE_PROCESS.poll() is None:
                FACE_SERVICE_PROCESS.terminate()
                try:
                    FACE_SERVICE_PROCESS.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    FACE_SERVICE_PROCESS.kill()
                    FACE_SERVICE_PROCESS.wait(timeout=5)
            FACE_SERVICE_PROCESS = None


atexit.register(stop_face_service)


def call_face_service(operation, payload, service_url, token):
    ensure_face_service(service_url, token)
    service_request = urllib.request.Request(
            f"{service_url.rstrip('/')}/{operation}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
    )
    try:
            with urllib.request.urlopen(service_request, timeout=90) as response:
                return json.loads(response.read())
    except urllib.error.HTTPError as error:
            try:
                result = json.loads(error.read())
            except (json.JSONDecodeError, UnicodeError):
                LOGGER.exception("JavaScript face recognition service returned invalid JSON.")
                raise RuntimeError(
                    "The face recognition service returned an unexpected response."
                ) from error
            message = result.get("error")
            if error.code == 400 and isinstance(message, str):
                raise ValueError(translate_face_service_error(message)) from error
            LOGGER.error("JavaScript face recognition service failed with HTTP %s.", error.code)
            raise RuntimeError(
                message if isinstance(message, str) else "The face recognition service failed."
            ) from error
    except (
            urllib.error.URLError,
            TimeoutError,
            json.JSONDecodeError,
            UnicodeError,
            OSError,
    ) as error:
            LOGGER.exception("Unable to reach the JavaScript face recognition service.")
            raise RuntimeError(
                "Could not connect to the JavaScript face recognition service. Please try again."
            ) from error


def extract_face_embedding(encoded_image, service_url, token):
    validate_face_image(encoded_image)
    result = call_face_service(
            "extract",
            {"image": encoded_image},
            service_url,
            token,
    )
    embedding = result.get("embedding")
    if (
            not isinstance(embedding, list)
            or len(embedding) != 128
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in embedding
            )
    ):
            raise RuntimeError("Could not create a valid JavaScript face template.")
    return embedding


def verify_face_embedding(encoded_image, embedding, service_url, token):
    validate_face_image(encoded_image)
    if (
            not isinstance(embedding, list)
            or len(embedding) != 128
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in embedding
            )
    ):
            raise RuntimeError("The saved face template is incompatible with the JavaScript model.")
    result = call_face_service(
            "verify",
            {"image": encoded_image, "embedding": embedding},
            service_url,
            token,
    )
    if not isinstance(result.get("verified"), bool):
            raise RuntimeError("The face recognition service returned an unexpected response.")
    return result["verified"]


def match_face_embedding(encoded_image, embeddings, service_url, token):
    validate_face_image(encoded_image)
    if not embeddings or any(
        not isinstance(embedding, list)
        or len(embedding) != 128
        or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in embedding
        )
        for embedding in embeddings
    ):
        raise RuntimeError("One or more saved face templates are invalid.")
    result = call_face_service(
        "match",
        {"image": encoded_image, "embeddings": embeddings},
        service_url,
        token,
    )
    matched_index = result.get("matchedIndex")
    if matched_index is not None and (
        not isinstance(matched_index, int)
        or not 0 <= matched_index < len(embeddings)
    ):
        raise RuntimeError("The face recognition service returned an invalid match.")
    return matched_index


def face_cipher(secret_key):
    secret_bytes = secret_key.encode("utf-8") if isinstance(secret_key, str) else secret_key
    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"FIPConnect face template encryption v1",
        info=b"admin face embedding",
    ).derive(secret_bytes)
    return Fernet(base64.urlsafe_b64encode(derived_key))


def encrypt_face_embedding(secret_key, embedding):
    serialized = json.dumps(embedding, separators=(",", ":")).encode("utf-8")
    return face_cipher(secret_key).encrypt(serialized).decode("ascii")


def decrypt_face_embedding(secret_key, encrypted_embedding):
    try:
        serialized = face_cipher(secret_key).decrypt(encrypted_embedding.encode("ascii"))
        embedding = json.loads(serialized)
    except (InvalidToken, ValueError, UnicodeError, json.JSONDecodeError) as error:
        LOGGER.exception("Unable to decrypt the saved admin face template.")
        raise RuntimeError("Could not read the encrypted face template.") from error
    if (
        not isinstance(embedding, list)
        or not embedding
        or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            for value in embedding
        )
    ):
        raise RuntimeError("The saved face template is invalid.")
    return embedding
