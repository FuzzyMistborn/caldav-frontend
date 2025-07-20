#!/usr/bin/env python3
"""
CalDAV Web Client for Nextcloud
A Flask-based web application for managing calendar events via CalDAV
Enhanced with Gunicorn WSGI server and SQLite database for persistent storage
Flask 2.3+ Compatible Version
"""

import os
import json
import secrets
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import caldav
from caldav.lib import error
import pytz
from icalendar import Calendar, Event as ICalEvent
import uuid
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create Flask app
app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///data/caldav_client.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_timeout': 20,
    'pool_recycle': -1,
    'pool_pre_ping': True
}

# Session configuration
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=int(os.environ.get('SESSION_LIFETIME_DAYS', 7)))

# CalDAV Configuration
CALDAV_SERVER_URL = os.environ.get('CALDAV_SERVER_URL', 'https://your-caldav-server.com')
CALDAV_SERVER_TYPE = os.environ.get('CALDAV_SERVER_TYPE', 'nextcloud')

# CalDAV URL patterns for different servers
CALDAV_URL_PATTERNS = {
    'nextcloud': '{base_url}/remote.php/dav/calendars/{username}/',
    'baikal': '{base_url}/cal.php/calendars/{username}/',
    'radicale': '{base_url}/{username}/',
    'generic': '{base_url}/calendars/{username}/'
}

# Import and initialize database after app configuration
from models import db, UserPreferences, CalendarCache, UserSession

db.init_app(app)

# Initialize database tables
def init_database():
    """Initialize database tables"""
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("Database tables created successfully")
        except Exception as e:
            app.logger.error(f"Error creating database tables: {e}")

# Call database initialization
init_database()

class CalDAVClient:
    def __init__(self, username, password, base_url, server_type='generic'):
        self.username = username
        self.password = password
        self.base_url = base_url
        self.server_type = server_type
        self.client = None
        self.principal = None
        self.calendar = None
        
    def connect(self):
        """Connect to CalDAV server"""
        try:
            self.client = caldav.DAVClient(
                url=self.base_url,
                username=self.username,
                password=self.password
            )
            self.principal = self.client.principal()
            return True
        except Exception as e:
            app.logger.error(f"CalDAV connection error: {e}")
            return False
    
    def get_calendars(self):
        """Get list of available calendars"""
        try:
            calendars = self.principal.calendars()
            calendar_list = []
            for cal in calendars:
                # Handle different server naming conventions
                display_name = cal.name
                if not display_name or display_name == 'None':
                    # Try to get display name from properties
                    try:
                        props = cal.get_properties(['{DAV:}displayname'])
                        display_name = props.get('{DAV:}displayname', 'Unnamed Calendar')
                    except:
                        display_name = 'Unnamed Calendar'
                
                calendar_list.append((display_name, str(cal.url)))
            return calendar_list
        except Exception as e:
            app.logger.error(f"Error getting calendars: {e}")
            return []
    
    def select_calendar(self, calendar_name):
        """Select a calendar to work with"""
        try:
            calendars = self.principal.calendars()
            for cal in calendars:
                # Check both name and display name
                display_name = cal.name
                if not display_name or display_name == 'None':
                    try:
                        props = cal.get_properties(['{DAV:}displayname'])
                        display_name = props.get('{DAV:}displayname', 'Unnamed Calendar')
                    except:
                        display_name = 'Unnamed Calendar'
                
                if display_name == calendar_name or cal.name == calendar_name:
                    self.calendar = cal
                    return True
            return False
        except Exception as e:
            app.logger.error(f"Error selecting calendar: {e}")
            return False
    
    def get_events(self, start_date, end_date):
        """Get events within date range"""
        if not self.calendar:
            return []
        
        try:
            events = self.calendar.search(
                start=start_date,
                end=end_date,
                event=True,
                expand=True
            )
            
            event_list = []
            for event in events:
                try:
                    cal = Calendar.from_ical(event.data)
                    for component in cal.walk():
                        if component.name == "VEVENT":
                            event_data = {
                                'uid': str(component.get('uid')),
                                'summary': str(component.get('summary', '')),
                                'description': str(component.get('description', '')),
                                'start': component.get('dtstart').dt,
                                'end': component.get('dtend').dt,
                                'url': str(event.url)
                            }
                            event_list.append(event_data)
                except Exception as e:
                    app.logger.error(f"Error parsing event: {e}")
                    continue
            
            return event_list
        except Exception as e:
            app.logger.error(f"Error getting events: {e}")
            return []
    
    def create_event(self, summary, description, start_dt, end_dt):
        """Create a new event"""
        if not self.calendar:
            return False
        
        try:
            cal = Calendar()
            cal.add('prodid', '-//CalDAV Web Client//Enhanced//')
            cal.add('version', '2.0')
            
            event = ICalEvent()
            event.add('summary', summary)
            event.add('description', description)
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
            event.add('dtstamp', datetime.now(pytz.UTC))
            event.add('uid', str(uuid.uuid4()))
            
            cal.add_component(event)
            
            self.calendar.save_event(cal.to_ical())
            return True
        except Exception as e:
            app.logger.error(f"Error creating event: {e}")
            return False
    
    def update_event(self, event_url, summary, description, start_dt, end_dt):
        """Update an existing event"""
        try:
            event = self.calendar.event_by_url(event_url)
            cal = Calendar.from_ical(event.data)
            
            for component in cal.walk():
                if component.name == "VEVENT":
                    component['summary'] = summary
                    component['description'] = description
                    component['dtstart'] = start_dt
                    component['dtend'] = end_dt
                    component['dtstamp'] = datetime.now(pytz.UTC)
                    break
            
            event.data = cal.to_ical()
            event.save()
            return True
        except Exception as e:
            app.logger.error(f"Error updating event: {e}")
            return False
    
    def delete_event(self, event_url):
        """Delete an event"""
        try:
            event = self.calendar.event_by_url(event_url)
            event.delete()
            return True
        except Exception as e:
            app.logger.error(f"Error deleting event: {e}")
            return False

def get_caldav_url(username, base_url, server_type):
    """Generate CalDAV URL based on server type"""
    pattern = CALDAV_URL_PATTERNS.get(server_type, CALDAV_URL_PATTERNS['generic'])
    return pattern.format(base_url=base_url, username=username)

def get_or_create_user_preferences(username, server_url, server_type):
    """Get or create user preferences"""
    prefs = UserPreferences.query.filter_by(
        username=username, 
        server_url=server_url
    ).first()
    
    if not prefs:
        prefs = UserPreferences(
            username=username,
            server_url=server_url,
            server_type=server_type
        )
        db.session.add(prefs)
        db.session.commit()
    
    # Update last login
    prefs.last_login = datetime.utcnow()
    prefs.server_type = server_type  # Update in case it changed
    db.session.commit()
    
    return prefs

def update_calendar_cache(user_id, calendars):
    """Update calendar cache for a user"""
    # Delete existing cache for this user
    CalendarCache.query.filter_by(user_id=user_id).delete()
    
    # Add new calendar entries
    for calendar_name, calendar_url in calendars:
        cache_entry = CalendarCache(
            user_id=user_id,
            calendar_name=calendar_name,
            calendar_url=calendar_url
        )
        db.session.add(cache_entry)
    
    db.session.commit()

@app.before_request
def cleanup_expired_sessions():
    """Clean up expired sessions periodically"""
    if request.endpoint == 'health_check':  # Only cleanup on health checks to avoid overhead
        try:
            expired_count = UserSession.query.filter(
                UserSession.expires_at < datetime.utcnow()
            ).delete()
            if expired_count > 0:
                db.session.commit()
                app.logger.info(f"Cleaned up {expired_count} expired sessions")
        except Exception as e:
            app.logger.error(f"Error cleaning up sessions: {e}")
            db.session.rollback()

@app.route('/health')
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        db.session.execute(db.text('SELECT 1'))
        db_status = 'healthy'
    except Exception as e:
        db_status = f'unhealthy: {str(e)}'
    
    return jsonify({
        'status': 'healthy' if db_status == 'healthy' else 'unhealthy',
        'message': 'CalDAV Web Client is running',
        'database': db_status,
        'version': '2.0.0'
    })

@app.route('/debug')
def debug_info():
    """Debug information endpoint"""
    try:
        user_count = UserPreferences.query.count()
        session_count = UserSession.query.count()
    except Exception as e:
        user_count = f"Error: {e}"
        session_count = f"Error: {e}"
    
    return jsonify({
        'flask_env': os.environ.get('FLASK_ENV', 'not set'),
        'caldav_server_url': os.environ.get('CALDAV_SERVER_URL', 'not set'),
        'caldav_server_type': os.environ.get('CALDAV_SERVER_TYPE', 'not set'),
        'database_url': app.config['SQLALCHEMY_DATABASE_URI'],
        'session_keys': list(session.keys()) if session else [],
        'users_count': user_count,
        'active_sessions': session_count,
        'request_path': request.path,
        'request_url': request.url
    })

@app.route('/')
def index():
    """Main calendar view"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('calendar.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Login page"""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        server_url = request.form.get('server_url', CALDAV_SERVER_URL)
        server_type = request.form.get('server_type', CALDAV_SERVER_TYPE)
        
        # Generate CalDAV URL based on server type
        caldav_url = get_caldav_url(username, server_url, server_type)
        
        client = CalDAVClient(username, password, caldav_url, server_type)
        if client.connect():
            calendars = client.get_calendars()
            if calendars:
                # Get or create user preferences
                user_prefs = get_or_create_user_preferences(username, server_url, server_type)
                
                # Update calendar cache
                update_calendar_cache(user_prefs.id, calendars)
                
                # Create session
                session.permanent = True
                session['user_id'] = user_prefs.id
                session['username'] = username
                session['password'] = password  # Consider encrypting this
                session['server_url'] = server_url
                session['server_type'] = server_type
                session['caldav_url'] = caldav_url
                
                return redirect(url_for('select_calendar'))
            else:
                return render_template('login.html', error="No calendars found")
        else:
            return render_template('login.html', error="Invalid credentials or server connection failed")
    
    return render_template('login.html', 
                         default_server_url=CALDAV_SERVER_URL,
                         default_server_type=CALDAV_SERVER_TYPE)

@app.route('/select_calendar', methods=['GET', 'POST'])
def select_calendar():
    """Calendar selection page"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_prefs = UserPreferences.query.get(session['user_id'])
    if not user_prefs:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        selected_calendars = request.form.getlist('calendars')
        if not selected_calendars:
            calendars = [(cal.calendar_name, cal.calendar_url) for cal in user_prefs.calendars]
            return render_template('select_calendar.html', 
                                 calendars=calendars,
                                 selected_calendars=user_prefs.get_selected_calendars(),
                                 error="Please select at least one calendar")
        
        # Save selected calendars to database
        user_prefs.set_selected_calendars(selected_calendars)
        user_prefs.updated_at = datetime.utcnow()
        db.session.commit()
        
        return redirect(url_for('index'))
    
    # Get calendars from cache
    calendars = [(cal.calendar_name, cal.calendar_url) for cal in user_prefs.calendars]
    selected_calendars = user_prefs.get_selected_calendars()
    
    # If no selection exists, pre-select all calendars
    if not selected_calendars:
        selected_calendars = [cal[0] for cal in calendars]
        user_prefs.set_selected_calendars(selected_calendars)
        db.session.commit()
    
    return render_template('select_calendar.html', 
                         calendars=calendars,
                         selected_calendars=selected_calendars)

@app.route('/api/events')
def api_events():
    """API endpoint to get events from multiple calendars"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated - please log in again'}), 401
    
    # Debug session info
    app.logger.info(f"Session info: user_id={session.get('user_id')}, username={session.get('username')}")
    
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    if not start_date or not end_date:
        return jsonify({'error': 'Missing date parameters'}), 400
    
    try:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    user_prefs = UserPreferences.query.get(session['user_id'])
    if not user_prefs:
        app.logger.error(f"User preferences not found for user_id: {session['user_id']}")
        # Try to recreate user preferences if they're missing
        try:
            user_prefs = get_or_create_user_preferences(
                session.get('username'), 
                session.get('server_url'), 
                session.get('server_type', 'generic')
            )
            app.logger.info(f"Created missing user preferences for user: {session.get('username')}")
        except Exception as e:
            app.logger.error(f"Failed to create user preferences: {e}")
            return jsonify({'error': 'User session expired - please log in again'}), 401
    
    # Check if we have CalDAV connection info in session
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete - please log in again'}), 401
    
    client = CalDAVClient(session['username'], session['password'], 
                         session['caldav_url'], session.get('server_type', 'generic'))
    
    if not client.connect():
        return jsonify({'error': 'CalDAV connection failed - please check credentials'}), 500
    
    # Get events from all selected calendars
    all_events = []
    selected_calendars = user_prefs.get_selected_calendars()
    calendar_colors = user_prefs.get_calendar_colors()
    
    # If no selected calendars, use all available calendars
    if not selected_calendars:
        app.logger.info("No selected calendars found, using all available calendars")
        calendars = client.get_calendars()
        selected_calendars = [cal[0] for cal in calendars]
        # Update user preferences with all calendars selected
        user_prefs.set_selected_calendars(selected_calendars)
        db.session.commit()
    
    # Define default colors
    default_calendar_colors = [
        '#3788d8', '#28a745', '#dc3545', '#ffc107', '#6f42c1',
        '#fd7e14', '#20c997', '#e83e8c', '#6c757d', '#17a2b8'
    ]
    
    for i, calendar_name in enumerate(selected_calendars):
        if client.select_calendar(calendar_name):
            events = client.get_events(start_dt, end_dt)
            
            # Get color from preferences or use default
            color = calendar_colors.get(calendar_name, 
                                      default_calendar_colors[i % len(default_calendar_colors)])
            
            for event in events:
                formatted_event = {
                    'id': f"{calendar_name}:{event['uid']}",
                    'title': event['summary'],
                    'start': event['start'].isoformat(),
                    'end': event['end'].isoformat(),
                    'description': event['description'],
                    'url': event['url'],
                    'backgroundColor': color,
                    'borderColor': color,
                    'calendar_name': calendar_name
                }
                all_events.append(formatted_event)
        else:
            app.logger.warning(f"Could not select calendar: {calendar_name}")
    
    app.logger.info(f"Returning {len(all_events)} events from {len(selected_calendars)} calendars")
    return jsonify(all_events)

@app.route('/api/events', methods=['POST'])
def api_create_event():
    """API endpoint to create event"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    app.logger.info(f"Creating event with data: {data}")
    
    try:
        start_dt = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
    except (ValueError, KeyError) as e:
        app.logger.error(f"Invalid date format: {e}")
        return jsonify({'error': 'Invalid date format'}), 400
    
    # Get user preferences to find available calendars and default
    user_prefs = UserPreferences.query.get(session['user_id'])
    if not user_prefs:
        return jsonify({'error': 'User preferences not found'}), 404
    
    # Determine target calendar with improved logic
    target_calendar = data.get('calendar_name')
    if not target_calendar:
        # First try user's default calendar
        if user_prefs.default_calendar:
            target_calendar = user_prefs.default_calendar
        else:
            # Fall back to first selected calendar
            selected_calendars = user_prefs.get_selected_calendars()
            if not selected_calendars:
                # If no selected calendars, try to get first available calendar
                available_calendars = [(cal.calendar_name, cal.calendar_url) for cal in user_prefs.calendars]
                if available_calendars:
                    target_calendar = available_calendars[0][0]
                else:
                    return jsonify({'error': 'No calendars available'}), 400
            else:
                target_calendar = selected_calendars[0]
    
    app.logger.info(f"Target calendar: {target_calendar}")
    
    # Check CalDAV connection info
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete - please log in again'}), 401
    
    # Create CalDAV client
    client = CalDAVClient(session['username'], session['password'], 
                         session['caldav_url'], session.get('server_type', 'generic'))
    
    if not client.connect():
        app.logger.error("CalDAV connection failed")
        return jsonify({'error': 'CalDAV connection failed'}), 500
    
    if not client.select_calendar(target_calendar):
        app.logger.error(f"Calendar not found: {target_calendar}")
        return jsonify({'error': f'Calendar "{target_calendar}" not found'}), 500
    
    # Create the event
    success = client.create_event(
        data.get('title', ''),
        data.get('description', ''),
        start_dt,
        end_dt
    )
    
    if success:
        app.logger.info("Event created successfully")
        return jsonify({'success': True})
    else:
        app.logger.error("Failed to create event")
        return jsonify({'error': 'Failed to create event'}), 500

@app.route('/api/settings', methods=['GET'])
def get_settings():
    """API endpoint to get user settings"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_prefs = UserPreferences.query.get(session['user_id'])
    if not user_prefs:
        return jsonify({'error': 'User preferences not found'}), 404
    
    return jsonify({
        'week_start': user_prefs.week_start,
        'calendar_colors': user_prefs.get_calendar_colors(),
        'default_calendar': user_prefs.default_calendar,  # Add this line
        'default_view': user_prefs.default_view,
        'timezone': user_prefs.timezone
    })

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """API endpoint to update user settings"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    user_prefs = UserPreferences.query.get(session['user_id'])
    
    if not user_prefs:
        return jsonify({'error': 'User preferences not found'}), 404
    
    # Update settings
    if 'week_start' in data:
        user_prefs.week_start = int(data['week_start'])
    
    if 'calendar_colors' in data:
        user_prefs.set_calendar_colors(data['calendar_colors'])
    
    if 'default_calendar' in data:  # Add this block
        user_prefs.default_calendar = data['default_calendar']
    
    if 'default_view' in data:
        user_prefs.default_view = data['default_view']
    
    if 'timezone' in data:
        user_prefs.timezone = data['timezone']
    
    user_prefs.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/api/calendar-selection', methods=['GET'])
def get_calendar_selection():
    """API endpoint to get current calendar selection"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_prefs = UserPreferences.query.get(session['user_id'])
    if not user_prefs:
        return jsonify({'error': 'User preferences not found'}), 404
    
    calendars = [(cal.calendar_name, cal.calendar_url) for cal in user_prefs.calendars]
    
    return jsonify({
        'calendars': calendars,
        'selected_calendars': user_prefs.get_selected_calendars(),
        'calendar_colors': user_prefs.get_calendar_colors(),
        'week_start': user_prefs.week_start
    })

@app.route('/api/events/<event_id>', methods=['PUT'])
def api_update_event(event_id):
    """API endpoint to update event"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    app.logger.info(f"Updating event {event_id} with data: {data}")
    
    try:
        start_dt = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
    except (ValueError, KeyError) as e:
        app.logger.error(f"Invalid date format: {e}")
        return jsonify({'error': 'Invalid date format'}), 400
    
    # Extract calendar name from event ID (format: "calendar_name:uid")
    if ':' in event_id:
        calendar_name, uid = event_id.split(':', 1)
    else:
        # Fallback to first selected calendar
        user_prefs = UserPreferences.query.get(session['user_id'])
        selected_calendars = user_prefs.get_selected_calendars() if user_prefs else []
        calendar_name = selected_calendars[0] if selected_calendars else None
        uid = event_id
    
    if not calendar_name:
        return jsonify({'error': 'Cannot determine target calendar'}), 400
    
    # Check for event URL in data
    event_url = data.get('url')
    if not event_url:
        return jsonify({'error': 'Event URL required for updates'}), 400
    
    # Check CalDAV connection info
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete - please log in again'}), 401
    
    client = CalDAVClient(session['username'], session['password'], 
                         session['caldav_url'], session.get('server_type', 'generic'))
    
    if not client.connect():
        app.logger.error("CalDAV connection failed")
        return jsonify({'error': 'CalDAV connection failed'}), 500
    
    if not client.select_calendar(calendar_name):
        app.logger.error(f"Calendar not found: {calendar_name}")
        return jsonify({'error': f'Calendar "{calendar_name}" not found'}), 500
    
    # Update the event
    success = client.update_event(
        event_url,
        data.get('title', ''),
        data.get('description', ''),
        start_dt,
        end_dt
    )
    
    if success:
        app.logger.info("Event updated successfully")
        return jsonify({'success': True})
    else:
        app.logger.error("Failed to update event")
        return jsonify({'error': 'Failed to update event'}), 500

@app.route('/api/events/<event_id>', methods=['DELETE'])
def api_delete_event(event_id):
    """API endpoint to delete event"""
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    app.logger.info(f"Deleting event: {event_id}")
    
    # Extract calendar name from event ID
    if ':' in event_id:
        calendar_name, uid = event_id.split(':', 1)
    else:
        user_prefs = UserPreferences.query.get(session['user_id'])
        selected_calendars = user_prefs.get_selected_calendars() if user_prefs else []
        calendar_name = selected_calendars[0] if selected_calendars else None
        uid = event_id
    
    if not calendar_name:
        return jsonify({'error': 'Cannot determine target calendar'}), 400
    
    # Get event URL from request data
    data = request.get_json() or {}
    event_url = data.get('url')
    
    if not event_url:
        return jsonify({'error': 'Event URL required for deletion'}), 400
    
    # Check CalDAV connection info
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete - please log in again'}), 401
    
    client = CalDAVClient(session['username'], session['password'], 
                         session['caldav_url'], session.get('server_type', 'generic'))
    
    if not client.connect():
        app.logger.error("CalDAV connection failed")
        return jsonify({'error': 'CalDAV connection failed'}), 500
    
    if not client.select_calendar(calendar_name):
        app.logger.error(f"Calendar not found: {calendar_name}")
        return jsonify({'error': f'Calendar "{calendar_name}" not found'}), 500
    
    # Delete the event
    success = client.delete_event(event_url)
    
    if success:
        app.logger.info("Event deleted successfully")
        return jsonify({'success': True})
    else:
        app.logger.error("Failed to delete event")
        return jsonify({'error': 'Failed to delete event'}), 500

@app.route('/logout')
def logout():
    """Logout and clear session"""
    session.clear()
    return redirect(url_for('login'))

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    app.logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    print(f"Starting CalDAV Web Client on 0.0.0.0:{port}")
    print(f"Debug mode: {debug}")
    print(f"Database: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.endpoint}: {rule.rule} {list(rule.methods)}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)