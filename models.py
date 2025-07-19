#!/usr/bin/env python3
"""
Database models for CalDAV Web Client
Handles persistent storage of user preferences and settings
"""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import json

db = SQLAlchemy()

class UserPreferences(db.Model):
    """Store user preferences and settings"""
    __tablename__ = 'user_preferences'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(255), nullable=False)
    server_url = db.Column(db.String(512), nullable=False)
    server_type = db.Column(db.String(50), nullable=False, default='generic')
    
    # Calendar settings
    selected_calendars = db.Column(db.Text)  # JSON array
    calendar_colors = db.Column(db.Text)     # JSON object
    week_start = db.Column(db.Integer, default=0)  # 0=Sunday, 1=Monday
    
    # UI preferences
    default_view = db.Column(db.String(50), default='dayGridMonth')
    timezone = db.Column(db.String(100), default='UTC')
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # Unique constraint to prevent duplicate entries
    __table_args__ = (
        db.UniqueConstraint('username', 'server_url', name='unique_user_server'),
    )
    
    def get_selected_calendars(self):
        """Parse selected calendars from JSON"""
        if self.selected_calendars:
            try:
                return json.loads(self.selected_calendars)
            except json.JSONDecodeError:
                return []
        return []
    
    def set_selected_calendars(self, calendars):
        """Store selected calendars as JSON"""
        self.selected_calendars = json.dumps(calendars)
    
    def get_calendar_colors(self):
        """Parse calendar colors from JSON"""
        if self.calendar_colors:
            try:
                return json.loads(self.calendar_colors)
            except json.JSONDecodeError:
                return {}
        return {}
    
    def set_calendar_colors(self, colors):
        """Store calendar colors as JSON"""
        self.calendar_colors = json.dumps(colors)
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'username': self.username,
            'server_url': self.server_url,
            'server_type': self.server_type,
            'selected_calendars': self.get_selected_calendars(),
            'calendar_colors': self.get_calendar_colors(),
            'week_start': self.week_start,
            'default_view': self.default_view,
            'timezone': self.timezone,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }

class CalendarCache(db.Model):
    """Cache calendar information to reduce CalDAV server requests"""
    __tablename__ = 'calendar_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user_preferences.id'), nullable=False)
    calendar_name = db.Column(db.String(255), nullable=False)
    calendar_url = db.Column(db.String(512), nullable=False)
    display_name = db.Column(db.String(255))
    color = db.Column(db.String(7))  # Hex color code
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    user = db.relationship('UserPreferences', backref=db.backref('calendars', lazy=True))
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'calendar_name': self.calendar_name,
            'calendar_url': self.calendar_url,
            'display_name': self.display_name,
            'color': self.color,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

class UserSession(db.Model):
    """Store active user sessions"""
    __tablename__ = 'user_sessions'
    
    id = db.Column(db.String(255), primary_key=True)  # Session ID
    user_id = db.Column(db.Integer, db.ForeignKey('user_preferences.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    ip_address = db.Column(db.String(45))  # IPv6 support
    user_agent = db.Column(db.Text)
    
    # Relationship
    user = db.relationship('UserPreferences', backref=db.backref('sessions', lazy=True))
    
    @property
    def is_expired(self):
        """Check if session is expired"""
        return datetime.utcnow() > self.expires_at
    
    def to_dict(self):
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'ip_address': self.ip_address,
            'is_expired': self.is_expired
        }
