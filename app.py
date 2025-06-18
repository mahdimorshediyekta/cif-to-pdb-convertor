import os
import uuid
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests as req
from io import StringIO
from Bio.PDB import MMCIFParser, PDBIO
from dotenv import load_dotenv

# Load .env file for local development
load_dotenv()

# --- Configuration ---
CLOUDFLARE_SECRET_KEY = os.environ.get("CLOUDFLARE_SECRET_KEY")

# Safety check: Ensure the secret key is set
if not CLOUDFLARE_SECRET_KEY:
    raise ValueError("FATAL ERROR: CLOUDFLARE_SECRET_KEY environment variable not set.")

TEMP_DIR = 'temp_files'
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# --- Flask App Initialization ---
app = Flask(__name__)
# In production, you might want to restrict origins to your actual frontend domain
CORS(app, resources={r"/api/*": {"origins": "*"}}) 

# --- CIF to PDB Conversion Logic ---
def convert_cif_to_pdb(cif_data_string: str, structure_id: str = "protein"):
    """
    Parses a CIF string and returns a PDB formatted string.
    """
    try:
        cif_parser = MMCIFParser(QUIET=True)
        cif_file = StringIO(cif_data_string)
        structure = cif_parser.get_structure(structure_id, cif_file)
        
        pdb_io = PDBIO()
        pdb_io.set_structure(structure)
        
        output_pdb = StringIO()
        pdb_io.save(output_pdb)
        return output_pdb.getvalue()

    except Exception as e:
        print(f"Error during CIF to PDB conversion: {e}")
        return None

# --- API Endpoints ---
@app.route('/api/convert', methods=['POST'])
def handle_conversion():
    """
    Handles the main conversion request from the frontend with CAPTCHA verification.
    """
    # 1. Verify Cloudflare Turnstile CAPTCHA
    turnstile_token = request.form.get('cf-turnstile-response')
    if not turnstile_token:
        return jsonify({"success": False, "error": "CAPTCHA token missing. Please refresh the page."}), 403

    verification_response = req.post(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data={"secret": CLOUDFLARE_SECRET_KEY, "response": turnstile_token},
    )
    outcome = verification_response.json()

    if not outcome.get("success"):
        print(f"CAPTCHA verification failed. Reason: {outcome.get('error-codes', 'Unknown')}")
        return jsonify({"success": False, "error": "CAPTCHA verification failed. Please try again."}), 403

    # 2. Get CIF data from either file upload or text area
    cif_data = ""
    if 'file' in request.files and request.files['file'].filename != '':
        cif_file = request.files['file']
        cif_data = cif_file.read().decode('utf-8')
    elif 'cif_data' in request.form and request.form['cif_data'].strip() != '':
        cif_data = request.form['cif_data']
    else:
        return jsonify({"success": False, "error": "No CIF data provided. Please upload a file or paste data."}), 400

    # 3. Perform the conversion
    pdb_result = convert_cif_to_pdb(cif_data)

    if not pdb_result:
        return jsonify({"success": False, "error": "Conversion failed. The provided data may not be a valid CIF format."}), 400

    # 4. Save the result to a temporary file
    unique_filename = f"{uuid.uuid4()}.pdb"
    output_path = os.path.join(TEMP_DIR, unique_filename)
    with open(output_path, "w") as f:
        f.write(pdb_result)

    # 5. Return success with PDB data for preview and a download URL
    return jsonify({
        "success": True,
        "pdb_data": pdb_result,
        "download_url": f"/api/download/{unique_filename}"
    })

@app.route('/api/download/<filename>')
def download_converted_file(filename):
    """
    Serves the converted file for download.
    """
    return send_from_directory(TEMP_DIR, filename, as_attachment=True)

# --- Main Entry Point ---
if __name__ == '__main__':
    # For local development. Gunicorn is used in production.
    app.run(port=5000, debug=True)