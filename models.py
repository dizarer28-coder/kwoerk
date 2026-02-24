from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.String(200), default='default.jpg')
    bio = db.Column(db.String(500), default='')
    online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Звезды и подарки
    stars = db.Column(db.Integer, default=100)  # Каждому новому пользователю 100 звезд
    wallpaper = db.Column(db.String(200), default='default_wallpaper.jpg')
    
    # Отношения
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy=True)
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy=True)
    owned_channels = db.relationship('Channel', backref='owner', lazy=True)
    sent_gifts = db.relationship('Gift', foreign_keys='Gift.sender_id', backref='sender', lazy=True)
    received_gifts = db.relationship('Gift', foreign_keys='Gift.receiver_id', backref='receiver', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Gift(db.Model):
    __tablename__ = 'gift'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    emoji = db.Column(db.String(10), nullable=False)
    price = db.Column(db.Integer, nullable=False)  # Цена в звездах
    image = db.Column(db.String(200), default='gift_default.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Связь с подарками пользователей
    user_gifts = db.relationship('UserGift', backref='gift', lazy=True)

class UserGift(db.Model):
    __tablename__ = 'user_gift'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    gift_id = db.Column(db.Integer, db.ForeignKey('gift.id'))
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    message = db.Column(db.String(200))
    received_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_hidden = db.Column(db.Boolean, default=False)  # Можно скрыть подарок в профиле
    
    sender = db.relationship('User', foreign_keys=[sender_id])

class Channel(db.Model):
    __tablename__ = 'channel'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    avatar = db.Column(db.String(200), default='channel_default.jpg')
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_private = db.Column(db.Boolean, default=False)
    
    messages = db.relationship('ChannelMessage', backref='channel', lazy=True)
    subscribers = db.relationship('ChannelSubscriber', backref='channel', lazy=True)

class ChannelSubscriber(db.Model):
    __tablename__ = 'channel_subscriber'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, default=False)

class Message(db.Model):
    __tablename__ = 'message'
    
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    read = db.Column(db.Boolean, default=False)
    file_url = db.Column(db.String(200))
    reply_to = db.Column(db.Integer, nullable=True)  # ID сообщения, на которое отвечаем

class ChannelMessage(db.Model):
    __tablename__ = 'channel_message'
    
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    channel_id = db.Column(db.Integer, db.ForeignKey('channel.id'), nullable=False)
    file_url = db.Column(db.String(200))
    
    sender = db.relationship('User', backref='channel_messages')