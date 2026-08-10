from flask import Blueprint, render_template, request
import bcrypt

from database.db import db

auth = Blueprint("auth", __name__)

users_collection = db["users"]


@auth.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        full_name = request.form.get("full_name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        role = request.form.get("role")

        # Check passwords
        if password != confirm_password:
            return "Passwords do not match!"

        # Check if email already exists
        existing_user = users_collection.find_one({"email": email})

        if existing_user:
            return "Email is already registered!"

        # Hash the password
        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        )

        # Create user document
        user_data = {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "password": hashed_password.decode("utf-8"),
            "role": role
        }

        # Save user to MongoDB
        users_collection.insert_one(user_data)

        return "Registration Successful!"

    return render_template("register.html")


@auth.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        print(email)
        print(password)

    return render_template("login.html")