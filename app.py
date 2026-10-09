import os
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_socketio import SocketIO, join_room, emit
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-before-deploying")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///kamandconnect.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins=[])

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    username = db.Column(db.String(30), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    kind = db.Column(db.String(20), nullable=False, default="group")  # dm, group, channel
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    members = db.relationship("Membership", backref="conversation", cascade="all, delete-orphan")
    messages = db.relationship("Message", backref="conversation", cascade="all, delete-orphan")

class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    role = db.Column(db.String(20), default="member")
    user = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("conversation_id", "user_id"),)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    body = db.Column(db.String(4000), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User")

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapped

def is_member(conversation_id, user_id):
    return Membership.query.filter_by(conversation_id=conversation_id, user_id=user_id).first() is not None

@app.route("/")
def home():
    if session.get("user_id"):
        return redirect(url_for("chat"))
    return render_template("landing.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not username or not email or len(password) < 8:
            flash("Fill every field. Password must contain at least 8 characters.", "error")
            return render_template("auth.html", mode="signup")
        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("That username or email is already registered.", "error")
            return render_template("auth.html", mode="signup")
        user = User(name=name, username=username, email=email,
                    password_hash=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        # Every new user gets a starter announcement channel.
        channel = Conversation.query.filter_by(title="Campus Broadcast", kind="channel").first()
        if not channel:
            channel = Conversation(title="Campus Broadcast", kind="channel", created_by=user.id)
            db.session.add(channel)
            db.session.flush()
        db.session.add(Membership(conversation_id=channel.id, user_id=user.id, role="member"))
        db.session.commit()
        session["user_id"] = user.id
        session["username"] = user.username
        session["name"] = user.name
        flash("Account created. Welcome to KamandConnect!", "success")
        return redirect(url_for("chat"))
    return render_template("auth.html", mode="signup")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        identity = request.form.get("identity", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter((User.username == identity) | (User.email == identity)).first()
        if not user or not check_password_hash(user.password_hash, password):
            flash("Incorrect username/email or password.", "error")
            return render_template("auth.html", mode="login")
        session["user_id"] = user.id
        session["username"] = user.username
        session["name"] = user.name
        return redirect(url_for("chat"))
    return render_template("auth.html", mode="login")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/chat")
@login_required
def chat():
    user_id = session["user_id"]
    memberships = Membership.query.filter_by(user_id=user_id).all()
    conversations = [m.conversation for m in memberships]
    users = User.query.filter(User.id != user_id).order_by(User.username.asc()).all()
    return render_template("chat.html", conversations=conversations, users=users,
                           current_user={"id": user_id, "name": session["name"], "username": session["username"]})

@app.route("/conversations", methods=["POST"])
@login_required
def create_conversation():
    title = request.form.get("title", "").strip()
    kind = request.form.get("kind", "group")
    if kind not in ("group", "channel"):
        kind = "group"
    if not title:
        flash("Give your group/channel a name.", "error")
        return redirect(url_for("chat"))
    conversation = Conversation(title=title[:100], kind=kind, created_by=session["user_id"])
    db.session.add(conversation)
    db.session.flush()
    db.session.add(Membership(conversation_id=conversation.id, user_id=session["user_id"], role="admin"))
    db.session.commit()
    flash(f"{'Group' if kind == 'group' else 'Channel'} created!", "success")
    return redirect(url_for("chat", conversation=conversation.id))

@app.route("/dm/<int:other_id>", methods=["POST"])
@login_required
def start_dm(other_id):
    user_id = session["user_id"]
    other = db.session.get(User, other_id)
    if not other or other.id == user_id:
        return redirect(url_for("chat"))
    for conv in Conversation.query.filter_by(kind="dm").all():
        ids = {m.user_id for m in conv.members}
        if ids == {user_id, other_id}:
            return redirect(url_for("chat", conversation=conv.id))
    conv = Conversation(title=f"@{other.username}", kind="dm", created_by=user_id)
    db.session.add(conv)
    db.session.flush()
    db.session.add_all([
        Membership(conversation_id=conv.id, user_id=user_id, role="member"),
        Membership(conversation_id=conv.id, user_id=other_id, role="member")
    ])
    db.session.commit()
    return redirect(url_for("chat", conversation=conv.id))

@app.route("/api/conversations/<int:conversation_id>/messages")
@login_required
def get_messages(conversation_id):
    user_id = session["user_id"]
    if not is_member(conversation_id, user_id):
        return jsonify({"error": "not a member"}), 403
    messages = Message.query.filter_by(conversation_id=conversation_id).order_by(Message.created_at.asc()).limit(100).all()
    return jsonify([{"id": m.id, "body": m.body, "username": m.user.username,
                     "name": m.user.name, "mine": m.user_id == user_id,
                     "time": m.created_at.strftime("%H:%M")} for m in messages])

@socketio.on("join_conversation")
def on_join(data):
    user_id = session.get("user_id")
    conversation_id = data.get("conversation_id")
    if not user_id or not isinstance(conversation_id, int) or not is_member(conversation_id, user_id):
        return
    join_room(f"conversation_{conversation_id}")

@socketio.on("send_message")
def on_message(data):
    user_id = session.get("user_id")
    if not user_id:
        return
    try:
        conversation_id = int(data.get("conversation_id"))
    except (TypeError, ValueError):
        return
    body = str(data.get("body", "")).strip()
    if not body or len(body) > 4000 or not is_member(conversation_id, user_id):
        return
    message = Message(conversation_id=conversation_id, user_id=user_id, body=body)
    db.session.add(message)
    db.session.commit()
    user = db.session.get(User, user_id)
    payload = {"id": message.id, "conversation_id": conversation_id, "body": message.body, "username": user.username,
               "name": user.name, "mine": False, "time": message.created_at.strftime("%H:%M")}
    emit("new_message", payload, to=f"conversation_{conversation_id}", include_self=False)
    # Send back to the sender as well, with mine=True.
    payload["mine"] = True
    emit("message_sent", payload)

@socketio.on("typing")
def on_typing(data):
    user_id = session.get("user_id")
    conversation_id = data.get("conversation_id")
    if user_id and isinstance(conversation_id, int) and is_member(conversation_id, user_id):
        user = db.session.get(User, user_id)
        emit("typing", {"name": user.name}, to=f"conversation_{conversation_id}", include_self=False)

with app.app_context():
    db.create_all()
    # Seed a public broadcast channel for first-time users.
    if not Conversation.query.filter_by(title="Campus Broadcast", kind="channel").first():
        seed = Conversation(title="Campus Broadcast", kind="channel", created_by=1)
        db.session.add(seed)
        db.session.commit()

if __name__ == "__main__":
    socketio.run(app, debug=True, port=5000)
