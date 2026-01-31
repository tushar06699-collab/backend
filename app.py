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


# 🔹 Helper: convert Mongo _id to string-safe
def clean_book(b):
    b["_id"] = str(b["_id"])
    return b


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

    return jsonify({
        "message": "Book returned successfully ✅",
        "fine": fine
    })
@app.route("/api/records", methods=["GET"])
def get_records():
    records = list(records_col.find({}, {"_id": 0}))
    return jsonify(records)
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
    return jsonify({"success": True})


# ==============================
# 🧹 CLEAR ALL BOOKS
# ==============================
@app.route("/api/books", methods=["DELETE"])
def clear_books():
    books_col.delete_many({})
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
