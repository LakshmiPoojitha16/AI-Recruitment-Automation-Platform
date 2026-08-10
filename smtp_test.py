import socket

try:
    sock = socket.create_connection(("smtp.gmail.com", 587), timeout=10)
    print("✅ Connected successfully!")
    sock.close()
except Exception as e:
    print("❌ Error:", e)