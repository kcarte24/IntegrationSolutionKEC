from flask import Flask, request, jsonify, render_template
from database import init_db, get_db_connection
from datetime import datetime
from faker import Faker
import random, time, json, os, threading

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

init_db()


@app.route('/')
def home():
    conn = get_db_connection()
    messages = conn.execute('SELECT * FROM messages').fetchall()
    conn.close()

    parsed_messages = []

    for m in messages:
        raw = json.loads(m['raw_data']) if m['raw_data'] else {}
        transformed = json.loads(m['transformed_data']) if m['transformed_data'] else None
        updated_at = datetime.fromisoformat(m["updated_at"])
        formatted_updated = updated_at.strftime("%b %d, %Y %I:%M:%S %p")

        parsed_messages.append({
            "id": m["id"],
            "source_system": m["source_system"],
            "target_system": m["target_system"],
            "status": m["status"],
            "raw": raw,
            "transformed": transformed,
            "failure_reason": m["failure_reason"],
            "updated_at": formatted_updated
        })
    return render_template('index.html', messages=parsed_messages)

# --------------------------------------------------------------------------------------------
# TRANSFORMATION LOGIC
def map_diagnosis(dx):
    return {
        "Lung Cancer": "LC",
        "Breast Cancer": "BC",
        "Prostate Cancer": "PC",
        "Lymphoma": "LYM"
    }.get(dx, dx)

def map_plan(plan):
    return {
        "Radiation Therapy": "RT",
        "Chemotherapy": "CHEMO",
        "Immunotherapy": "IMMUNO",
        "Surgery": "SURG"
    }.get(plan, plan)

def reverse_diagnosis(code):
    return {
        "LC": "Lung Cancer",
        "BC": "Breast Cancer",
        "PC": "Prostate Cancer",
        "LYM": "Lymphoma"
    }.get(code, code)

def reverse_plan(code):
    return {
        "RT": "Radiation Therapy",
        "CHEMO": "Chemotherapy",
        "IMMUNO": "Immunotherapy",
        "SURG": "Surgery"
    }.get(code, code)

# --------------------------------------------------------------------------------------------
#Separate Create Message Page
@app.route('/create')
def create_page():
    return render_template('create_message.html')
# --------------------------------------------------------------------------------------------
# Message Ingestion (CREATE)
@app.route('/messages', methods=['POST'])
def create_message():
    # Mock Data UI Input - Manual Entry
    data = request.get_json()
    source = data.get("source_system")
    target = data.get("target_system")

    if source == target:
        return jsonify({"error": "Source and Target cannot be the same"}), 400

    if source == "Epic":
        patient_data = {
            "patient_id": data.get("patient_id"),
            "patient_name": data.get("patient_name"),
            "diagnosis": data.get("diagnosis"),
            "treatment_plan": data.get("treatment_plan")
        }
    else:
        patient_data = {
            "patientId": data.get("patient_id"),
            "patientName": data.get("patient_name"),
            "diagnosisCode": map_diagnosis(data.get("diagnosis")),
            "radiationPlanCode": map_plan(data.get("treatment_plan"))
        }

    timestamp = datetime.now().isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()

    patient_id = data.get("patient_id")
    if not patient_id or not patient_id.startswith("P"):
        return jsonify({"error": "Invalid Patient ID format"}), 400

    if data.get("diagnosis") not in diagnoses:
        return jsonify({"error": "Invalid diagnosis"}), 400

    if data.get("treatment_plan") not in plans:
        return jsonify({"error": "Invalid treatment plan"}), 400

    cursor.execute('''
        INSERT INTO messages (source_system, target_system, raw_data, status, created_at, updated_at, retry_count, user_created)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (source, target, json.dumps(patient_data), 'RECEIVED', timestamp, timestamp, 0, 1))

    message_id = cursor.lastrowid
    conn.commit()
    conn.close()

    threading.Thread(
        target=process_message_internal,
        args=(message_id,),
        daemon=True
    ).start()

    return jsonify({"id": message_id, "status": "RECEIVED"}), 201

# --------------------------------------------------------------------------------------------
# Mock Data Background Input
# Fake name generation
fake = Faker()
def generate_name():
    if random.random() < 0.1:
        return "Baby Jane Doe"
    return fake.name()


# Generation of mock patient data
diagnoses = ["Lung Cancer", "Breast Cancer", "Prostate Cancer", "Lymphoma"]
plans = ["Radiation Therapy", "Chemotherapy", "Immunotherapy", "Surgery"]

def auto_generate():
    while True:
        time.sleep(2)
        for _ in range(3):
            source = random.choice(["Epic", "MOSAIQ"])
            dx = random.choice(diagnoses)
            plan = random.choice(plans)

            if source == "Epic":
                patient_data = {
                    "patient_id": f"P{random.randint(1000, 9999)}",
                    "patient_name": generate_name(),
                    "diagnosis": dx,
                    "treatment_plan": plan
                }
                target = "MOSAIQ"
            else:
                patient_data = {
                    "patientId": f"P{random.randint(1000, 9999)}",
                    "patientName": generate_name(),
                    "diagnosisCode": map_diagnosis(dx),
                    "radiationPlanCode": map_plan(plan)
                }
                target = "Epic"

            conn = get_db_connection()
            cursor = conn.cursor()
            timestamp = datetime.now().isoformat()

            cursor.execute('''
                  INSERT INTO messages (source_system, target_system, raw_data, status, created_at, updated_at, retry_count)
                  VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (f"{source}",f"{target}",json.dumps(patient_data), "RECEIVED", timestamp, timestamp, 0))

            message_id = cursor.lastrowid
            conn.commit()
            conn.close()

            threading.Thread(
                target=process_message_internal,
                args=(message_id,),
                daemon=True
            ).start()


# --------------------------------------------------------------------------------------------
@app.route('/message/<int:id>')
def message_detail(id):
    conn = get_db_connection()
    message = conn.execute(
        'SELECT * FROM messages WHERE id = ?', (id,)
    ).fetchone()
    conn.close()

    if not message:
        return "Message not found", 404

    raw = json.loads(message['raw_data']) if message['raw_data'] else {}
    transformed = json.loads(message['transformed_data']) if message['transformed_data'] else {}

    created_dt = datetime.fromisoformat(message['created_at'])
    updated_dt = datetime.fromisoformat(message['updated_at'])

    formatted_created = created_dt.strftime("%b %d, %Y %I:%M:%S %p")
    formatted_updated = updated_dt.strftime("%b %d, %Y %I:%M:%S %p")

    message_dict = dict(message)
    message_dict["can_delete"] = can_delete(message)
    message_dict["is_integration_error"] = any(
        err in (message["failure_reason"] or "").lower()
        for err in INTEGRATION_REVIEW_ERRORS
    )

    return render_template(
        'message_detail.html',
        message=message_dict,
        raw=raw,
        transformed=transformed,
        created_at=formatted_created,
        updated_at=formatted_updated,
    )


# --------------------------------------------------------------------------------------------
# Get Messages (READ)
@app.route('/messages', methods=['GET'])
def get_messages():
    conn = get_db_connection()
    messages = conn.execute('SELECT * FROM messages').fetchall()
    conn.close()

    result = []
    for message in messages:
        result.append({
            "id": message["id"],
            "source_system": message["source_system"],
            "raw_data": message["raw_data"],
            "transformed_data": message["transformed_data"],
            "status": message["status"],
            "failure_reason": message["failure_reason"],
            "created_at": message["created_at"],
            "updated_at": message["updated_at"]
        })
    return jsonify(result)
# --------------------------------------------------------------------------------------------
#Refresh API Route
@app.route('/api/messages', methods=['GET'])
def get_messages_api():
    conn = get_db_connection()
    messages = conn.execute('SELECT * FROM messages').fetchall()
    conn.close()

    result = []
    for message in messages:
        updated_dt = datetime.fromisoformat(message["updated_at"])
        formatted_updated = updated_dt.strftime("%b %d, %Y %I:%M:%S %p")
        result.append({
            "id": message["id"],
            "source_system": message["source_system"],
            "target_system": message["target_system"],
            "raw_data": message["raw_data"],
            "transformed_data": message["transformed_data"],
            "status": message["status"],
            "failure_reason": message["failure_reason"],
            "retry_count": message["retry_count"],
            "created_at": message["created_at"],
            "updated_at": formatted_updated,
            "can_delete": can_delete(message),
            "is_user_created": message["user_created"],
            "is_integration_error": any(err in (message["failure_reason"] or "").lower() for err in INTEGRATION_REVIEW_ERRORS)
        })
    return jsonify(result)
# --------------------------------------------------------------------------------------------
# Processing Logic
def process_message_internal(id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        message = conn.execute(
            'SELECT * FROM messages WHERE id = ?', (id,)
        ).fetchone()

        if not message:
            return

        user_created = message["user_created"]
        source = message['source_system']
        target = message['target_system']
        raw = json.loads(message['raw_data'])

        # Determine if retry
        is_retry = message['status'] == 'RETRYING'

        # Show RETRYING state briefly
        if is_retry:
            time.sleep(1.5)
        else:
            time.sleep(1)

        # Move to PROCESSING (for both retry and first-time)
        cursor.execute('''
            UPDATE messages
            SET status = ?, updated_at = ?
            WHERE id = ?
        ''', ('PROCESSING',datetime.now().isoformat(), id))
        conn.commit()
        # Simulate processing time (always)
        time.sleep(random.uniform(2,4))

        timestamp = datetime.now().isoformat()

        patient_id = raw.get("patient_id") or raw.get("patientId")
        patient_id = str(patient_id) if patient_id else None

        error = None
        #Detailed Message Field Validation
        #Patient ID:
        if not patient_id:
            error = "Missing Patient ID"
        elif not patient_id.startswith("P") or not patient_id[1:].isdigit():
            error = "Invalid patient ID"

        #Diagnosis Validation:
        elif "Epic" in source:
            if raw.get("diagnosis") not in diagnoses:
                error = "Invalid diagnosis"

        elif "MOSAIQ" in source:
            if raw.get("diagnosisCode") not in ["LC","BC", "PC", "LYM"]:
                error = "Invalid diagnosis code"

        #Treatment Plan Validation:
        if not error:
            if "Epic" in source:
                if raw.get("treatment_plan") not in plans:
                    error = "Invalid treatment plan"
            elif "MOSAIQ" in source:
                if raw.get("radiationPlanCode") not in ["RT", "CHEMO", "IMMUNO","SURG"]:
                    error = "Invalid treatment plan code"
        if error:
            cursor.execute('''
                UPDATE messages
                SET status = ?,
                failure_reason = ?,
                updated_at = ?
                WHERE id = ?
            ''', ('FAILED', error, timestamp, id))

            conn.commit()
            conn.close()
            return

        existing_failure = message["failure_reason"]

# If this message has failed before, reuse the same reason
        if existing_failure and not user_created:
            # Decide if retry succeeds or fails
            if random.random() < 0.5:
                # FAIL AGAIN (same reason)
                cursor.execute('''
                    UPDATE messages
                    SET status = ?, failure_reason = ?, updated_at = ?
                    WHERE id = ?
                ''', ('FAILED', existing_failure, timestamp, id))

                conn.commit()
                conn.close()
                return
            else:
                # SUCCESS on retry
                failure_reason = None
        else:
            # First-time processing → generate failure randomly
            failure_reason = None
            if not user_created:
                if random.random() < 0.3:
                    failure_reason = "System timeout during processing"
                elif random.random() < 0.15:
                    failure_reason = "Transformation schema mismatch"
                elif "Epic" in source and random.random() < 0.1:
                    failure_reason = "Epic data mapping error"
                elif "MOSAIQ" in source and random.random() < 0.1:
                    failure_reason = "MOSAIQ encoding failure"

            if failure_reason:
                cursor.execute('''
                    UPDATE messages
                    SET status = ?, failure_reason = ?, updated_at = ?
                    WHERE id = ?
                ''', ('FAILED', failure_reason, timestamp, id))

                conn.commit()
                conn.close()
                return
        # --------------------------------------------------------------------------------------------
        if "Epic" in source and "MOSAIQ" in target:
            transformed = {
                "patientId": raw.get("patient_id"),
                "patientName": raw.get("patient_name"),
                "diagnosisCode": map_diagnosis(raw.get("diagnosis")),
                "radiationPlanCode": map_plan(raw.get("treatment_plan"))
            }

        elif "MOSAIQ" in source and "Epic" in target:
            transformed = {
                "patient_id": raw.get("patientId"),
                "patient_name": raw.get("patientName"),
                "diagnosis": reverse_diagnosis(raw.get("diagnosisCode")),
                "treatment_plan": reverse_plan(raw.get("radiationPlanCode"))
            }
        transformed_data = json.dumps(transformed)

        cursor.execute('''
            UPDATE messages
            SET status = ?, transformed_data = ?, failure_reason = NULL, updated_at = ?
            WHERE id = ?
        ''', ('SUCCESS', transformed_data, timestamp, id))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Processing failed for message {id}: {e}")
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            UPDATE messages
            SET status = ?, failure_reason = ?, updated_at = ?
            WHERE id = ?
        ''', ('FAILED', 'Unexpected processing error', datetime.now().isoformat(), id))

        conn.commit()
        conn.close()

# --------------------------------------------------------------------------------------------
# Reprocessing Failed message transformation
@app.route('/messages/<int:id>/process', methods=['PUT'])
def reprocess_message(id):
    conn = get_db_connection()
    cursor = conn.cursor()

    message = conn.execute(
        'SELECT * FROM messages WHERE id = ?', (id,)
    ).fetchone()

    if not message:
        return jsonify({"error": "Message not found"}), 404

    cursor.execute('''
        UPDATE messages
        SET status = 'RETRYING', failure_reason = failure_reason, updated_at = ?, retry_count = COALESCE(retry_count, 0) + 1
        WHERE id = ?
    ''', (datetime.now().isoformat(), id))

    conn.commit()
    conn.close()

    threading.Thread(
        target=process_message_internal,
        args=(id,),
        daemon=True
    ).start()

    return jsonify({
        "id": id,
        "status": "RETRYING"
    })
# --------------------------------------------------------------------------------------------
#Delete Functionality
INTEGRATION_REVIEW_ERRORS = [
    "schema mismatch",
    "mapping error",
    "invalid data structure",
    "missing required field",
    "invalid code"
]

def can_delete(message):
    retry_count = message["retry_count"] or 0
    failure_reason = (message["failure_reason"] or "").lower()
    user_created = message["user_created"] or 0

    needs_review = any(err in failure_reason for err in INTEGRATION_REVIEW_ERRORS)
    return retry_count > 3 or needs_review or user_created

@app.route('/messages/<int:id>', methods=['DELETE'])
def delete_message(id):
    conn = get_db_connection()
    message = conn.execute(
        'SELECT * FROM messages WHERE id = ?', (id,)
    ).fetchone()

    if not message:
        return jsonify({"error": "Message not found"}), 404

    if not can_delete(message):
        return jsonify({
            "error": "Deletion not allowed: requires > 3 retries or integration-level failure."
        }), 403

    conn.execute('DELETE FROM messages WHERE id = ?', (id,))
    conn.commit()
    conn.close()

    return jsonify({"success": True})
# --------------------------------------------------------------------------------------------
if __name__ == '__main__':
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=auto_generate, daemon=True).start()

    app.run(debug=True)
