from datetime import datetime


def create_user(full_name, email, phone, password, role):
    user = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "password": password,
        "role": role,
        "created_at": datetime.now()
    }

    return user