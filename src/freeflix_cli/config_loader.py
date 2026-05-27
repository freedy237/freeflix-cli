import json
import re
from curl_cffi import requests


def strip_json_comments(json_str: str) -> str:
    """
    Remove // and /* */ comments from JSON string.
    """
    # Remove // comments
    json_str = re.sub(r"(?<!:)\/\/.*$", "", json_str, flags=re.MULTILINE)
    # Remove /* */ comments
    json_str = re.sub(r"\/\*.*?\*\/", "", json_str, flags=re.DOTALL)
    return json_str


def strip_trailing_commas(json_str: str) -> str:
    """
    Remove trailing commas from JSON objects and arrays.
    """
    return re.sub(r",\s*([\]}])", r"\1", json_str)


def load_remote_jsonc(url: str, default: dict) -> dict:
    """
    Fetch a remote JSONC file, strip comments, and parse it.
    Returns the default dictionary if fetching or parsing fails.
    """
    try:
        response = requests.get(url, impersonate="chrome", timeout=5)
        response.raise_for_status()

        clean_json = strip_json_comments(response.text)
        clean_json = strip_trailing_commas(clean_json)

        return json.loads(clean_json)
    except Exception as e:
        print(f"Warning: Failed to load remote config from {url}: {e}")
        return default


def load_local_jsonc(file_path: str, default: dict = None) -> dict:
    """
    Load a local JSONC file, strip comments, and parse it.
    Returns default if the file is missing or invalid.
    """
    import os

    if not os.path.exists(file_path):
        return default or {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        clean_json = strip_json_comments(content)
        clean_json = strip_trailing_commas(clean_json)

        return json.loads(clean_json)
    except Exception as e:
        print(f"Warning: Failed to load local config from {file_path}: {e}")
        return default or {}
