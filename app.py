from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# 🔹 MongoDB connection
# For local MongoDB:
# client = MongoClient("mongodb://localhost:27017")

# For MongoDB Atlas (replace URI)
client = MongoClient("mongodb+srv://school_students:Tushar2007@cluster0.upoywck.mongodb.net/school_erp?retryWrites=true&w=majority")

db = client.library
books_col = db.books
teachers_col = client.school_erp.teachers
students_col = client.school_erp.students
records_col = db.records
incidents_col = db.book_incidents
audit_logs_col = db.audit_logs


# 🔹 Helper: convert Mongo _id to string-safe
def clean_book(b):
    b["_id"] = str(b["_id"])
    return b


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_audit_log(action, details=None, actor_id="LIBRARIAN"):
    if details is None:
        details = {}
    audit_logs_col.insert_one({
        "action": str(action or "").strip().upper(),
        "module": infer_module(action),
        "actor_id": str(actor_id or "LIBRARIAN").strip(),
        "details": details,
        "timestamp": now_str()
    })


def find_book_by_code(code):
    raw = str(code or "").strip()
    if not raw:
        return None
    doc = books_col.find_one({"code": raw})
    if doc:
        return doc
    if raw.isdigit():
        return books_col.find_one({"code": int(raw)})
    return None


def infer_module(action):
    a = str(action or "").upper()
    if "INCIDENT" in a:
        return "LOST_DAMAGE"
    if "TEACHER" in a:
        return "ISSUE_TEACHER"
    if "ISSUE_STUDENT" in a or "RETURN" in a:
        return "ISSUE_RETURN"
    if "BOOK_" in a:
        return "BOOKS"
    return "SYSTEM"


# ==============================
# 📚 GET ALL BOOKS
# ==============================
@app.route("/api/books", methods=["GET"])
def get_books():
    books = list(books_col.find({}, {"_id": 0}))
    return jsonify(books)

@app.route("/api/students/admission/<admission_no>", methods=["GET"])
def get_student(admission_no):
    student = students_col.find_one(
        {"admission_no": admission_no},
        {"_id": 0}
    )
    if not student:
        return jsonify({"error": "Student not found"}), 404
    return jsonify(student)


@app.route("/api/teachers/id/<teacher_id>", methods=["GET"])
def get_teacher_by_employee_id(teacher_id):
    raw = str(teacher_id).strip()
    normalized = raw.zfill(4) if raw.isdigit() and len(raw) <= 4 else raw
    q = {
        "$or": [
            {"employee_id": raw},
            {"employee_id": normalized},
            {"teacher_code": raw},
            {"teacher_code": normalized}
        ]
    }
    t = teachers_col.find_one(q, {"_id": 0})
    if not t:
        return jsonify({"error": "Teacher not found"}), 404
    return jsonify({
        "teacher_name": t.get("teacher_name", ""),
        "employee_id": t.get("employee_id", ""),
        "teacher_code": t.get("teacher_code", ""),
        "designation": t.get("designation", "")
    })

# ==============================
# ➕ ADD SINGLE BOOK
# ==============================
@app.route("/api/books", methods=["POST"])
def add_book():
    data = request.json

    if not data.get("code") or not data.get("name"):
        return jsonify({"error": "Book code and name required"}), 400

    existing = books_col.find_one({"code": data["code"]})

    if existing:
        books_col.update_one(
            {"code": data["code"]},
            {"$inc": {"copies": int(data.get("copies", 1))}}
        )
        add_audit_log("BOOK_STOCK_UPDATE", {
            "code": data["code"],
            "added_copies": int(data.get("copies", 1))
        })
    else:
        book = {
            "code": data["code"],
            "author": data.get("author", ""),
            "name": data["name"],
            "publisher": data.get("publisher", ""),
            "price": data.get("price", ""),
            "pages": data.get("pages", ""),
            "class": data.get("class", ""),
            "copies": int(data.get("copies", 1)),
            "issuedCount": 0
        }
        books_col.insert_one(book)
        add_audit_log("BOOK_ADD", {
            "code": data["code"],
            "name": data["name"],
            "copies": int(data.get("copies", 1))
        })

    return jsonify({"success": True})

@app.route("/api/issue", methods=["POST"])
def issue_book():
    data = request.json
    code = data.get("code")
    admission_no = data.get("admission_no")
    days = int(data.get("days", 7))

    if not code or not admission_no:
        return jsonify({"error": "Missing data"}), 400

    book = books_col.find_one({"code": code})
    if not book or book["copies"] <= 0:
        return jsonify({"error": "Book not available"}), 400

    student = students_col.find_one({"admission_no": admission_no})
    if not student:
        return jsonify({"error": "Student not found"}), 404

    # prevent duplicate issue
    existing = records_col.find_one({
        "code": code,
        "admission_no": admission_no,
        "status": "ISSUED"
    })
    if existing:
        return jsonify({"error": "Book already issued"}), 400

    issue_date = datetime.now()
    due_date = issue_date + timedelta(days=days)

    record = {
        "code": code,
        "bookName": book["name"],
        "admission_no": admission_no,
        "student_name": student["student_name"],
        "issueDate": issue_date.strftime("%Y-%m-%d"),
        "dueDate": due_date.strftime("%Y-%m-%d"),
        "returnDate": None,
        "status": "ISSUED",
        "fine": 0
    }

    records_col.insert_one(record)

    books_col.update_one(
        {"code": code},
        {
            "$inc": {
                "copies": -1,
                "issuedCount": 1
            }
        }
    )
    add_audit_log("BOOK_ISSUE_STUDENT", {
        "code": code,
        "bookName": book["name"],
        "admission_no": admission_no,
        "student_name": student.get("student_name", ""),
        "days": days
    })

    return jsonify({"message": "Book issued successfully ✅"})

@app.route("/api/issue/teacher", methods=["POST"])
def issue_book_teacher():
    data = request.json

    code = data.get("code")
    teacher_id = str(data.get("teacher_id"))
    teacher_name = data.get("teacher_name")
    days = int(data.get("days", 30))

    if not code or not teacher_id or not teacher_name:
        return jsonify({"error": "Missing teacher data"}), 400

    book = books_col.find_one({"code": code})
    if not book or book["copies"] <= 0:
        return jsonify({"error": "Book not available"}), 400

    # prevent duplicate issue
    existing = records_col.find_one({
        "code": code,
        "teacher_id": teacher_id,
        "status": "ISSUED"
    })
    if existing:
        return jsonify({"error": "Book already issued to this teacher"}), 400

    issue_date = datetime.now()
    due_date = issue_date + timedelta(days=days)

    record = {
        "code": code,
        "bookName": book["name"],

        "teacher_id": teacher_id,
        "teacher_name": teacher_name,   # ✅ STORE NAME

        "issueDate": issue_date.strftime("%Y-%m-%d"),
        "dueDate": due_date.strftime("%Y-%m-%d"),
        "returnDate": None,
        "status": "ISSUED",
        "fine": 0,
        "who_type": "TEACHER"
    }

    records_col.insert_one(record)

    books_col.update_one(
        {"code": code},
        {"$inc": {"copies": -1, "issuedCount": 1}}
    )
    add_audit_log("BOOK_ISSUE_TEACHER", {
        "code": code,
        "bookName": book["name"],
        "teacher_id": teacher_id,
        "teacher_name": teacher_name,
        "days": days
    })

    return jsonify({"message": "Book issued to teacher successfully ✅"})


@app.route("/api/return", methods=["POST"])
def return_book():
    try:
        code = int(request.json.get("code"))  # convert to number
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid book code"}), 400

    record = records_col.find_one({
        "code": code,
        "status": "ISSUED"
    })

    if not record:
        return jsonify({"error": "No issued record found"}), 404

    return_date = datetime.now()
    due_date = datetime.strptime(record["dueDate"], "%Y-%m-%d")

    late_days = (return_date - due_date).days
    fine = max(0, late_days * 5)  # ₹5 per day

    records_col.update_one(
        {"_id": record["_id"]},
        {"$set": {
            "status": "RETURNED",
            "returnDate": return_date.strftime("%Y-%m-%d"),
            "fine": fine
        }}
    )

    books_col.update_one(
        {"code": code},
        {
            "$inc": {
                "copies": 1,
                "issuedCount": -1
            }
        }
    )
    add_audit_log("BOOK_RETURN", {
        "code": code,
        "status_before": "ISSUED",
        "status_after": "RETURNED",
        "fine": fine,
        "returnDate": return_date.strftime("%Y-%m-%d")
    })

    return jsonify({
        "message": "Book returned successfully ✅",
        "fine": fine
    })
@app.route("/api/records", methods=["GET"])
def get_records():
    records = list(records_col.find({}, {"_id": 0}))
    return jsonify(records)


@app.route("/api/records/student/<admission_no>", methods=["GET"])
def get_student_records(admission_no):
    adm = str(admission_no or "").strip()
    if not adm:
        return jsonify({"success": False, "error": "Admission number required"}), 400

    rows = list(records_col.find({"admission_no": adm}, {"_id": 0}))
    out = []
    for r in rows:
        status = str(r.get("status", "")).upper()
        fine = int(r.get("fine", 0) or 0)
        if status in {"LOST", "DAMAGED", "MISPLACED"}:
            reason = r.get("incident_note") or status.title()
        elif status == "RETURNED" and fine > 0:
            reason = "Late return"
        else:
            reason = ""

        out.append({
            "code": r.get("code", ""),
            "bookName": r.get("bookName", ""),
            "issueDate": r.get("issueDate", ""),
            "dueDate": r.get("dueDate", ""),
            "returnDate": r.get("returnDate", ""),
            "status": r.get("status", ""),
            "fine": fine,
            "fine_reason": reason
        })

    # Include incident-based fines even when no matching issued record exists.
    # This ensures Lost/Damaged/Misplaced fines always appear in student portal.
    incidents = list(incidents_col.find({"admission_no": adm}, {"_id": 0}))
    existing_keys = {
        (
            str(x.get("code", "")),
            str(x.get("status", "")).upper(),
            str(x.get("returnDate", "") or "")
        )
        for x in out
    }
    for inc in incidents:
        inc_status = str(inc.get("incident_type", "")).upper()
        inc_date = str(inc.get("incident_date", "") or "")
        key = (str(inc.get("code", "")), inc_status, inc_date)
        if key in existing_keys:
            continue
        out.append({
            "code": inc.get("code", ""),
            "bookName": inc.get("bookName", ""),
            "issueDate": "",
            "dueDate": "",
            "returnDate": inc_date,
            "status": inc_status,
            "fine": int(inc.get("fine", 0) or 0),
            "fine_reason": inc.get("remarks", "") or inc_status.title()
        })

    out.sort(
        key=lambda x: (
            str(x.get("issueDate", "") or x.get("returnDate", "") or ""),
            str(x.get("code", ""))
        ),
        reverse=True
    )
    return jsonify({"success": True, "admission_no": adm, "records": out})
# 🔹 GET TEACHER-ISSUED BOOK BY CODE
@app.route("/api/issue/teacher/by-book/<code>", methods=["GET"])
def get_teacher_issue_by_book(code):
    try:
        code = int(code)  # convert code to number if needed
    except ValueError:
        return jsonify({"error": "Invalid book code"}), 400

    record = records_col.find_one({
        "code": code,
        "status": "ISSUED",
        "who_type": "TEACHER"
    }, {"_id": 0})

    if not record:
        return jsonify({"error": "Not issued to teacher"}), 404

    return jsonify({
        "code": record["code"],
        "teacher_name": record["teacher_name"],
        "teacher_id": record["teacher_id"],
        "issue_date": record["issueDate"],
        "due_date": record["dueDate"]
    })

# ==============================
# ❌ DELETE BOOK
# ==============================
@app.route("/api/books/<code>", methods=["DELETE"])
def delete_book(code):
    books_col.delete_one({"code": code})
    add_audit_log("BOOK_DELETE", {"code": code})
    return jsonify({"success": True})


# ==============================
# 🧹 CLEAR ALL BOOKS
# ==============================
@app.route("/api/books", methods=["DELETE"])
def clear_books():
    books_col.delete_many({})
    add_audit_log("BOOK_CLEAR_ALL", {})
    return jsonify({"success": True})


# ==============================
# 📥 BULK UPLOAD (EXCEL IMPORT)
# ==============================
@app.route("/api/books/bulk", methods=["POST"])
def bulk_upload():
    books = request.json

    for b in books:
        if not b.get("code") or not b.get("name"):
            continue

        existing = books_col.find_one({"code": b["code"]})
        if existing:
            books_col.update_one(
                {"code": b["code"]},
                {"$inc": {"copies": int(b.get("copies", 1))}}
            )
        else:
            books_col.insert_one({
                "code": b["code"],
                "author": b.get("author", ""),
                "name": b["name"],
                "publisher": b.get("publisher", ""),
                "price": b.get("price", ""),
                "pages": b.get("pages", ""),
                "class": b.get("class", ""),
                "copies": int(b.get("copies", 1)),
                "issuedCount": 0
            })

    return jsonify({"success": True})


@app.route("/api/incidents", methods=["POST"])
def create_incident():
    data = request.get_json() or {}
    code = str(data.get("code", "")).strip()
    incident_type = str(data.get("incident_type", "")).strip().upper()
    responsible_type = str(data.get("responsible_type", "")).strip().upper()
    admission_no = str(data.get("admission_no", "")).strip()
    teacher_id = str(data.get("teacher_id", "")).strip()
    remarks = str(data.get("remarks", "")).strip()
    actor_id = str(data.get("actor_id", "LIBRARIAN")).strip() or "LIBRARIAN"

    if not code:
        return jsonify({"success": False, "error": "Book code required"}), 400
    if incident_type not in {"LOST", "DAMAGED", "MISPLACED"}:
        return jsonify({"success": False, "error": "Invalid incident type"}), 400
    if responsible_type not in {"STUDENT", "TEACHER", "SCHOOL"}:
        return jsonify({"success": False, "error": "Invalid responsible type"}), 400
    if responsible_type == "STUDENT" and not admission_no:
        return jsonify({"success": False, "error": "Student admission number required"}), 400
    if responsible_type == "TEACHER" and not teacher_id:
        return jsonify({"success": False, "error": "Teacher ID required"}), 400

    book = find_book_by_code(code)
    book_name = (book or {}).get("name", "")

    fine = 1000
    incident_date = datetime.now().strftime("%Y-%m-%d")

    # If incident is linked to an issued record, close the issued record.
    code_filters = [code]
    if code.isdigit():
        code_filters.append(int(code))
    record_query = {"code": {"$in": code_filters}, "status": "ISSUED"}
    if responsible_type == "STUDENT":
        record_query["admission_no"] = admission_no
    elif responsible_type == "TEACHER":
        record_query["teacher_id"] = teacher_id
        record_query["who_type"] = "TEACHER"

    linked_record = None
    if responsible_type in {"STUDENT", "TEACHER"}:
        linked_record = records_col.find_one(record_query)
        if linked_record:
            records_col.update_one(
                {"_id": linked_record["_id"]},
                {"$set": {
                    "status": incident_type,
                    "returnDate": incident_date,
                    "fine": fine,
                    "incident_note": remarks
                }}
            )
            books_col.update_one({"code": linked_record.get("code")}, {"$inc": {"issuedCount": -1}})

    # If school is responsible, it means a library-stock copy is affected.
    if responsible_type == "SCHOOL":
        target = find_book_by_code(code)
        if not target:
            return jsonify({"success": False, "error": "Book not found"}), 404
        if int(target.get("copies", 0)) <= 0:
            return jsonify({"success": False, "error": "No available copies to mark incident"}), 400
        books_col.update_one({"_id": target["_id"]}, {"$inc": {"copies": -1}})

    incident_doc = {
        "code": code,
        "bookName": book_name,
        "incident_type": incident_type,
        "responsible_type": responsible_type,
        "admission_no": admission_no,
        "teacher_id": teacher_id,
        "fine": fine,
        "remarks": remarks,
        "incident_date": incident_date,
        "created_at": now_str(),
        "linked_issue_record": bool(linked_record)
    }
    incidents_col.insert_one(incident_doc)

    add_audit_log("BOOK_INCIDENT_CREATE", {
        "code": code,
        "bookName": book_name,
        "incident_type": incident_type,
        "responsible_type": responsible_type,
        "admission_no": admission_no,
        "teacher_id": teacher_id,
        "fine": fine
    }, actor_id=actor_id)

    return jsonify({"success": True, "message": "Incident saved successfully", "fine": fine})


@app.route("/api/incidents", methods=["GET"])
def list_incidents():
    rows = list(incidents_col.find({}, {"_id": 0}).sort("created_at", -1))
    return jsonify(rows)


@app.route("/api/audit-logs", methods=["GET"])
def list_audit_logs():
    limit = request.args.get("limit", "50")
    page = request.args.get("page", "1")
    module = str(request.args.get("module", "ALL")).strip().upper()
    try:
        limit = max(1, min(1000, int(limit)))
    except Exception:
        limit = 50
    try:
        page = max(1, int(page))
    except Exception:
        page = 1

    q = {}
    if module and module != "ALL":
        q["module"] = module

    total = audit_logs_col.count_documents(q)
    rows = list(
        audit_logs_col.find(q, {"_id": 0})
        .sort("timestamp", -1)
        .skip((page - 1) * limit)
        .limit(limit)
    )
    return jsonify({
        "success": True,
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": (total + limit - 1) // limit if total else 1,
        "rows": rows
    })
# ==============================
# 🔍 GET ISSUED BOOK BY CODE
# ==============================
@app.route("/api/issue/by-book/<code>", methods=["GET"])
def get_issue_by_book(code):
    try:
        code = int(code)  # convert URL param to number
    except ValueError:
        return jsonify({"error": "Invalid book code"}), 400

    record = records_col.find_one({
        "code": code,
        "status": "ISSUED"
    }, {"_id": 0})

    if not record:
        return jsonify({"error": "Not issued"}), 404

    return jsonify({
        "code": record["code"],
        "student_name": record["student_name"],
        "admission_no": record["admission_no"],
        "issue_date": record["issueDate"],
        "due_date": record["dueDate"]
    })
    
@app.route("/", methods=["GET"])
def home():
    return "LIBRARY Backend Running", 200

# ==============================
# 🚀 RUN SERVER
# ==============================
if __name__ == "__main__":
    app.run(debug=True)
