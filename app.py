from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from models import db, User, Channel, ChannelSubscriber, Message, ChannelMessage
import os
import uuid

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key')
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

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Имя пользователя уже занято', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email уже зарегистрирован', 'error')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        
        db.session.add(user)
        db.session.commit()
        
        flash('Регистрация успешна! Теперь войдите', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            user.online = True
            db.session.commit()
            
            socketio.emit('user_online', {
                'user_id': user.id,
                'username': user.username
            })
            
            return redirect(url_for('chats'))
        
        flash('Неверное имя или пароль', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    current_user.online = False
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    
    socketio.emit('user_offline', {
        'user_id': current_user.id
    })
    
    logout_user()
    return redirect(url_for('index'))

@app.route('/chats')
@login_required
def chats():
    sent_messages = Message.query.filter_by(sender_id=current_user.id).all()
    received_messages = Message.query.filter_by(receiver_id=current_user.id).all()
    
    chat_partners = set()
    for msg in sent_messages:
        chat_partners.add(msg.receiver_id)
    for msg in received_messages:
        chat_partners.add(msg.sender_id)
    
    chats_data = []
    for partner_id in chat_partners:
        partner = User.query.get(partner_id)
        last_message = Message.query.filter(
            ((Message.sender_id == current_user.id) & (Message.receiver_id == partner_id)) |
            ((Message.sender_id == partner_id) & (Message.receiver_id == current_user.id))
        ).order_by(Message.timestamp.desc()).first()
        
        unread_count = Message.query.filter_by(
            sender_id=partner_id,
            receiver_id=current_user.id,
            read=False
        ).count()
        
        chats_data.append({
            'user': partner,
            'last_message': last_message,
            'unread_count': unread_count
        })
    
    chats_data.sort(key=lambda x: x['last_message'].timestamp if x['last_message'] else datetime.min, reverse=True)
    
    user_channels = ChannelSubscriber.query.filter_by(user_id=current_user.id).all()
    channels = [sub.channel for sub in user_channels]
    
    random_users = User.query.filter(User.id != current_user.id).order_by(db.func.random()).limit(5).all()
    
    return render_template('chats.html', 
                         chats=chats_data, 
                         channels=channels,
                         random_users=random_users)

@app.route('/chat/<int:user_id>')
@login_required
def chat(user_id):
    other_user = User.query.get_or_404(user_id)
    
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()
    
    unread_messages = Message.query.filter_by(
        sender_id=user_id,
        receiver_id=current_user.id,
        read=False
    ).all()
    
    for msg in unread_messages:
        msg.read = True
    
    db.session.commit()
    
    return render_template('chat.html', user=other_user, messages=messages)

@app.route('/channel/<int:channel_id>')
@login_required
def channel(channel_id):
    channel = Channel.query.get_or_404(channel_id)
    
    is_subscribed = ChannelSubscriber.query.filter_by(
        user_id=current_user.id,
        channel_id=channel_id
    ).first() is not None
    
    messages = ChannelMessage.query.filter_by(channel_id=channel_id).order_by(ChannelMessage.timestamp).all()
    subscribers = ChannelSubscriber.query.filter_by(channel_id=channel_id).count()
    
    return render_template('channel.html', 
                         channel=channel, 
                         messages=messages,
                         is_subscribed=is_subscribed,
                         subscribers=subscribers)

@app.route('/create_channel', methods=['GET', 'POST'])
@login_required
def create_channel():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        
        channel = Channel(
            name=name,
            description=description,
            owner_id=current_user.id
        )
        
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"channel_{uuid.uuid4()}_{file.filename}")
                file.save(os.path.join('static/uploads/channels', filename))
                channel.avatar = filename
        
        db.session.add(channel)
        db.session.commit()
        
        subscriber = ChannelSubscriber(
            user_id=current_user.id,
            channel_id=channel.id,
            is_admin=True
        )
        db.session.add(subscriber)
        db.session.commit()
        
        flash('Канал успешно создан!', 'success')
        return redirect(url_for('channel', channel_id=channel.id))
    
    return render_template('create_channel.html')

@app.route('/subscribe_channel/<int:channel_id>', methods=['POST'])
@login_required
def subscribe_channel(channel_id):
    channel = Channel.query.get_or_404(channel_id)
    
    existing = ChannelSubscriber.query.filter_by(
        user_id=current_user.id,
        channel_id=channel_id
    ).first()
    
    if not existing:
        subscriber = ChannelSubscriber(
            user_id=current_user.id,
            channel_id=channel_id
        )
        db.session.add(subscriber)
        db.session.commit()
        
        socketio.emit('new_subscriber', {
            'channel_id': channel_id,
            'username': current_user.username
        })
        
        return jsonify({'success': True, 'message': 'Вы подписались на канал'})
    
    return jsonify({'success': False, 'message': 'Вы уже подписаны'})

@app.route('/profile/<username>')
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    mutual_chats = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user.id)) |
        ((Message.sender_id == user.id) & (Message.receiver_id == current_user.id))
    ).first() is not None
    
    return render_template('profile.html', user=user, mutual_chats=mutual_chats)

@app.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    if request.method == 'POST':
        current_user.username = request.form['username']
        current_user.bio = request.form['bio']
        current_user.phone = request.form['phone']
        
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

@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify({'success': False, 'message': 'Нет файла'})
    
    file = request.files['avatar']
    if file and allowed_file(file.filename):
        filename = secure_filename(f"user_{current_user.id}_{uuid.uuid4()}.jpg")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        
        current_user.avatar = filename
        db.session.commit()
        
        socketio.emit('avatar_changed', {
            'user_id': current_user.id,
            'avatar': filename
        })
        
        return jsonify({'success': True, 'avatar': filename})
    
    return jsonify({'success': False, 'message': 'Неверный формат файла'})

@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(f"user_{current_user.id}")
        current_user.online = True
        db.session.commit()
        
        emit('user_online', {
            'user_id': current_user.id,
            'username': current_user.username
        }, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        current_user.online = False
        current_user.last_seen = datetime.utcnow()
        db.session.commit()
        
        emit('user_offline', {
            'user_id': current_user.id
        }, broadcast=True)

@socketio.on('send_message')
def handle_send_message(data):
    receiver_id = data['receiver_id']
    content = data['content']
    
    message = Message(
        content=content,
        sender_id=current_user.id,
        receiver_id=receiver_id
    )
    db.session.add(message)
    db.session.commit()
    
    emit('new_message', {
        'id': message.id,
        'content': content,
        'sender_id': current_user.id,
        'sender_username': current_user.username,
        'sender_avatar': current_user.avatar,
        'timestamp': message.timestamp.strftime('%H:%M'),
        'receiver_id': receiver_id
    }, room=f"user_{receiver_id}")
    
    emit('message_sent', {
        'id': message.id,
        'content': content,
        'timestamp': message.timestamp.strftime('%H:%M'),
        'receiver_id': receiver_id
    }, room=f"user_{current_user.id}")

@socketio.on('send_channel_message')
def handle_send_channel_message(data):
    channel_id = data['channel_id']
    content = data['content']
    
    subscriber = ChannelSubscriber.query.filter_by(
        user_id=current_user.id,
        channel_id=channel_id
    ).first()
    
    if subscriber:
        message = ChannelMessage(
            content=content,
            sender_id=current_user.id,
            channel_id=channel_id
        )
        db.session.add(message)
        db.session.commit()
        
        emit('new_channel_message', {
            'id': message.id,
            'content': content,
            'sender_id': current_user.id,
            'sender_username': current_user.username,
            'sender_avatar': current_user.avatar,
            'timestamp': message.timestamp.strftime('%H:%M'),
            'channel_id': channel_id
        }, room=f"channel_{channel_id}")

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {
        'user_id': current_user.id,
        'username': current_user.username,
        'is_typing': data['is_typing']
    }, room=f"user_{data['receiver_id']}")

@socketio.on('join_channel')
def handle_join_channel(data):
    channel_id = data['channel_id']
    join_room(f"channel_{channel_id}")
    
    emit('user_joined_channel', {
        'user_id': current_user.id,
        'username': current_user.username,
        'channel_id': channel_id
    }, room=f"channel_{channel_id}")

@socketio.on('leave_channel')
def handle_leave_channel(data):
    channel_id = data['channel_id']
    leave_room(f"channel_{channel_id}")

@app.route('/search_users')
@login_required
def search_users():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    users = User.query.filter(
        User.username.contains(query),
        User.id != current_user.id
    ).limit(10).all()
    
    return jsonify([{
        'id': user.id,
        'username': user.username,
        'avatar': user.avatar,
        'online': user.online
    } for user in users])

@app.route('/test')
def test():
    try:
        # Проверка базы данных
        test_user = User.query.first()
        if test_user:
            return f"База данных работает! Найден пользователь: {test_user.username}"
        else:
            return "База данных работает, но пользователей пока нет"
    except Exception as e:
        return f"Ошибка базы данных: {str(e)}"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Создание тестовых пользователей если их нет
        if User.query.count() == 0:
            users_data = [
                {'username': 'alice', 'email': 'alice@test.com', 'password': '123456', 'bio': 'Дизайнер, люблю рисовать'},
                {'username': 'bob', 'email': 'bob@test.com', 'password': '123456', 'bio': 'Разработчик игр'},
                {'username': 'charlie', 'email': 'charlie@test.com', 'password': '123456', 'bio': 'Музыкант'},
            ]
            
            for user_data in users_data:
                user = User(
                    username=user_data['username'],
                    email=user_data['email'],
                    bio=user_data['bio']
                )
                user.set_password(user_data['password'])
                db.session.add(user)
            
            db.session.commit()
            
            tech_channel = Channel(
                name='Tech News',
                description='Все о технологиях и программировании',
                owner_id=2
            )
            db.session.add(tech_channel)
            db.session.commit()
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)