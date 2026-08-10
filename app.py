from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_file
)

from flask import send_from_directory
from PyPDF2 import PdfReader
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pymongo import MongoClient
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from bson.objectid import ObjectId
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from io import BytesIO
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
)
import os
import uuid
import re
import random

# -------------------------------------------------
# Load Environment Variables
# -------------------------------------------------
load_dotenv()

# -------------------------------------------------
# Create Flask App (single clean initialization)
# -------------------------------------------------
app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER")
app.config["MAIL_PORT"] = int(os.getenv("MAIL_PORT"))
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USE_SSL"] = False
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")

print("=" * 50)
print("MAIL_SERVER  :", app.config["MAIL_SERVER"])
print("MAIL_PORT    :", app.config["MAIL_PORT"])
print("MAIL_USERNAME:", app.config["MAIL_USERNAME"])
print("PASSWORD SET :", app.config["MAIL_PASSWORD"] is not None)
print("=" * 50)

mail = Mail(app)

UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

ALLOWED_EXTENSIONS = {"pdf"}
def allowed_file(filename):
    return "." in filename and \
           filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# -------------------------------------------------
# Password Validation
# -------------------------------------------------
PASSWORD_REGEX = re.compile(
    r"^(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*(),.?\":{}|<>_\-+=~`\[\]/\\;']).{8,}$"
)

def is_valid_password(password):
    return bool(PASSWORD_REGEX.match(password))

PASSWORD_REQUIREMENTS_MESSAGE = (
    "Password must be at least 8 characters long and include "
    "one uppercase letter, one number, and one special character."
)

# -------------------------------------------------
# OTP Helper
# -------------------------------------------------
def generate_otp():
    return str(random.randint(100000, 999999))

OTP_VALIDITY_MINUTES = 10

# -------------------------------------------------
# MongoDB Connection
# -------------------------------------------------
client = MongoClient(os.getenv("MONGO_URI"))

db = client["ai_recruitment"]

users = db["users"]
jobs = db["jobs"]
applications = db["applications"]
applications_collection = db["applications"]
interviews = db["interviews"]
pending_registrations = db["pending_registrations"]
password_resets = db["password_resets"]
notifications = db["notifications"]
audit_logs = db["audit_logs"]

print("✅ MongoDB Connected Successfully!")


# -------------------------------------------------
# MAIL - Send Email Function
# -------------------------------------------------
def send_email(subject, recipient, body):
    print("=" * 60)
    print("EMAIL FUNCTION CALLED")
    print("Subject:", subject)
    print("Recipient:", repr(recipient))

    if not recipient:
        print("EMAIL FAILED: recipient is empty or None!")
        print("=" * 60)
        return

    try:
        msg = Message(
            subject,
            sender=app.config["MAIL_USERNAME"],
            recipients=[recipient]
        )
        msg.body = body
        mail.send(msg)
        print("EMAIL SENT SUCCESSFULLY")
        print("=" * 60)

    except Exception as e:
        print("EMAIL FAILED")
        print(type(e).__name__, ":", e)
        print("=" * 60)
        raise

# -------------------------------------------------
# AUDIT LOG HELPER
# -------------------------------------------------
def log_audit(actor_email, actor_role, action, details=""):
    audit_logs.insert_one({
        "actor_email": actor_email,
        "actor_role": actor_role,
        "action": action,
        "details": details,
        "timestamp": datetime.now()
    })

# -------------------------------------------------
# IN-DASHBOARD NOTIFICATION HELPER
# -------------------------------------------------
def add_notification(recipient_email, message, link=None):
    notifications.insert_one({
        "recipient_email": recipient_email,
        "message": message,
        "link": link,
        "is_read": False,
        "created_on": datetime.now()
    })

# -------------------------------------------------
# Inject notifications into every template automatically
# (usable in base.html as unread_notifications_count / recent_notifications)
# -------------------------------------------------
@app.context_processor
def inject_notifications():
    if "email" in session:
        unread_count = notifications.count_documents({
            "recipient_email": session["email"],
            "is_read": False
        })
        recent = list(
            notifications.find({"recipient_email": session["email"]})
            .sort("created_on", -1)
            .limit(6)
        )
        return dict(
            unread_notifications_count=unread_count,
            recent_notifications=recent
        )
    return dict(unread_notifications_count=0, recent_notifications=[])

# =================================================
# HELPER FUNCTIONS
# =================================================

def extract_resume_text(file_path):
    reader = PdfReader(file_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text
    return text

# =================================================
# CALCULATE MATCH
# =================================================
def calculate_match(job_description, resume_text, skills=""):
    jd_text = f"{job_description} {skills}".lower()
    resume_text = resume_text.lower()

    keywords = [
        "java", "python", "c", "c++", "javascript",
        "react", "node.js", "mongodb", "sql",
        "html", "css", "docker", "ci/cd"
    ]

    matched_keywords = 0
    total_keywords = 0

    for keyword in keywords:
        if keyword in jd_text:
            total_keywords += 1
            if keyword in resume_text:
                matched_keywords += 1

    skill_score = 0
    if total_keywords > 0:
        skill_score = (matched_keywords / total_keywords) * 100

    vectorizer = CountVectorizer(stop_words="english")
    vectors = vectorizer.fit_transform([jd_text, resume_text])
    similarity = cosine_similarity(vectors)[0][1] * 100

    final_score = (skill_score * 0.7) + (similarity * 0.3)

    return round(final_score, 2)

# =================================================
# FIND MISSING SKILLS
# =================================================
def find_missing_skills(job_description, resume_text, skills=""):
    jd_text = f"{job_description} {skills}".lower()
    resume_text = resume_text.lower()

    keywords = [
        "java", "python", "c", "c++", "javascript",
        "react", "node.js", "mongodb", "sql",
        "html", "css", "docker", "ci/cd"
    ]

    missing = []
    for keyword in keywords:
        if keyword in jd_text and keyword not in resume_text:
            missing.append(keyword)

    return missing

# =================================================
# HOME
# =================================================

@app.route("/")
def home():
    return render_template("index.html")

# =================================================
# REGISTER
# =================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        full_name = request.form["full_name"]
        email = request.form["email"].strip().lower()
        phone = request.form["phone"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]
        role = request.form["role"]

        if password != confirm_password:
            flash("Passwords do not match!", "danger")
            return redirect(url_for("register"))

        if not is_valid_password(password):
            flash(PASSWORD_REQUIREMENTS_MESSAGE, "danger")
            return redirect(url_for("register"))

        existing_user = users.find_one({"email": email})

        if existing_user:
            flash("Email already registered!", "danger")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        otp = generate_otp()
        otp_expiry = datetime.now() + timedelta(minutes=OTP_VALIDITY_MINUTES)

        pending_registrations.update_one(
            {"email": email},
            {
                "$set": {
                    "full_name": full_name,
                    "email": email,
                    "phone": phone,
                    "password": hashed_password,
                    "role": role,
                    "otp": otp,
                    "otp_expiry": otp_expiry
                }
            },
            upsert=True
        )

        send_email(
            "Verify Your Email - OTP",
            email,
            f"""Hello {full_name},

Thank you for registering with the AI Recruitment Automation Platform.

Your OTP for verifying your email address is:

{otp}

This OTP is valid for {OTP_VALIDITY_MINUTES} minutes.

Please enter this OTP on the verification page to complete your registration.

If you did not request this registration, please ignore this email.

Best Regards,
AI Recruitment Automation Platform
"""
        )

        session["pending_email"] = email

        flash(
            "An OTP has been sent to your email. Please verify to complete registration.",
            "info"
        )

        return redirect(url_for("verify_otp"))

    return render_template("register.html")

# =================================================
# VERIFY OTP (REGISTRATION)
# =================================================

@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():

    email = session.get("pending_email")

    if not email:
        flash("No pending registration found. Please register again.", "warning")
        return redirect(url_for("register"))

    if request.method == "POST":
        entered_otp = request.form.get("otp", "").strip()

        pending = pending_registrations.find_one({"email": email})

        if not pending:
            flash("Registration session expired. Please register again.", "danger")
            return redirect(url_for("register"))

        if datetime.now() > pending["otp_expiry"]:
            flash("OTP has expired. Please request a new one.", "danger")
            return redirect(url_for("verify_otp"))

        if entered_otp != pending["otp"]:
            flash("Incorrect OTP. Please try again.", "danger")
            return redirect(url_for("verify_otp"))

        users.insert_one({
            "full_name": pending["full_name"],
            "email": pending["email"],
            "phone": pending["phone"],
            "password": pending["password"],
            "role": pending["role"]
        })

        pending_registrations.delete_one({"email": email})
        session.pop("pending_email", None)

        log_audit(pending["email"], pending["role"], "Account Created", "Registered via OTP verification")

        flash("Email verified successfully! Your account has been created. Please login.", "success")
        return redirect(url_for("login"))

    return render_template("verify_otp.html", email=email, purpose="register")

# =================================================
# RESEND OTP (REGISTRATION)
# =================================================

@app.route("/resend_otp")
def resend_otp():

    email = session.get("pending_email")

    if not email:
        flash("No pending registration found. Please register again.", "warning")
        return redirect(url_for("register"))

    pending = pending_registrations.find_one({"email": email})

    if not pending:
        flash("Registration session expired. Please register again.", "danger")
        return redirect(url_for("register"))

    otp = generate_otp()
    otp_expiry = datetime.now() + timedelta(minutes=OTP_VALIDITY_MINUTES)

    pending_registrations.update_one(
        {"email": email},
        {"$set": {"otp": otp, "otp_expiry": otp_expiry}}
    )

    send_email(
        "Verify Your Email - OTP",
        email,
        f"""Hello {pending['full_name']},

Your new OTP for verifying your email address is:

{otp}

This OTP is valid for {OTP_VALIDITY_MINUTES} minutes.

Best Regards,
AI Recruitment Automation Platform
"""
    )

    flash("A new OTP has been sent to your email.", "info")
    return redirect(url_for("verify_otp"))

# =================================================
# LOGIN
# =================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if "email" in session:
        if session["role"] == "Recruiter":
            return redirect(url_for("recruiter_dashboard"))
        elif session["role"] == "Candidate":
            return redirect(url_for("candidate_dashboard"))
        elif session["role"] == "Admin":
            return redirect(url_for("admin_dashboard"))

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        user = users.find_one({"email": email})

        if not user:
            flash("User not found!", "danger")
            return redirect(url_for("login"))

        if not check_password_hash(user["password"], password):
            flash("Incorrect Password!", "danger")
            return redirect(url_for("login"))

        session["email"] = user["email"]
        session["name"] = user["full_name"]
        session["role"] = user["role"]

        log_audit(user["email"], user["role"], "Login")

        flash("Login Successful!", "success")

        if user["role"] == "Recruiter":
            return redirect(url_for("recruiter_dashboard"))
        elif user["role"] == "Candidate":
            return redirect(url_for("candidate_dashboard"))
        elif user["role"] == "Admin":
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid user role!", "danger")
            return redirect(url_for("login"))

    return render_template("login.html")

# =================================================
# FORGOT PASSWORD
# =================================================

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()

        user = users.find_one({"email": email})

        if not user:
            flash("No account found with that email address.", "danger")
            return redirect(url_for("forgot_password"))

        otp = generate_otp()
        otp_expiry = datetime.now() + timedelta(minutes=OTP_VALIDITY_MINUTES)

        password_resets.update_one(
            {"email": email},
            {
                "$set": {
                    "otp": otp,
                    "otp_expiry": otp_expiry,
                    "verified": False
                }
            },
            upsert=True
        )

        send_email(
            "Password Reset OTP",
            email,
            f"""Hello {user['full_name']},

We received a request to reset your password.

Your OTP for password reset is:

{otp}

This OTP is valid for {OTP_VALIDITY_MINUTES} minutes. If you did not request this, please ignore this email.

Best Regards,
AI Recruitment Automation Platform
"""
        )

        session["reset_email"] = email

        flash("An OTP has been sent to your email.", "info")
        return redirect(url_for("verify_reset_otp"))

    return render_template("forgot_password.html")

# =================================================
# VERIFY OTP (PASSWORD RESET)
# =================================================

@app.route("/verify_reset_otp", methods=["GET", "POST"])
def verify_reset_otp():

    email = session.get("reset_email")

    if not email:
        flash("No password reset request found. Please try again.", "warning")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        entered_otp = request.form.get("otp", "").strip()

        reset_doc = password_resets.find_one({"email": email})

        if not reset_doc:
            flash("Password reset session expired. Please try again.", "danger")
            return redirect(url_for("forgot_password"))

        if datetime.now() > reset_doc["otp_expiry"]:
            flash("OTP has expired. Please request a new one.", "danger")
            return redirect(url_for("forgot_password"))

        if entered_otp != reset_doc["otp"]:
            flash("Incorrect OTP. Please try again.", "danger")
            return redirect(url_for("verify_reset_otp"))

        password_resets.update_one(
            {"email": email},
            {"$set": {"verified": True}}
        )

        flash("OTP verified. You can now set a new password.", "success")
        return redirect(url_for("reset_password"))

    return render_template("verify_otp.html", email=email, purpose="reset")

# =================================================
# RESEND OTP (PASSWORD RESET)
# =================================================

@app.route("/resend_reset_otp")
def resend_reset_otp():

    email = session.get("reset_email")

    if not email:
        flash("No password reset request found. Please try again.", "warning")
        return redirect(url_for("forgot_password"))

    user = users.find_one({"email": email})

    if not user:
        flash("No account found with that email address.", "danger")
        return redirect(url_for("forgot_password"))

    otp = generate_otp()
    otp_expiry = datetime.now() + timedelta(minutes=OTP_VALIDITY_MINUTES)

    password_resets.update_one(
        {"email": email},
        {"$set": {"otp": otp, "otp_expiry": otp_expiry, "verified": False}},
        upsert=True
    )

    send_email(
        "Password Reset OTP",
        email,
        f"""Hello {user['full_name']},

Your new OTP for password reset is:

{otp}

This OTP is valid for {OTP_VALIDITY_MINUTES} minutes.

Best Regards,
AI Recruitment Automation Platform
"""
    )

    flash("A new OTP has been sent to your email.", "info")
    return redirect(url_for("verify_reset_otp"))

# =================================================
# RESET PASSWORD
# =================================================

@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():

    email = session.get("reset_email")

    if not email:
        flash("No password reset request found. Please try again.", "warning")
        return redirect(url_for("forgot_password"))

    reset_doc = password_resets.find_one({"email": email})

    if not reset_doc or not reset_doc.get("verified"):
        flash("Please verify the OTP before resetting your password.", "warning")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if new_password != confirm_password:
            flash("Passwords do not match!", "danger")
            return redirect(url_for("reset_password"))

        if not is_valid_password(new_password):
            flash(PASSWORD_REQUIREMENTS_MESSAGE, "danger")
            return redirect(url_for("reset_password"))

        hashed_password = generate_password_hash(new_password)

        users.update_one(
            {"email": email},
            {"$set": {"password": hashed_password}}
        )

        password_resets.delete_one({"email": email})
        session.pop("reset_email", None)

        flash("Password reset successfully! Please login with your new password.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html")


# =================================================
# RECRUITER DASHBOARD
# =================================================

@app.route("/recruiter_dashboard")
def recruiter_dashboard():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    return render_template(
        "recruiter_dashboard.html",
        name=session["name"]
    )


# =================================================
# CANDIDATE DASHBOARD
# =================================================

@app.route("/candidate_dashboard")
def candidate_dashboard():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Candidate":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    return render_template(
        "candidate_dashboard.html",
        name=session["name"]
    )

# =================================================
# CANDIDATE PROFILE
# =================================================

@app.route("/candidate_profile", methods=["GET", "POST"])
def candidate_profile():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Candidate":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":

        users.update_one(
            {"email": session["email"]},
            {
                "$set": {
                    "school_name": request.form.get("school_name", "").strip(),
                    "school_percentage": request.form.get("school_percentage", "").strip(),
                    "college": request.form.get("college", "").strip(),
                    "college_marks": request.form.get("college_marks", "").strip(),
                    "qualification": request.form.get("qualification", "").strip(),
                    "city": request.form.get("city", "").strip(),
                    "experience": request.form.get("experience", "").strip(),
                    "skills": request.form.get("skills", "").strip(),
                    "linkedin": request.form.get("linkedin", "").strip(),
                    "github": request.form.get("github", "").strip(),
                    "portfolio": request.form.get("portfolio", "").strip()
                }
            }
        )

        flash("Profile updated successfully!", "success")
        return redirect(url_for("candidate_profile"))

    candidate = users.find_one({"email": session["email"]})

    return render_template(
        "candidate_profile.html",
        candidate=candidate
    )

# =================================================
# VIEW JOB
# =================================================

@app.route("/view_jobs")
def view_jobs():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Candidate":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    keyword = request.args.get("keyword", "").strip()
    location = request.args.get("location", "").strip()

    query = {}

    if keyword:
        query["$or"] = [
            {"job_title": {"$regex": keyword, "$options": "i"}},
            {"company": {"$regex": keyword, "$options": "i"}},
            {"skills": {"$regex": keyword, "$options": "i"}}
        ]

    if location:
        query["location"] = {"$regex": location, "$options": "i"}

    all_jobs = list(jobs.find(query).sort("posted_on", -1))

    candidate = users.find_one({"email": session["email"]})

    resume_text = ""

    if candidate and "resume" in candidate:
        resume_path = os.path.join(
            app.config["UPLOAD_FOLDER"],
            candidate["resume"]
        )
        if os.path.exists(resume_path):
            resume_text = extract_resume_text(resume_path)

    for job in all_jobs:
        if resume_text and job.get("description"):
            job["recommendation_score"] = calculate_match(job["description"], resume_text)
        else:
            job["recommendation_score"] = 0

    all_jobs.sort(key=lambda j: j["recommendation_score"], reverse=True)

    return render_template(
        "view_jobs.html",
        jobs=all_jobs,
        keyword=keyword,
        location=location
    )

# =================================================
# MY APPLICATIONS
# =================================================

@app.route("/my_applications")
def my_applications():
    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Candidate":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    my_applications_list = list(
        applications_collection.find(
            {"candidate_email": session["email"]}
        ).sort("applied_on", -1)
    )

    return render_template(
        "my_applications.html",
        applications=my_applications_list
    )

# =================================================
# MY INTERVIEWS
# =================================================

@app.route("/my_interviews")
def my_interviews():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Candidate":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    candidate_interviews = interviews.find(
        {"candidate_email": session["email"]}
    ).sort("date", 1)

    return render_template(
        "my_interviews.html",
        interviews=candidate_interviews,
        name=session["name"]
    )

# =================================================
# APPLY JOB
# =================================================

@app.route("/apply_job/<job_id>", methods=["GET", "POST"])
def apply_job(job_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Candidate":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    candidate = users.find_one({"email": session["email"]})

    job = jobs.find_one({"_id": ObjectId(job_id)})

    if not job:
        flash("Job not found!", "danger")
        return redirect(url_for("view_jobs"))

    # ---- Require a complete academic profile before applying ----
    required_fields = ["school_name", "school_percentage", "college", "college_marks"]
    missing_fields = [
        f for f in required_fields
        if not candidate or not str(candidate.get(f, "")).strip()
    ]

    if missing_fields:
        flash(
            "Please complete your school and college details in your profile before applying.",
            "warning"
        )
        return redirect(url_for("candidate_profile"))

    if not candidate or "resume" not in candidate:
        flash("Please upload your resume (PDF) before applying!", "warning")
        return redirect(url_for("upload_resume"))

    existing_application = applications.find_one({
        "candidate_email": session["email"],
        "job_id": job_id
    })

    if existing_application:
        flash("You have already applied for this job.", "warning")
        return redirect(url_for("view_jobs"))

    resume_filename = candidate["resume"]

    resume_path = os.path.join(
        app.config["UPLOAD_FOLDER"],
        resume_filename
    )

    match_score = 0
    missing_skills = []
    if os.path.exists(resume_path) and resume_filename.lower().endswith(".pdf"):
        resume_text = extract_resume_text(resume_path)
        job_description = job["description"]
        match_score = calculate_match(
            job_description,
            resume_text,
            job.get("skills", "")
        )
        missing_skills = find_missing_skills(
            job_description,
            resume_text,
            job.get("skills", "")
        )

    application = {
        "job_id": job_id,
        "candidate_name": candidate["full_name"],
        "candidate_email": candidate["email"],
        "job_title": job["job_title"],
        "company": job["company"],
        "phone": candidate.get("phone", ""),
        "city": candidate.get("city", ""),
        "qualification": candidate.get("qualification", ""),
        "school_name": candidate.get("school_name", ""),
        "school_percentage": candidate.get("school_percentage", ""),
        "college": candidate.get("college", ""),
        "college_marks": candidate.get("college_marks", ""),
        "experience": candidate.get("experience", ""),
        "skills": candidate.get("skills", ""),
        "linkedin": candidate.get("linkedin", ""),
        "github": candidate.get("github", ""),
        "portfolio": candidate.get("portfolio", ""),
        "resume": resume_filename,
        "score": match_score,
        "missing_skills": missing_skills,
        "status": "Pending",
        "applied_on": datetime.now()
    }

    applications.insert_one(application)

    log_audit(
        candidate["email"], "Candidate", "Applied to Job",
        f"Applied for '{job['job_title']}' at {job['company']}"
    )

    add_notification(
        job["posted_by"],
        f"{candidate['full_name']} applied for {job['job_title']} (Match: {match_score}%)",
        link=url_for("manage_applications")
    )

    send_email(
        f"Application Received - {job['job_title']}",
        session["email"],
        f"""Hello {session['name']},

Thank you for applying for the position of {job['job_title']} at {job['company']}.

We have successfully received your application, and our recruitment team is now reviewing your profile and resume.

--------------------------------
Position: {job['job_title']}
AI Match Score: {match_score}%
Application Status: Received
--------------------------------

If your profile matches our current requirements, we will reach out to you regarding the next steps in the recruitment process.

Thank you for your interest in joining {job['company']}.

Best Regards,
{job['company']}
"""
    )

    flash(
        f"Application submitted successfully! AI Match Score: {match_score}%",
        "success"
    )

    return redirect(url_for("my_applications"))
# =================================================
# POST JOB
# =================================================

@app.route("/post_job", methods=["GET", "POST"])
def post_job():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":

        job_title   = request.form.get("job_title", "").strip()
        company     = request.form.get("company", "").strip()
        location    = request.form.get("location", "").strip()
        salary      = request.form.get("salary", "").strip()
        skills      = request.form.get("skills", "").strip()
        description = request.form.get("description", "").strip()

        if not job_title or not company or not location or not salary or not skills or not description:
            flash("All fields are required. Please fill in every field.", "danger")
            return redirect(url_for("post_job"))

        job = {
            "job_title"      : job_title,
            "company"        : company,
            "location"       : location,
            "salary"         : salary,
            "skills"         : skills,
            "description"    : description,
            "posted_by"      : session["email"],
            "recruiter_name" : session["name"],
            "posted_on"      : datetime.now()
        }

        jobs.insert_one(job)

        log_audit(
            session["email"], "Recruiter", "Posted Job",
            f"Posted '{job_title}' at {company}"
        )

        flash("Job Posted Successfully!", "success")

        return redirect(url_for("recruiter_dashboard"))

    return render_template("post_job.html")
# =================================================
# MANAGE JOBS
# =================================================

@app.route("/manage_jobs")
def manage_jobs():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    recruiter_jobs = list(
        jobs.find(
            {"posted_by": session["email"]}
        ).sort("posted_on", -1)
    )

    return render_template(
        "manage_jobs.html",
        jobs=recruiter_jobs
    )

# =================================================
# MANAGE APPLICATIONS
# =================================================

@app.route("/manage_applications")
def manage_applications():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    recruiter_jobs = jobs.find(
        {"posted_by": session["email"]}
    )

    recruiter_job_ids = []

    for job in recruiter_jobs:
        recruiter_job_ids.append(str(job["_id"]))

    recruiter_applications = list(applications.find(
        {
            "job_id": {
                "$in": recruiter_job_ids
            }
        }
    ).sort("score", -1))

    return render_template(
        "manage_applications.html",
        applications=recruiter_applications
    )
# =================================================
# ACCEPT APPLICATION
# =================================================

@app.route("/accept_application/<application_id>")
def accept_application(application_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    applications.update_one(
        {"_id": ObjectId(application_id)},
        {"$set": {"status": "Accepted"}}
    )

    application = applications.find_one({
        "_id": ObjectId(application_id)
    })

    log_audit(
        session["email"], "Recruiter", "Accepted Application",
        f"Accepted {application['candidate_name']} for '{application['job_title']}'"
    )

    add_notification(
        application["candidate_email"],
        f"Your application for {application['job_title']} has been accepted!",
        link=url_for("my_applications")
    )

    send_email(
        f"Application Accepted - {application['job_title']}",
        application["candidate_email"],
        f"""Dear {application['candidate_name']},

Congratulations! We are pleased to inform you that your application for the position of {application['job_title']} has been accepted after a thorough review of your profile, skills, and qualifications.

Our recruitment team was genuinely impressed by your suitability for this role, and your application has successfully cleared the initial screening stage.

--------------------------------
Position: {application['job_title']}
Company: {application['company']}
Application Status: Accepted
Interview Schedule: To be announced
--------------------------------

We will reach out to you shortly with further details regarding your interview. Please keep an eye on your email in the coming days and ensure your contact information is up to date.

There is nothing further you need to do at this moment - we simply ask for a little patience as we coordinate the next steps with our hiring team.

Thank you once again for your interest in joining {application['company']}. We look forward to speaking with you soon.

Best Regards,
{application['company']}
"""
    )

    flash("Candidate Accepted Successfully!", "success")

    return redirect(url_for("manage_applications"))
# =================================================
# REJECT APPLICATION
# =================================================

@app.route("/reject_application/<application_id>")
def reject_application(application_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    applications.update_one(
        {"_id": ObjectId(application_id)},
        {"$set": {"status": "Rejected"}}
    )

    application = applications.find_one({
        "_id": ObjectId(application_id)
    })

    log_audit(
        session["email"], "Recruiter", "Rejected Application",
        f"Rejected {application['candidate_name']} for '{application['job_title']}'"
    )

    add_notification(
        application["candidate_email"],
        f"There's an update on your application for {application['job_title']}.",
        link=url_for("my_applications")
    )

    send_email(
        f"Application Update - {application['job_title']}",
        application["candidate_email"],
        f"""Dear {application['candidate_name']},

Thank you for taking the time to apply for the position of {application['job_title']} at {application['company']}, and for sharing your skills and experience with us.

After careful consideration, we have decided to move forward with candidates whose profiles more closely match our current requirements for this particular role. This was not an easy decision, as we received applications from many talented individuals.

Please don't be discouraged - this outcome reflects the specific needs of this role at this time, and not the value of your skills or potential. We encourage you to apply again for future opportunities that match your profile.

We sincerely appreciate your interest in {application['company']} and wish you continued success in your career.

Best Regards,
{application['company']}
"""
    )

    flash("Candidate Rejected Successfully!", "success")

    return redirect(url_for("manage_applications"))

# =================================================
# EDIT JOB
# =================================================

@app.route("/edit_job/<job_id>", methods=["GET", "POST"])
def edit_job(job_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    job = jobs.find_one({
        "_id": ObjectId(job_id),
        "posted_by": session["email"]
    })

    if not job:
        flash("Job not found!", "danger")
        return redirect(url_for("manage_jobs"))

    if request.method == "POST":

        updated_job = {
            "job_title": request.form.get("job_title").strip(),
            "company": request.form.get("company").strip(),
            "location": request.form.get("location").strip(),
            "salary": request.form.get("salary").strip(),
            "skills": request.form.get("skills").strip(),
            "description": request.form.get("description").strip()
        }

        jobs.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": updated_job}
        )

        log_audit(
            session["email"], "Recruiter", "Edited Job",
            f"Edited '{updated_job['job_title']}' (Job ID: {job_id})"
        )

        flash("Job updated successfully!", "success")

        return redirect(url_for("manage_jobs"))

    return render_template(
        "edit_job.html",
        job=job
    )
# =================================================
# DELETE JOB
# =================================================

@app.route("/delete_job/<job_id>")
def delete_job(job_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    job = jobs.find_one({"_id": ObjectId(job_id), "posted_by": session["email"]})

    jobs.delete_one({
        "_id": ObjectId(job_id),
        "posted_by": session["email"]
    })

    if job:
        log_audit(
            session["email"], "Recruiter", "Deleted Job",
            f"Deleted '{job['job_title']}' (Job ID: {job_id})"
        )

    flash("Job deleted successfully!", "success")

    return redirect(url_for("manage_jobs"))
# =================================================
# UPLOAD RESUME
# =================================================

@app.route("/upload_resume", methods=["GET", "POST"])
def upload_resume():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Candidate":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":

        if "resume" not in request.files:
            flash("No file selected.", "danger")
            return redirect(url_for("upload_resume"))

        file = request.files["resume"]

        if file.filename == "":
            flash("Please select a resume.", "warning")
            return redirect(url_for("upload_resume"))

        if file and allowed_file(file.filename):

            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

            filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"

            file.save(
                os.path.join(
                    app.config["UPLOAD_FOLDER"],
                    filename
                )
            )

            users.update_one(
                {"email": session["email"]},
                {"$set": {"resume": filename}}
            )

            flash("Resume uploaded successfully!", "success")
            return redirect(url_for("candidate_dashboard"))

        flash("Only PDF files are allowed.", "danger")

    return render_template("upload_resume.html")


# =================================================
# VIEW RESUME FILE
# =================================================

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# =================================================
# RECRUITER ANALYTICS (with chart data)
# =================================================

@app.route("/analytics")
def analytics():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    recruiter_email = session["email"]

    recruiter_job_docs = list(jobs.find({"posted_by": recruiter_email}))
    recruiter_job_ids = [str(job["_id"]) for job in recruiter_job_docs]

    total_jobs = len(recruiter_job_docs)

    total_applications = applications.count_documents({
        "job_id": {"$in": recruiter_job_ids}
    })

    accepted = applications.count_documents({
        "job_id": {"$in": recruiter_job_ids},
        "status": "Accepted"
    })

    rejected = applications.count_documents({
        "job_id": {"$in": recruiter_job_ids},
        "status": "Rejected"
    })

    pending = applications.count_documents({
        "job_id": {"$in": recruiter_job_ids},
        "status": "Pending"
    })

    scores = [
        a.get("score", 0)
        for a in applications.find({"job_id": {"$in": recruiter_job_ids}})
    ]

    if scores:
        average_score = round(sum(scores) / len(scores), 2)
        highest_score = max(scores)
        lowest_score = min(scores)
    else:
        average_score = 0
        highest_score = 0
        lowest_score = 0

    top_candidates = applications.find(
        {"job_id": {"$in": recruiter_job_ids}}
    ).sort("score", -1).limit(5)

    # ---- Data for "Applications per job" chart ----
    applications_per_job = []
    for job in recruiter_job_docs:
        count = applications.count_documents({"job_id": str(job["_id"])})
        applications_per_job.append({
            "job_title": job["job_title"],
            "count": count
        })

    return render_template(
        "analytics.html",
        total_jobs=total_jobs,
        total_applications=total_applications,
        accepted=accepted,
        rejected=rejected,
        pending=pending,
        average_score=average_score,
        highest_score=highest_score,
        lowest_score=lowest_score,
        top_candidates=top_candidates,
        applications_per_job=applications_per_job
    )

# =================================================
# SCHEDULE INTERVIEW
# =================================================

@app.route("/schedule_interview/<application_id>", methods=["GET", "POST"])
def schedule_interview(application_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    application = applications.find_one({
        "_id": ObjectId(application_id)
    })

    if not application:
        flash("Application not found!", "danger")
        return redirect(url_for("manage_applications"))

    if request.method == "POST":

        interview = {
            "application_id": application["_id"],
            "candidate_email": application["candidate_email"],
            "candidate_name": application["candidate_name"],
            "job_title": application["job_title"],
            "date": request.form.get("date"),
            "time": request.form.get("time"),
            "mode": request.form.get("mode"),
            "meeting_link": request.form.get("meeting_link"),
            "scheduled_by": session["email"]
        }

        interviews.insert_one(interview)

        log_audit(
            session["email"], "Recruiter", "Scheduled Interview",
            f"Scheduled interview for {application['candidate_name']} - '{application['job_title']}' on {interview['date']} {interview['time']}"
        )

        add_notification(
            application["candidate_email"],
            f"Your interview for {application['job_title']} has been scheduled on {interview['date']} at {interview['time']}.",
            link=url_for("my_interviews")
        )

        send_email(
            f"Interview Scheduled - {application['job_title']}",
            application["candidate_email"],
            f"""Dear {application['candidate_name']},

Great news! Following your accepted application, we are pleased to invite you to the next stage of our recruitment process for the position of {application['job_title']}.

Your interview has been scheduled with the following details:

--------------------------------
Position: {application['job_title']}
Company: {application['company']}
Date: {request.form.get('date')}
Time: {request.form.get('time')}
Mode: {request.form.get('mode')}
Meeting Link: {request.form.get('meeting_link')}
--------------------------------

Please join the interview at least 10 minutes before the scheduled time, and make sure your internet connection, camera, and microphone are working properly beforehand. If the interview mode is online, we recommend testing the meeting link in advance.

This is an important opportunity for us to learn more about you, and for you to learn more about the role and about {application['company']}. Feel free to prepare any questions you may have about the position or our organization.

We look forward to speaking with you and wish you the very best for your interview.

Best Regards,
{application['company']}
"""
        )

        flash("Interview Scheduled Successfully!", "success")

        return redirect(url_for("manage_applications"))

    return render_template(
        "schedule_interview.html",
        application=application
    )

# =================================================
# NOTIFICATIONS
# =================================================

@app.route("/notifications")
def view_notifications():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    my_notifications = list(
        notifications.find({"recipient_email": session["email"]})
        .sort("created_on", -1)
    )

    # Mark all as read when the page is viewed
    notifications.update_many(
        {"recipient_email": session["email"], "is_read": False},
        {"$set": {"is_read": True}}
    )

    return render_template("notifications.html", notifications=my_notifications)

@app.route("/notifications/mark_read/<notification_id>")
def mark_notification_read(notification_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    notification = notifications.find_one({"_id": ObjectId(notification_id)})

    notifications.update_one(
        {"_id": ObjectId(notification_id), "recipient_email": session["email"]},
        {"$set": {"is_read": True}}
    )

    if notification and notification.get("link"):
        return redirect(notification["link"])

    return redirect(url_for("view_notifications"))


# =================================================
# ADMIN DASHBOARD
# =================================================

@app.route("/admin_dashboard")
def admin_dashboard():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    total_users = users.count_documents({})
    total_candidates = users.count_documents({"role": "Candidate"})
    total_recruiters = users.count_documents({"role": "Recruiter"})
    total_jobs = jobs.count_documents({})
    total_applications = applications.count_documents({})

    recent_audit_logs = list(
        audit_logs.find().sort("timestamp", -1).limit(15)
    )

    return render_template(
        "admin_dashboard.html",
        total_users=total_users,
        total_candidates=total_candidates,
        total_recruiters=total_recruiters,
        total_jobs=total_jobs,
        total_applications=total_applications,
        recent_audit_logs=recent_audit_logs
    )

@app.route("/admin/audit_logs")
def admin_audit_logs():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    all_logs = list(audit_logs.find().sort("timestamp", -1).limit(500))

    return render_template("audit_logs.html", logs=all_logs)

@app.route("/admin/users")
def admin_users():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    all_users = list(users.find().sort("full_name", 1))

    return render_template("admin_users.html", users=all_users)

@app.route("/admin/delete_user/<user_id>")
def admin_delete_user(user_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Admin":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    target_user = users.find_one({"_id": ObjectId(user_id)})

    users.delete_one({"_id": ObjectId(user_id)})

    if target_user:
        log_audit(
            session["email"], "Admin", "Deleted User",
            f"Deleted user {target_user['email']} ({target_user['role']})"
        )

    flash("User deleted successfully.", "success")
    return redirect(url_for("admin_users"))


# =================================================
# PDF REPORTS
# =================================================

def build_pdf_table(title, headers, rows, col_widths=None):
    """Shared helper to build a simple titled table PDF and return BytesIO."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4),
                             topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph(title, styles["Title"]))
    elements.append(Spacer(1, 0.5 * cm))
    elements.append(Paragraph(
        f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        styles["Normal"]
    ))
    elements.append(Spacer(1, 0.5 * cm))

    table_data = [headers] + rows

    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)
    return buffer

@app.route("/report/candidate_rankings/<job_id>")
def report_candidate_rankings(job_id):

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    job = jobs.find_one({"_id": ObjectId(job_id), "posted_by": session["email"]})

    if not job:
        flash("Job not found or access denied.", "danger")
        return redirect(url_for("manage_jobs"))

    job_applications = list(
        applications.find({"job_id": job_id}).sort("score", -1)
    )

    headers = ["Rank", "Candidate", "Email", "Match Score (%)", "Status", "Applied On"]
    rows = []
    for i, a in enumerate(job_applications, start=1):
        rows.append([
            str(i),
            a.get("candidate_name", ""),
            a.get("candidate_email", ""),
            str(a.get("score", 0)),
            a.get("status", ""),
            a.get("applied_on").strftime("%Y-%m-%d") if a.get("applied_on") else ""
        ])

    if not rows:
        rows = [["-", "No applications yet", "-", "-", "-", "-"]]

    buffer = build_pdf_table(
        f"Candidate Rankings - {job['job_title']} ({job['company']})",
        headers, rows,
        col_widths=[1.5*cm, 5*cm, 6*cm, 3.5*cm, 3*cm, 3*cm]
    )

    log_audit(session["email"], "Recruiter", "Downloaded PDF Report",
              f"Candidate rankings for '{job['job_title']}'")

    filename = f"candidate_rankings_{job['job_title'].replace(' ', '_')}.pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype="application/pdf")

@app.route("/report/interview_schedule")
def report_interview_schedule():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    my_interviews = list(
        interviews.find({"scheduled_by": session["email"]}).sort("date", 1)
    )

    headers = ["Candidate", "Job Title", "Date", "Time", "Mode", "Meeting Link"]
    rows = []
    for i in my_interviews:
        rows.append([
            i.get("candidate_name", ""),
            i.get("job_title", ""),
            i.get("date", ""),
            i.get("time", ""),
            i.get("mode", ""),
            i.get("meeting_link", "")
        ])

    if not rows:
        rows = [["-", "No interviews scheduled yet", "-", "-", "-", "-"]]

    buffer = build_pdf_table(
        "Interview Schedule",
        headers, rows,
        col_widths=[4*cm, 5*cm, 3*cm, 2.5*cm, 3*cm, 5.5*cm]
    )

    log_audit(session["email"], "Recruiter", "Downloaded PDF Report", "Interview schedule")

    return send_file(buffer, as_attachment=True, download_name="interview_schedule.pdf", mimetype="application/pdf")

@app.route("/report/hiring_summary")
def report_hiring_summary():

    if "email" not in session:
        flash("Please login first!", "warning")
        return redirect(url_for("login"))

    if session["role"] != "Recruiter":
        flash("Access Denied!", "danger")
        return redirect(url_for("login"))

    recruiter_job_docs = list(jobs.find({"posted_by": session["email"]}))
    recruiter_job_ids = [str(job["_id"]) for job in recruiter_job_docs]

    total_jobs = len(recruiter_job_docs)
    total_applications = applications.count_documents({"job_id": {"$in": recruiter_job_ids}})
    accepted = applications.count_documents({"job_id": {"$in": recruiter_job_ids}, "status": "Accepted"})
    rejected = applications.count_documents({"job_id": {"$in": recruiter_job_ids}, "status": "Rejected"})
    pending = applications.count_documents({"job_id": {"$in": recruiter_job_ids}, "status": "Pending"})

    headers = ["Job Title", "Company", "Applications", "Accepted", "Rejected", "Pending"]
    rows = []
    for job in recruiter_job_docs:
        jid = str(job["_id"])
        rows.append([
            job["job_title"],
            job["company"],
            str(applications.count_documents({"job_id": jid})),
            str(applications.count_documents({"job_id": jid, "status": "Accepted"})),
            str(applications.count_documents({"job_id": jid, "status": "Rejected"})),
            str(applications.count_documents({"job_id": jid, "status": "Pending"})),
        ])

    if not rows:
        rows = [["-", "No jobs posted yet", "-", "-", "-", "-"]]

    summary_line = (
        f"Total Jobs: {total_jobs}  |  Total Applications: {total_applications}  |  "
        f"Accepted: {accepted}  |  Rejected: {rejected}  |  Pending: {pending}"
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), topMargin=1.5*cm, bottomMargin=1.5*cm)
    styles = getSampleStyleSheet()
    elements = [
        Paragraph("Hiring Summary Report", styles["Title"]),
        Spacer(1, 0.3*cm),
        Paragraph(f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]),
        Spacer(1, 0.3*cm),
        Paragraph(summary_line, styles["Normal"]),
        Spacer(1, 0.5*cm),
    ]

    table = Table([headers] + rows, colWidths=[5*cm, 4*cm, 3*cm, 3*cm, 3*cm, 3*cm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d6efd")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    log_audit(session["email"], "Recruiter", "Downloaded PDF Report", "Hiring summary")

    return send_file(buffer, as_attachment=True, download_name="hiring_summary.pdf", mimetype="application/pdf")

# =================================================
# LOGOUT
# =================================================

@app.route("/logout")
def logout():

    if "email" in session:
        log_audit(session["email"], session.get("role", ""), "Logout")

    session.clear()

    flash("Logged out successfully!", "success")

    return redirect(url_for("login"))


# =================================================
# RUN APPLICATION
# =================================================

if __name__ == "__main__":
    app.run(debug=True)