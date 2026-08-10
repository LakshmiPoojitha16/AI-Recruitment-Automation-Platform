from flask import Flask

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = "change-this-in-production"

    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.candidate import candidate_bp
    from app.routes.recruiter import recruiter_bp
    from app.routes.ai import ai_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(candidate_bp)
    app.register_blueprint(recruiter_bp)
    app.register_blueprint(ai_bp)

    return app