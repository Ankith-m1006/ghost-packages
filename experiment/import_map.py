"""Well-known Python import names whose PyPI distribution has a different name.

Used only to *avoid* false ghosts: `import cv2` with `pip install opencv-python` is correct.
"""
import re

IMPORT_TO_DIST = {
    "cv2": "opencv-python", "PIL": "pillow", "sklearn": "scikit-learn", "skimage": "scikit-image",
    "yaml": "pyyaml", "bs4": "beautifulsoup4", "dateutil": "python-dateutil", "dotenv": "python-dotenv",
    "Crypto": "pycryptodome", "Cryptodome": "pycryptodomex", "jwt": "pyjwt", "serial": "pyserial",
    "usb": "pyusb", "docx": "python-docx", "pptx": "python-pptx", "fitz": "pymupdf", "pymupdf": "pymupdf",
    "magic": "python-magic", "attr": "attrs", "OpenSSL": "pyopenssl", "Bio": "biopython",
    "telegram": "python-telegram-bot", "gi": "pygobject", "wx": "wxpython", "mpl_toolkits": "matplotlib",
    "pkg_resources": "setuptools", "win32api": "pywin32", "win32com": "pywin32", "RPi": "rpi-gpio",
    "board": "adafruit-blinka", "busio": "adafruit-blinka", "digitalio": "adafruit-blinka",
    "adafruit_dht": "adafruit-circuitpython-dht", "Adafruit_DHT": "adafruit-dht", "mfrc522": "mfrc522",
    "smbus": "smbus", "smbus2": "smbus2", "can": "python-can", "cantools": "cantools",
    "escpos": "python-escpos", "pymodbus": "pymodbus", "minimalmodbus": "minimalmodbus",
    "opcua": "opcua", "asyncua": "asyncua", "bleak": "bleak", "evdev": "evdev", "hid": "hidapi",
    "influxdb_client": "influxdb-client", "kiteconnect": "kiteconnect", "nsepy": "nsepy",
    "yfinance": "yfinance", "talib": "ta-lib", "binance": "python-binance", "ofxparse": "ofxparse",
    "pydicom": "pydicom", "gpxpy": "gpxpy", "h5py": "h5py", "netCDF4": "netcdf4", "asammdf": "asammdf",
    "fastavro": "fastavro", "exifread": "exifread", "rawpy": "rawpy", "fitparse": "fitparse",
    "ifcopenshell": "ifcopenshell", "osgeo": "gdal", "shapefile": "pyshp", "geopandas": "geopandas",
    "google": "google-api-python-client", "googleapiclient": "google-api-python-client",
    "kubernetes": "kubernetes", "hvac": "hvac", "paramiko": "paramiko", "fabric": "fabric",
    "boto3": "boto3", "botocore": "botocore", "slack_sdk": "slack-sdk", "github": "pygithub",
    "grafana_api": "grafana-api", "grafanalib": "grafanalib", "lightgbm": "lightgbm", "xgboost": "xgboost",
    "optuna": "optuna", "mlflow": "mlflow", "shap": "shap", "sentence_transformers": "sentence-transformers",
    "faiss": "faiss-cpu", "torch": "torch", "transformers": "transformers", "datasets": "datasets",
    "whisper": "openai-whisper", "faster_whisper": "faster-whisper", "pytesseract": "pytesseract",
    "easyocr": "easyocr", "prophet": "prophet", "holidays": "holidays", "rembg": "rembg",
    "pysam": "pysam", "pyfaidx": "pyfaidx", "scanpy": "scanpy", "anndata": "anndata", "rdkit": "rdkit",
    "pydeseq2": "pydeseq2", "cyvcf2": "cyvcf2", "vcf": "pyvcf", "Levenshtein": "levenshtein",
    "rapidfuzz": "rapidfuzz", "fuzzywuzzy": "fuzzywuzzy", "thefuzz": "thefuzz", "ftfy": "ftfy",
    "pandera": "pandera", "duckdb": "duckdb", "polars": "polars", "pyarrow": "pyarrow", "s3fs": "s3fs",
    "ydata_profiling": "ydata-profiling", "pandas_profiling": "pandas-profiling",
    "playwright": "playwright", "selenium": "selenium", "trafilatura": "trafilatura",
    "newspaper": "newspaper3k", "extruct": "extruct", "google_play_scraper": "google-play-scraper",
    "fake_useragent": "fake-useragent", "camelot": "camelot-py", "pdfplumber": "pdfplumber",
    "pypdf": "pypdf", "PyPDF2": "pypdf2", "pikepdf": "pikepdf", "reportlab": "reportlab",
    "endesive": "endesive", "pyhanko": "pyhanko", "qrcode": "qrcode", "weasyprint": "weasyprint",
    "razorpay": "razorpay", "jinja2": "jinja2", "markupsafe": "markupsafe", "lxml": "lxml",
    "num2words": "num2words", "pyzbar": "pyzbar", "zmq": "pyzmq", "nacl": "pynacl",
    "websocket": "websocket-client", "websockets": "websockets", "socketio": "python-socketio",
    "flask_cors": "flask-cors", "pydantic": "pydantic", "fastapi": "fastapi", "uvicorn": "uvicorn",
    "mt940": "mt-940", "pyx12": "pyx12", "beancount": "beancount",
    "py_vollib": "py-vollib",
}


def _norm(n: str) -> str:
    return re.sub(r"[-_.]+", "-", n).lower()


# keep only the entries where the import name really differs from the distribution name
IMPORT_TO_DIST = {k: v for k, v in IMPORT_TO_DIST.items() if _norm(k) != _norm(v)}
