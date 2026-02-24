from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from models import db, User, Channel, ChannelSubscriber, Message, ChannelMessage
import os
import uuid
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'd41d8cd98f00b204e9800998ecf8427e')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///telegram.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads/avatars'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('static/uploads/channels', exist_ok=True)

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_phone(phone):
    phone = re.sub(r'\D', '', phone)
    if len(phone) >= 10 and len(phone) <= 15:
        return phone
    return None

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('chats'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            phone = request.form['phone']
            username = request.form['username']
            password = request.form['password']
            email = request.form.get('email', '')
            
            clean_phone = validate_phone(phone)
            if not clean_phone:
                flash('Неверный формат номера телефона', 'error')
                return redirect(url_for('register'))
            
            if User.query.filter_by(phone=clean_phone).first():
                flash('Номер телефона уже зарегистрирован', 'error')
                return redirect(url_for('register'))
            
            if User.query.filter_by(username=username).first():
                flash('Имя пользователя уже занято', 'error')
                return redirect(url_for('register'))
            
            if email and User.query.filter_by(email=email).first():
                flash('Email уже зарегистрирован', 'error')
                return redirect(url_for('register'))
            
            user = User(
                phone=clean_phone,
                username=username,
                email=email if email else None
            )
            user.set_password(password)
            
            db.session.add(user)
            db.session.commit()
            
            flash('Регистрация успешна! Теперь войдите', 'success')
            return redirect(url_for('login'))
            
        except Exception as e:
            return f"Ошибка: {str(e)}"
    
    return render_template('register_phone.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            login_input = request.form['login']
            password = request.form['password']
            
            clean_phone = validate_phone(login_input)
            
            if clean_phone:
                user = User.query.filter_by(phone=clean_phone).first()
            else:
                user = User.query.filter_by(username=login_input).first()
            
            if user and user.check_password(password):
                login_user(user)
                user.online = True
                db.session.commit()
                
                return redirect(url_for('chats'))
            
            flash('Неверный номер телефона/имя или пароль', 'error')
        except Exception as e:
            return f"Ошибка: {str(e)}"
    
    return render_template('login_phone.html')

@app.route('/logout')
@login_required
def logout():
    current_user.online = False
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    logout_user()
    return redirect(url_for('index'))

@app.route('/chats')
@login_required
def chats():
    return render_template('chats.html')

@app.route('/profile/<username>')
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    return render_template('profile.html', user=user)

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        current_user.username = request.form['username']
        current_user.bio = request.form['bio']
        current_user.email = request.form.get('email', '')
        
        new_phone = validate_phone(request.form['phone'])
        if new_phone and new_phone != current_user.phone:
            if User.query.filter_by(phone=new_phone).first():
                flash('Номер телефона уже используется', 'error')
                return redirect(url_for('edit_profile'))
            current_user.phone = new_phone
        
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"user_{current_user.id}_{uuid.uuid4()}.jpg")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                current_user.avatar = filename
        
        db.session.commit()
        flash('Профиль обновлен!', 'success')
        return redirect(url_for('profile', username=current_user.username))
    
    return render_template('edit_profile.html')

@app.route('/test')
def test():
    try:
        result = db.session.execute('SELECT 1').scalar()
        return f"✅ База данных работает! Результат теста: {result}"
    except Exception as e:
        return f"❌ Ошибка базы данных: {str(e)}"

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("✅ База данных создана!")
        
        if User.query.count() == 0:
            test_user = User(
                phone='79123456789',
                username='test',
                email='test@test.com'
            )
            test_user.set_password('123456')
            db.session.add(test_user)
            db.session.commit()
            print("✅ Тестовый пользователь создан: тел: 79123456789, пароль: 123456")
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)