#!/usr/bin/env python3
"""
CalDAV Web Client for Nextcloud
A Flask-based web application for managing calendar events via CalDAV
Simplified version with session-only storage (no database)
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
        """Get events - clean version without test events"""
        if not self.calendar:
            return []
        
        try:
            app.logger.info(f"Getting events from {start_date} to {end_date}")
            
            # Get all calendar objects
            all_objects = list(self.calendar.objects())
            app.logger.info(f"Found {len(all_objects)} calendar objects")
            
            event_list = []
            processed_count = 0
            
            for i, obj in enumerate(all_objects):
                try:
                    # Try to get data
                    raw_data = None
                    
                    if hasattr(obj, 'data') and obj.data is not None:
                        raw_data = obj.data
                    elif hasattr(obj, 'get_data'):
                        try:
                            raw_data = obj.get_data()
                        except Exception:
                            pass
                    elif hasattr(obj, 'load'):
                        try:
                            obj.load()
                            raw_data = getattr(obj, 'data', None)
                        except Exception:
                            pass
                    elif hasattr(obj, 'calendar_data'):
                        raw_data = obj.calendar_data
                    
                    if raw_data is None:
                        continue
                    
                    # Convert to string
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode('utf-8', errors='ignore')
                    
                    if not isinstance(raw_data, str) or 'BEGIN:VEVENT' not in raw_data:
                        continue
                    
                    # Get object URL
                    obj_url = getattr(obj, 'url', None) or getattr(obj, 'canonical_url', f'/event/{i}')
                    
                    # Parse the event
                    parsed_event = self.safe_parse_event(raw_data, str(obj_url))
                    if parsed_event:
                        # Date range check
                        event_start = parsed_event['start']
                        event_end = parsed_event['end']
                        
                        if (event_start.date() <= end_date.date() and 
                            event_end.date() >= start_date.date()):
                            event_list.append(parsed_event)
                            app.logger.debug(f"Added event: '{parsed_event['summary']}'")
                    
                    processed_count += 1
                    
                except Exception as obj_error:
                    app.logger.error(f"Error processing object {i}: {obj_error}")
                    continue
            
            app.logger.info(f"Processed {processed_count} objects, returning {len(event_list)} events")
            return event_list
            
        except Exception as e:
            app.logger.error(f"Error in get_events: {e}")
            return []

    def safe_parse_event(self, ical_text, event_url):
        """Safely parse iCalendar text with extensive error handling"""
        try:
            if not ical_text or not isinstance(ical_text, str):
                return None
            
            lines = [line.strip() for line in ical_text.split('\n') if line.strip()]
            
            # Find VEVENT section
            vevent_lines = []
            in_vevent = False
            
            for line in lines:
                if line == 'BEGIN:VEVENT':
                    in_vevent = True
                    continue
                elif line == 'END:VEVENT':
                    break
                elif in_vevent and line:
                    vevent_lines.append(line)
            
            if not vevent_lines:
                app.logger.debug("No VEVENT section found")
                return None
            
            # Initialize with safe defaults
            event_data = {
                'uid': str(uuid.uuid4()),
                'summary': 'Untitled Event',
                'description': '',
                'start': datetime.now().replace(hour=9, minute=0, second=0, microsecond=0),
                'end': datetime.now().replace(hour=10, minute=0, second=0, microsecond=0),
                'url': str(event_url) if event_url else '/unknown'
            }
            
            # Parse each line safely
            for line in vevent_lines:
                try:
                    if ':' not in line:
                        continue
                    
                    colon_pos = line.find(':')
                    prop = line[:colon_pos].strip()
                    value = line[colon_pos + 1:].strip()
                    
                    # Remove property parameters
                    if ';' in prop:
                        prop = prop.split(';')[0]
                    
                    # Parse known properties
                    if prop == 'UID' and value:
                        event_data['uid'] = value[:100]  # Limit length
                    elif prop == 'SUMMARY' and value:
                        event_data['summary'] = value[:200]  # Limit length
                    elif prop == 'DESCRIPTION' and value:
                        # Clean up description
                        clean_desc = value.replace('\\n', '\n').replace('\\,', ',').replace('\\;', ';')
                        event_data['description'] = clean_desc[:500]  # Limit length
                    elif prop == 'DTSTART' and value:
                        parsed_dt = self.robust_date_parse(value)
                        if parsed_dt:
                            event_data['start'] = parsed_dt
                    elif prop == 'DTEND' and value:
                        parsed_dt = self.robust_date_parse(value)
                        if parsed_dt:
                            event_data['end'] = parsed_dt
                            
                except Exception as line_error:
                    app.logger.debug(f"Error parsing line '{line[:50]}': {line_error}")
                    continue
            
            # Validate event data
            if event_data['end'] <= event_data['start']:
                event_data['end'] = event_data['start'] + timedelta(hours=1)
            
            app.logger.debug(f"Parsed event: {event_data['summary']} from {event_data['start']} to {event_data['end']}")
            return event_data
            
        except Exception as e:
            app.logger.error(f"Error in safe_parse_event: {e}")
            return None

    def robust_date_parse(self, date_str):
        """Very robust date parsing with multiple fallbacks"""
        if not date_str or not isinstance(date_str, str):
            return None
        
        try:
            # Clean the string
            original_str = date_str
            date_str = date_str.strip().replace('T', '').replace('Z', '').replace('-', '').replace(':', '')
            
            # Extract numeric parts
            if len(date_str) >= 8:
                try:
                    year = int(date_str[:4])
                    month = int(date_str[4:6])
                    day = int(date_str[6:8])
                    
                    # Validate date parts
                    if year < 1900 or year > 2100:
                        raise ValueError(f"Invalid year: {year}")
                    if month < 1 or month > 12:
                        raise ValueError(f"Invalid month: {month}")
                    if day < 1 or day > 31:
                        raise ValueError(f"Invalid day: {day}")
                    
                    # Extract time if available
                    hour = 0
                    minute = 0
                    second = 0
                    
                    if len(date_str) >= 10:
                        hour = int(date_str[8:10])
                    if len(date_str) >= 12:
                        minute = int(date_str[10:12])
                    if len(date_str) >= 14:
                        second = int(date_str[12:14])
                    
                    # Validate time parts
                    if hour < 0 or hour > 23:
                        hour = 0
                    if minute < 0 or minute > 59:
                        minute = 0
                    if second < 0 or second > 59:
                        second = 0
                    
                    return datetime(year, month, day, hour, minute, second)
                    
                except ValueError as ve:
                    app.logger.warning(f"Date validation failed for '{original_str}': {ve}")
                    return None
            
            app.logger.warning(f"Date string too short: '{original_str}'")
            return None
            
        except Exception as e:
            app.logger.warning(f"Date parsing failed for '{date_str}': {e}")
            return None
    
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

def get_user_preferences():
    """Get user preferences from session with defaults"""
    return session.get('user_preferences', {
        'week_start': 0,
        'calendar_colors': {},
        'default_calendar': None,
        'default_view': 'dayGridMonth',
        'timezone': 'UTC',
        'selected_calendars': [],
        'available_calendars': []
    })

def save_user_preferences(preferences):
    """Save user preferences to session"""
    session['user_preferences'] = preferences
    session.permanent = True

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'CalDAV Web Client is running',
        'version': '2.0.0'
    })

@app.route('/debug')
def debug_info():
    """Debug information endpoint"""
    return jsonify({
        'flask_env': os.environ.get('FLASK_ENV', 'not set'),
        'caldav_server_url': os.environ.get('CALDAV_SERVER_URL', 'not set'),
        'caldav_server_type': os.environ.get('CALDAV_SERVER_TYPE', 'not set'),
        'session_keys': list(session.keys()) if session else [],
        'request_path': request.path,
        'request_url': request.url
    })

@app.route('/')
def index():
    """Main calendar view"""
    if 'username' not in session:
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
                # Store session data
                session.permanent = True
                session['username'] = username
                session['password'] = password
                session['server_url'] = server_url
                session['server_type'] = server_type
                session['caldav_url'] = caldav_url
                
                # Initialize user preferences
                prefs = get_user_preferences()
                prefs['available_calendars'] = calendars
                # Pre-select all calendars if none selected
                if not prefs['selected_calendars']:
                    prefs['selected_calendars'] = [cal[0] for cal in calendars]
                save_user_preferences(prefs)
                
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
    if 'username' not in session:
        return redirect(url_for('login'))
    
    prefs = get_user_preferences()
    calendars = prefs.get('available_calendars', [])
    
    if request.method == 'POST':
        selected_calendars = request.form.getlist('calendars')
        if not selected_calendars:
            return render_template('select_calendar.html', 
                                 calendars=calendars,
                                 selected_calendars=prefs.get('selected_calendars', []),
                                 error="Please select at least one calendar")
        
        # Save selected calendars
        prefs['selected_calendars'] = selected_calendars
        save_user_preferences(prefs)
        
        return redirect(url_for('index'))
    
    selected_calendars = prefs.get('selected_calendars', [])
    
    # If no selection exists, pre-select all calendars
    if not selected_calendars and calendars:
        selected_calendars = [cal[0] for cal in calendars]
        prefs['selected_calendars'] = selected_calendars
        save_user_preferences(prefs)
    
    return render_template('select_calendar.html', 
                         calendars=calendars,
                         selected_calendars=selected_calendars)

@app.route('/api/events')
def api_events():
    """API endpoint to get events from multiple calendars"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated - please log in again'}), 401
    
    start_date = request.args.get('start')
    end_date = request.args.get('end')
    
    if not start_date or not end_date:
        return jsonify({'error': 'Missing date parameters'}), 400
    
    try:
        start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
    
    # Check if we have CalDAV connection info in session
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete - please log in again'}), 401
    
    client = CalDAVClient(session['username'], session['password'], 
                         session['caldav_url'], session.get('server_type', 'generic'))
    
    if not client.connect():
        return jsonify({'error': 'CalDAV connection failed - please check credentials'}), 500
    
    # Get events from all selected calendars
    all_events = []
    prefs = get_user_preferences()
    selected_calendars = prefs.get('selected_calendars', [])
    calendar_colors = prefs.get('calendar_colors', {})
    
    # If no selected calendars, use all available calendars
    if not selected_calendars:
        app.logger.info("No selected calendars found, using all available calendars")
        calendars = client.get_calendars()
        selected_calendars = [cal[0] for cal in calendars]
        prefs['selected_calendars'] = selected_calendars
        save_user_preferences(prefs)
    
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
    if 'username' not in session:
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
    
    # Determine target calendar
    prefs = get_user_preferences()
    target_calendar = data.get('calendar_name')
    if not target_calendar:
        # First try user's default calendar
        if prefs.get('default_calendar'):
            target_calendar = prefs['default_calendar']
        else:
            # Fall back to first selected calendar
            selected_calendars = prefs.get('selected_calendars', [])
            if not selected_calendars:
                # If no selected calendars, try to get first available calendar
                available_calendars = prefs.get('available_calendars', [])
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
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    prefs = get_user_preferences()
    return jsonify({
        'week_start': prefs.get('week_start', 0),
        'calendar_colors': prefs.get('calendar_colors', {}),
        'default_calendar': prefs.get('default_calendar'),
        'default_view': prefs.get('default_view', 'dayGridMonth'),
        'timezone': prefs.get('timezone', 'UTC')
    })

@app.route('/api/settings', methods=['POST'])
def update_settings():
    """API endpoint to update user settings"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    prefs = get_user_preferences()
    
    # Update settings
    if 'week_start' in data:
        prefs['week_start'] = int(data['week_start'])
    
    if 'calendar_colors' in data:
        prefs['calendar_colors'] = data['calendar_colors']
    
    if 'default_calendar' in data:
        prefs['default_calendar'] = data['default_calendar']
    
    if 'default_view' in data:
        prefs['default_view'] = data['default_view']
    
    if 'timezone' in data:
        prefs['timezone'] = data['timezone']
    
    save_user_preferences(prefs)
    
    return jsonify({'success': True})

@app.route('/api/calendar-selection', methods=['GET'])
def get_calendar_selection():
    """API endpoint to get current calendar selection"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    prefs = get_user_preferences()
    
    return jsonify({
        'calendars': prefs.get('available_calendars', []),
        'selected_calendars': prefs.get('selected_calendars', []),
        'calendar_colors': prefs.get('calendar_colors', {}),
        'week_start': prefs.get('week_start', 0)
    })

@app.route('/api/calendar-selection', methods=['POST'])
def update_calendar_selection():
    """API endpoint to update calendar selection"""
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    if not data or 'calendars' not in data:
        return jsonify({'error': 'No calendar data provided'}), 400
    
    prefs = get_user_preferences()
    prefs['selected_calendars'] = data['calendars']
    save_user_preferences(prefs)
    
    return jsonify({'success': True})

@app.route('/api/events/<event_id>', methods=['PUT'])
def api_update_event(event_id):
    """API endpoint to update event"""
    if 'username' not in session:
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
        prefs = get_user_preferences()
        selected_calendars = prefs.get('selected_calendars', [])
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
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    app.logger.info(f"Deleting event: {event_id}")
    
    # Extract calendar name from event ID
    if ':' in event_id:
        calendar_name, uid = event_id.split(':', 1)
    else:
        prefs = get_user_preferences()
        selected_calendars = prefs.get('selected_calendars', [])
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
    app.logger.error(f"Internal error: {error}")
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Get port from environment variable or default to 5000
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') == 'development'
    
    print(f"Starting CalDAV Web Client on 0.0.0.0:{port}")
    print(f"Debug mode: {debug}")
    print(f"Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.endpoint}: {rule.rule} {list(rule.methods)}")
    
    app.run(host='0.0.0.0', port=port, debug=debug)