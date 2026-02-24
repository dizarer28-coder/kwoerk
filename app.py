from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
from datetime import datetime
from models import db, User, Gift, UserGift, Channel, ChannelSubscriber, Message, ChannelMessage
import os
import uuid
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'd41d8cd98f00b204e9800998ecf8427e')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///telegram.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads/avatars'
app.config['WALLPAPER_FOLDER'] = 'static/uploads/wallpapers'
app.config['GIFT_FOLDER'] = 'static/uploads/gifts'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Создаем папки для загрузок
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['WALLPAPER_FOLDER'], exist_ok=True)
os.makedirs(app.config['GIFT_FOLDER'], exist_ok=True)
os.makedirs('static/uploads/channels', exist_ok=True)

# Инициализация расширений
db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# СОЗДАЕМ ТАБЛИЦЫ И ПОДАРКИ ПРЯМО СЕЙЧАС!
with app.app_context():
    db.create_all()
    
    # Создаем подарки если их нет
    if Gift.query.count() == 0:
        gifts_data = [
            {'name': '🌟 Золотая звезда', 'emoji': '🌟', 'price': 10},
            {'name': '🎂 Торт', 'emoji': '🎂', 'price': 25},
            {'name': '🌹 Роза', 'emoji': '🌹', 'price': 15},
            {'name': '🐻 Мишка', 'emoji': '🧸', 'price': 30},
            {'name': '🍫 Шоколадка', 'emoji': '🍫', 'price': 5},
            {'name': '🏆 Трофей', 'emoji': '🏆', 'price': 50},
            {'name': '💎 Алмаз', 'emoji': '💎', 'price': 100},
            {'name': '🎮 Игровая приставка', 'emoji': '🎮', 'price': 200},
            {'name': '✈️ Путешествие', 'emoji': '✈️', 'price': 500},
            {'name': '👑 Корона', 'emoji': '👑', 'price': 1000},
        ]
        
        for gift_data in gifts_data:
            gift = Gift(
                name=gift_data['name'],
                emoji=gift_data['emoji'],
                price=gift_data['price']
            )
            db.session.add(gift)
        
        db.session.commit()
        print("✅ Подарки созданы!")

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
    # Поиск пользователей
    query = request.args.get('q', '')
    found_users = []
    if query:
        found_users = User.query.filter(
            User.username.contains(query),
            User.id != current_user.id
        ).limit(10).all()
    
    # Получаем все чаты пользователя
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
    
    return render_template('chats.html', 
                         chats=chats_data,
                         found_users=found_users,
                         query=query)

@app.route('/chat/<int:user_id>')
@login_required
def chat(user_id):
    other_user = User.query.get_or_404(user_id)
    
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp).all()
    
    # Отмечаем сообщения как прочитанные
    unread_messages = Message.query.filter_by(
        sender_id=user_id,
        receiver_id=current_user.id,
        read=False
    ).all()
    
    for msg in unread_messages:
        msg.read = True
    
    db.session.commit()
    
    return render_template('chat.html', user=other_user, messages=messages)

@app.route('/send_message/<int:receiver_id>', methods=['POST'])
@login_required
def send_message(receiver_id):
    content = request.form.get('content')
    reply_to = request.form.get('reply_to')
    
    if content:
        message = Message(
            content=content,
            sender_id=current_user.id,
            receiver_id=receiver_id,
            reply_to=reply_to if reply_to else None
        )
        db.session.add(message)
        db.session.commit()
        
        # Отправляем через WebSocket
        socketio.emit('new_message', {
            'id': message.id,
            'content': content,
            'sender_id': current_user.id,
            'sender_username': current_user.username,
            'timestamp': message.timestamp.strftime('%H:%M'),
            'reply_to': reply_to
        }, room=f"user_{receiver_id}")
    
    return redirect(url_for('chat', user_id=receiver_id))

@app.route('/profile/<username>')
@login_required
def profile(username):
    user = User.query.filter_by(username=username).first_or_404()
    
    # Получаем подарки пользователя
    user_gifts = UserGift.query.filter_by(user_id=user.id, is_hidden=False).order_by(UserGift.received_at.desc()).all()
    
    # Проверяем, есть ли уже чат с этим пользователем
    existing_chat = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == user.id)) |
        ((Message.sender_id == user.id) & (Message.receiver_id == current_user.id))
    ).first() is not None
    
    return render_template('profile.html', 
                         user=user, 
                         user_gifts=user_gifts,
                         existing_chat=existing_chat)

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

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

@app.route('/wallpaper', methods=['POST'])
@login_required
def change_wallpaper():
    if 'wallpaper' in request.files:
        file = request.files['wallpaper']
        if file and allowed_file(file.filename):
            filename = secure_filename(f"wallpaper_{current_user.id}_{uuid.uuid4()}.jpg")
            file.save(os.path.join(app.config['WALLPAPER_FOLDER'], filename))
            current_user.wallpaper = filename
            db.session.commit()
            flash('Обои обновлены!', 'success')
    
    return redirect(url_for('settings'))

@app.route('/gifts')
@login_required
def gifts():
    # Все доступные подарки
    all_gifts = Gift.query.all()
    
    # Подарки пользователя
    user_gifts = UserGift.query.filter_by(user_id=current_user.id).order_by(UserGift.received_at.desc()).all()
    
    return render_template('gifts.html', 
                         all_gifts=all_gifts, 
                         user_gifts=user_gifts,
                         stars=current_user.stars)

@app.route('/buy_gift/<int:gift_id>', methods=['POST'])
@login_required
def buy_gift(gift_id):
    gift = Gift.query.get_or_404(gift_id)
    
    if current_user.stars >= gift.price:
        current_user.stars -= gift.price
        db.session.commit()
        flash(f'Вы купили {gift.name}! Теперь можете дарить его друзьям', 'success')
    else:
        flash('Недостаточно звезд!', 'error')
    
    return redirect(url_for('gifts'))

@app.route('/send_gift/<int:receiver_id>', methods=['POST'])
@login_required
def send_gift(receiver_id):
    gift_id = request.form.get('gift_id')
    message = request.form.get('message', '')
    
    gift = Gift.query.get_or_404(gift_id)
    receiver = User.query.get_or_404(receiver_id)
    
    # Проверяем, есть ли у пользователя этот подарок
    user_has_gift = UserGift.query.filter_by(
        user_id=current_user.id,
        gift_id=gift_id,
        sender_id=current_user.id
    ).first()
    
    if not user_has_gift and current_user.stars < gift.price:
        flash('У вас нет этого подарка и недостаточно звезд для покупки', 'error')
        return redirect(url_for('profile', username=receiver.username))
    
    # Если у пользователя нет подарка, покупаем его
    if not user_has_gift:
        if current_user.stars >= gift.price:
            current_user.stars -= gift.price
        else:
            flash('Недостаточно звезд!', 'error')
            return redirect(url_for('profile', username=receiver.username))
    
    # Дарим подарок
    user_gift = UserGift(
        user_id=receiver_id,
        gift_id=gift_id,
        sender_id=current_user.id,
        message=message
    )
    db.session.add(user_gift)
    db.session.commit()
    
    flash(f'Подарок {gift.name} отправлен {receiver.username}!', 'success')
    return redirect(url_for('profile', username=receiver.username))

@app.route('/hide_gift/<int:gift_id>', methods=['POST'])
@login_required
def hide_gift(gift_id):
    user_gift = UserGift.query.get_or_404(gift_id)
    if user_gift.user_id == current_user.id:
        user_gift.is_hidden = not user_gift.is_hidden
        db.session.commit()
    
    return redirect(url_for('gifts'))

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
        
        # Добавляем создателя как подписчика
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
        
        flash('Вы подписались на канал!', 'success')
    else:
        flash('Вы уже подписаны', 'info')
    
    return redirect(url_for('channel', channel_id=channel_id))

@app.route('/test')
@login_required
def test():
    try:
        users = User.query.all()
        gifts = Gift.query.all()
        user_gifts = UserGift.query.all()
        
        return f"""
        ✅ База данных работает!<br>
        Пользователей: {len(users)}<br>
        Подарков в магазине: {len(gifts)}<br>
        Подарков подарено: {len(user_gifts)}<br>
        <br>
        <b>Твои звезды: {current_user.stars} ⭐</b>
        """
    except Exception as e:
        return f"❌ Ошибка: {str(e)}"

@app.teardown_appcontext
def shutdown_session(exception=None):
    db.session.remove()

# WebSocket события
@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        join_room(f"user_{current_user.id}")
        current_user.online = True
        db.session.commit()

@socketio.on('disconnect')
def handle_disconnect():
    if current_user.is_authenticated:
        current_user.online = False
        current_user.last_seen = datetime.utcnow()
        db.session.commit()

@socketio.on('typing')
def handle_typing(data):
    emit('user_typing', {
        'user_id': current_user.id,
        'username': current_user.username,
        'is_typing': data['is_typing']
    }, room=f"user_{data['receiver_id']}")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Создаем тестовых пользователей если их нет
        if User.query.count() == 0:
            users_data = [
                {'phone': '79123456789', 'username': 'test', 'email': 'test@test.com', 'password': '123456'},
                {'phone': '11213141516', 'username': 'user2', 'email': 'user2@test.com', 'password': '123456789'},
                {'phone': '79876543210', 'username': 'alice', 'email': 'alice@test.com', 'password': '123456'},
                {'phone': '79876543211', 'username': 'bob', 'email': 'bob@test.com', 'password': '123456'},
            ]
            
            for user_data in users_data:
                user = User(
                    phone=user_data['phone'],
                    username=user_data['username'],
                    email=user_data['email'],
                    stars=200  # Дополнительные звезды для теста
                )
                user.set_password(user_data['password'])
                db.session.add(user)
            
            db.session.commit()
            print("✅ Тестовые пользователи созданы!")
    
    port = int(os.environ.get('PORT', 5000))
    socketio.run(app, debug=False, host='0.0.0.0', port=port)