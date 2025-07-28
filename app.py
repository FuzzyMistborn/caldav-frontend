#!/usr/bin/env python3
"""
CalDAV Web Client for Nextcloud
A Flask-based web application for managing calendar events via CalDAV
Clean version with proper recurring events support
"""

import os
import json
import secrets
import sys
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import caldav
from caldav.lib import error
import pytz
from icalendar import Calendar, Event as ICalEvent, vRecur
import uuid
from dotenv import load_dotenv
from urllib.parse import unquote

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Create Flask app
app = Flask(__name__)

# Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
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
                display_name = cal.name
                if not display_name or display_name == 'None':
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

    def create_event(self, summary, description, location, start_dt, end_dt, rrule=None):
        """Create a new event with optional recurrence"""
        if not self.calendar:
            app.logger.error("No calendar selected for event creation")
            return False
        
        try:
            # Ensure timezone-naive datetimes for CalDAV compatibility
            if hasattr(start_dt, 'tzinfo') and start_dt.tzinfo:
                start_dt = start_dt.replace(tzinfo=None)
            if hasattr(end_dt, 'tzinfo') and end_dt.tzinfo:
                end_dt = end_dt.replace(tzinfo=None)
            
            cal = Calendar()
            cal.add('prodid', '-//CalDAV Web Client//Enhanced//')
            cal.add('version', '2.0')
            
            event = ICalEvent()
            event.add('summary', summary)
            event.add('description', description)
            if location:
                event.add('location', location)
            event.add('dtstart', start_dt)
            event.add('dtend', end_dt)
            event.add('dtstamp', datetime.now(pytz.UTC).replace(tzinfo=None))
            event.add('uid', str(uuid.uuid4()))
            
            # Add recurrence rule if provided
            if rrule:
                try:
                    rrule_dict = self._parse_rrule_string(rrule)
                    if rrule_dict:
                        recur = vRecur(rrule_dict)
                        event.add('rrule', recur)
                        app.logger.info(f"Added RRULE: {rrule_dict}")
                except Exception as e:
                    app.logger.error(f"Error adding RRULE: {e}")
            
            cal.add_component(event)
            ical_data = cal.to_ical()
            
            self.calendar.save_event(ical_data)
            app.logger.info("Event created successfully")
            return True
                
        except Exception as e:
            app.logger.error(f"Error creating event: {e}")
            return False

    def update_event(self, event_url, summary, description, location, start_dt, end_dt, rrule=None):
        """Update an existing event"""
        try:
            # Find the event
            event = self.calendar.event_by_url(event_url)
            
            # Parse current event data
            cal = Calendar.from_ical(event.data)
            
            # Update the VEVENT component
            for component in cal.walk():
                if component.name == "VEVENT":
                    # Update basic properties
                    component['summary'] = summary
                    component['description'] = description
                    
                    if location:
                        component['location'] = location
                    elif 'location' in component:
                        del component['location']
                    
                    # Ensure timezone-naive datetimes
                    if hasattr(start_dt, 'tzinfo') and start_dt.tzinfo:
                        start_dt = start_dt.replace(tzinfo=None)
                    if hasattr(end_dt, 'tzinfo') and end_dt.tzinfo:
                        end_dt = end_dt.replace(tzinfo=None)
                    
                    component['dtstart'] = start_dt
                    component['dtend'] = end_dt
                    component['dtstamp'] = datetime.now(pytz.UTC).replace(tzinfo=None)
                    
                    # Handle recurrence rule
                    if rrule:
                        rrule_dict = self._parse_rrule_string(rrule)
                        if rrule_dict:
                            recur = vRecur(rrule_dict)
                            component['rrule'] = recur
                    elif 'rrule' in component:
                        del component['rrule']
                    
                    break
            
            # Save updated event
            event.data = cal.to_ical()
            event.save()
            app.logger.info("Event updated successfully")
            return True
                
        except Exception as e:
            app.logger.error(f"Error updating event: {e}")
            return False

    def delete_event(self, event_url):
        """Delete a complete event"""
        try:
            if not self.calendar:
                app.logger.error("No calendar selected")
                return False
            
            event = self.calendar.event_by_url(event_url)
            event.delete()
            app.logger.info("Event deleted successfully")
            return True
                
        except Exception as e:
            app.logger.error(f"Error deleting event: {e}")
            return False

    def delete_recurring_occurrence(self, event_url, original_uid, event_date):
        """Delete only a specific occurrence of a recurring event by adding EXDATE"""
        try:
            # Find the original recurring event
            original_event = self._find_event_by_uid(original_uid)
            if not original_event:
                app.logger.error(f"Could not find original event with UID: {original_uid}")
                return False
            
            # Parse event data
            cal = Calendar.from_ical(original_event.data)
            
            # Add EXDATE to exclude this occurrence
            for component in cal.walk():
                if component.name == "VEVENT":
                    # Parse the exception date
                    if 'T' in event_date:
                        exception_datetime = datetime.fromisoformat(event_date.replace('Z', ''))
                    else:
                        exception_datetime = datetime.fromisoformat(event_date)
                    
                    # Get original DTSTART to match format
                    dtstart = component.get('dtstart')
                    if dtstart and hasattr(dtstart.dt, 'date'):
                        if hasattr(dtstart.dt, 'hour'):
                            # Full datetime - preserve time
                            exception_datetime = datetime.combine(
                                exception_datetime.date(), 
                                dtstart.dt.time()
                            )
                        else:
                            # Date only
                            exception_datetime = exception_datetime.date()
                    
                    # Add EXDATE
                    if 'exdate' in component:
                        existing_exdates = component['exdate']
                        if not isinstance(existing_exdates, list):
                            existing_exdates = [existing_exdates]
                        existing_exdates.append(exception_datetime)
                        component['exdate'] = existing_exdates
                    else:
                        component.add('exdate', exception_datetime)
                    
                    break
            
            # Save modified event
            original_event.data = cal.to_ical()
            original_event.save()
            app.logger.info("Recurring occurrence deleted successfully")
            return True
                
        except Exception as e:
            app.logger.error(f"Error deleting recurring occurrence: {e}")
            return False

    def delete_recurring_future(self, event_url, original_uid, event_date):
        """Delete this occurrence and all future occurrences by modifying RRULE"""
        try:
            # Find the original recurring event
            original_event = self._find_event_by_uid(original_uid)
            if not original_event:
                app.logger.error(f"Could not find original event with UID: {original_uid}")
                return False
            
            # Parse event data
            cal = Calendar.from_ical(original_event.data)
            
            # Modify RRULE to end before this date
            for component in cal.walk():
                if component.name == "VEVENT":
                    # Parse the cutoff date
                    if 'T' in event_date:
                        until_date = datetime.fromisoformat(event_date.replace('Z', '')) - timedelta(days=1)
                    else:
                        until_date = datetime.fromisoformat(event_date) - timedelta(days=1)
                    
                    # Get existing RRULE
                    rrule = component.get('rrule')
                    if rrule:
                        rrule_dict = {}
                        for key, value in rrule.items():
                            rrule_dict[key] = value
                        
                        # Set UNTIL date and remove COUNT if present
                        rrule_dict['UNTIL'] = until_date
                        if 'COUNT' in rrule_dict:
                            del rrule_dict['COUNT']
                        
                        # Update the component
                        new_recur = vRecur(rrule_dict)
                        component['rrule'] = new_recur
                    else:
                        # No RRULE found, treat as single event deletion
                        return self.delete_event(event_url)
                    break
            
            # Save modified event
            original_event.data = cal.to_ical()
            original_event.save()
            app.logger.info("Future recurring events deleted successfully")
            return True
                
        except Exception as e:
            app.logger.error(f"Error deleting future recurring events: {e}")
            return False

    def delete_recurring_series(self, original_uid):
        """Delete the entire recurring event series"""
        try:
            # Find the original recurring event
            original_event = self._find_event_by_uid(original_uid)
            if not original_event:
                app.logger.error(f"Could not find original event with UID: {original_uid}")
                return False
            
            # Delete the entire event
            original_event.delete()
            app.logger.info("Entire recurring series deleted successfully")
            return True
                
        except Exception as e:
            app.logger.error(f"Error deleting recurring series: {e}")
            return False

    def _find_event_by_uid(self, uid):
        """Find an event by its UID"""
        try:
            if not self.calendar:
                return None
            
            # Clean the UID (remove recurrence suffix if present)
            clean_uid = uid.split('_recurrence_')[0] if '_recurrence_' in uid else uid
            
            all_objects = list(self.calendar.objects())
            
            for obj in all_objects:
                try:
                    raw_data = obj.data
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode('utf-8', errors='ignore')
                    
                    if isinstance(raw_data, str) and f'UID:{clean_uid}' in raw_data:
                        return obj
                        
                except Exception:
                    continue
            
            return None
            
        except Exception as e:
            app.logger.error(f"Error finding event by UID: {e}")
            return None

    def get_events(self, start_date, end_date):
        """Get events from calendar with recurring event expansion"""
        if not self.calendar:
            return []
        
        try:
            all_objects = list(self.calendar.objects())
            event_list = []
            
            for i, obj in enumerate(all_objects):
                try:
                    raw_data = obj.data
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode('utf-8', errors='ignore')
                    
                    if not isinstance(raw_data, str) or 'BEGIN:VEVENT' not in raw_data:
                        continue
                    
                    obj_url = getattr(obj, 'url', f'/event/{i}')
                    
                    # Parse the event(s) - handle recurring events
                    parsed_events = self._parse_event(raw_data, str(obj_url), start_date, end_date)
                    
                    for parsed_event in parsed_events:
                        # Date range check
                        event_start = parsed_event['start']
                        event_end = parsed_event['end']
                        
                        if (event_start.date() <= end_date.date() and 
                            event_end.date() >= start_date.date()):
                            event_list.append(parsed_event)
                    
                except Exception as obj_error:
                    app.logger.error(f"Error processing object {i}: {obj_error}")
                    continue
            
            app.logger.info(f"Returning {len(event_list)} events")
            return event_list
            
        except Exception as e:
            app.logger.error(f"Error in get_events: {e}")
            return []

    def _parse_event(self, ical_text, event_url, start_date, end_date):
        """Parse iCalendar text and expand recurring events"""
        try:
            from icalendar import Calendar as ICalendar
            cal = ICalendar.from_ical(ical_text)
            
            events = []
            for component in cal.walk():
                if component.name == "VEVENT":
                    event_data = self._parse_ical_component(component, event_url)
                    if event_data:
                        # Handle recurring events
                        if event_data.get('rrule'):
                            expanded = self._expand_recurring_event(event_data, start_date, end_date)
                            events.extend(expanded)
                        else:
                            events.append(event_data)
            
            return events
                    
        except Exception as e:
            app.logger.error(f"Error parsing event: {e}")
            return []

    def _parse_ical_component(self, component, event_url):
        """Parse an iCalendar component into event data"""
        try:
            event_data = {
                'uid': str(component.get('uid', uuid.uuid4())),
                'summary': str(component.get('summary', 'Untitled Event')),
                'description': str(component.get('description', '')),
                'location': str(component.get('location', '')),
                'url': str(event_url),
                'rrule': None
            }
            
            # Parse dates
            dtstart = component.get('dtstart')
            if dtstart:
                if hasattr(dtstart.dt, 'replace'):
                    event_data['start'] = dtstart.dt.replace(tzinfo=None) if dtstart.dt.tzinfo else dtstart.dt
                else:
                    event_data['start'] = dtstart.dt
            else:
                event_data['start'] = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
            
            dtend = component.get('dtend')
            if dtend:
                if hasattr(dtend.dt, 'replace'):
                    event_data['end'] = dtend.dt.replace(tzinfo=None) if dtend.dt.tzinfo else dtend.dt
                else:
                    event_data['end'] = dtend.dt
            else:
                event_data['end'] = event_data['start'] + timedelta(hours=1)
            
            # Parse RRULE
            rrule = component.get('rrule')
            if rrule:
                rrule_dict = rrule.to_ical().decode('utf-8') if hasattr(rrule, 'to_ical') else str(rrule)
                event_data['rrule'] = rrule_dict
            
            return event_data
            
        except Exception as e:
            app.logger.error(f"Error parsing iCalendar component: {e}")
            return None

    def _expand_recurring_event(self, base_event, start_date, end_date):
        """Expand a recurring event into individual occurrences"""
        try:
            events = []
            rrule_text = base_event['rrule']
            
            # Simple RRULE parsing
            rrule_parts = {}
            if rrule_text.startswith('FREQ='):
                for part in rrule_text.split(';'):
                    if '=' in part:
                        key, value = part.split('=', 1)
                        rrule_parts[key.upper()] = value.upper() if key.upper() == 'FREQ' else value
            else:
                return [base_event]
            
            freq = rrule_parts.get('FREQ', '').upper()
            interval = int(rrule_parts.get('INTERVAL', 1))
            count = int(rrule_parts.get('COUNT', 0)) if rrule_parts.get('COUNT') else None
            until_str = rrule_parts.get('UNTIL', '')
            
            # Parse UNTIL date
            until_date = None
            if until_str:
                until_date = self._parse_date(until_str)
            
            # Calculate event duration
            duration = base_event['end'] - base_event['start']
            
            # Generate occurrences
            current_date = base_event['start']
            occurrence_count = 0
            max_occurrences = count if count else 100
            
            # Ensure timezone-naive dates
            if hasattr(start_date, 'tzinfo') and start_date.tzinfo:
                start_date = start_date.replace(tzinfo=None)
            if hasattr(end_date, 'tzinfo') and end_date.tzinfo:
                end_date = end_date.replace(tzinfo=None)
            if hasattr(current_date, 'tzinfo') and current_date.tzinfo:
                current_date = current_date.replace(tzinfo=None)
            if until_date and hasattr(until_date, 'tzinfo') and until_date.tzinfo:
                until_date = until_date.replace(tzinfo=None)
            
            # Expand date range to catch overlapping events
            expanded_start = start_date - timedelta(days=60)
            expanded_end = end_date + timedelta(days=60)
            
            while (occurrence_count < max_occurrences and 
                   current_date <= expanded_end and
                   (not until_date or current_date <= until_date)):
                
                event_end = current_date + duration
                
                # Check if this occurrence overlaps with query range
                if (current_date.date() <= end_date.date() and 
                    event_end.date() >= start_date.date()):
                    
                    event_copy = base_event.copy()
                    event_copy['start'] = current_date
                    event_copy['end'] = event_end
                    event_copy['uid'] = f"{base_event['uid']}_recurrence_{occurrence_count}"
                    event_copy['is_recurring'] = True
                    event_copy['original_uid'] = base_event['uid']
                    event_copy['recurrence_id'] = occurrence_count
                    events.append(event_copy)
                
                occurrence_count += 1
                
                # Calculate next occurrence
                if freq == 'DAILY':
                    current_date += timedelta(days=interval)
                elif freq == 'WEEKLY':
                    current_date += timedelta(weeks=interval)
                elif freq == 'MONTHLY':
                    month = current_date.month + interval
                    year = current_date.year
                    while month > 12:
                        month -= 12
                        year += 1
                    try:
                        current_date = current_date.replace(year=year, month=month)
                    except ValueError:
                        # Handle day overflow
                        import calendar
                        last_day = calendar.monthrange(year, month)[1]
                        day = min(current_date.day, last_day)
                        current_date = current_date.replace(year=year, month=month, day=day)
                elif freq == 'YEARLY':
                    try:
                        current_date = current_date.replace(year=current_date.year + interval)
                    except ValueError:
                        # Handle leap year issues
                        current_date = current_date.replace(year=current_date.year + interval, day=28)
                else:
                    break
                
                # Safety check
                if occurrence_count > 1000:
                    break
            
            return events
            
        except Exception as e:
            app.logger.error(f"Error expanding recurring event: {e}")
            return [base_event]

    def _parse_rrule_string(self, rrule_string):
        """Parse RRULE string into dictionary format"""
        try:
            rrule_dict = {}
            parts = rrule_string.split(';')
            
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    key = key.upper().strip()
                    value = value.strip()
                    
                    if key == 'FREQ':
                        rrule_dict[key] = value.upper()
                    elif key in ['INTERVAL', 'COUNT']:
                        try:
                            rrule_dict[key] = int(value)
                        except ValueError:
                            continue
                    elif key == 'UNTIL':
                        until_date = self._parse_date(value)
                        if until_date:
                            rrule_dict[key] = until_date
                    else:
                        rrule_dict[key] = value
            
            return rrule_dict if rrule_dict else None
        except Exception as e:
            app.logger.error(f"Error parsing RRULE string: {e}")
            return None

    def _parse_date(self, date_str):
        """Parse date string with multiple format support"""
        if not date_str or not isinstance(date_str, str):
            return None
        
        try:
            # Clean the string
            date_str = date_str.strip().replace('T', '').replace('Z', '').replace('-', '').replace(':', '')
            
            # Extract numeric parts
            if len(date_str) >= 8:
                year = int(date_str[:4])
                month = int(date_str[4:6])
                day = int(date_str[6:8])
                
                hour = 0
                minute = 0
                second = 0
                
                if len(date_str) >= 10:
                    hour = int(date_str[8:10])
                if len(date_str) >= 12:
                    minute = int(date_str[10:12])
                if len(date_str) >= 14:
                    second = int(date_str[12:14])
                
                # Validate ranges
                if (1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31 and
                    0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
                    return datetime(year, month, day, hour, minute, second)
            
            return None
            
        except Exception as e:
            app.logger.warning(f"Date parsing failed for '{date_str}': {e}")
            return None

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
        'version': '2.1.0'
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

@app.route('/api/events', methods=['GET', 'POST'])
def api_events():
    """API endpoint to handle both GET (fetch events) and POST (create events)"""
    if request.method == 'GET':
        if 'username' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        
        start_date = request.args.get('start')
        end_date = request.args.get('end')
        
        if not start_date or not end_date:
            return jsonify({'error': 'Missing date parameters'}), 400
        
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({'error': 'Invalid date format'}), 400
        
        # Check session data
        if not all(key in session for key in ['username', 'password', 'caldav_url']):
            return jsonify({'error': 'Session incomplete'}), 401
        
        client = CalDAVClient(session['username'], session['password'], 
                             session['caldav_url'], session.get('server_type', 'generic'))
        
        if not client.connect():
            return jsonify({'error': 'CalDAV connection failed'}), 500
        
        # Get events from all selected calendars
        all_events = []
        prefs = get_user_preferences()
        selected_calendars = prefs.get('selected_calendars', [])
        calendar_colors = prefs.get('calendar_colors', {})
        
        # Default colors
        default_colors = [
            '#3788d8', '#28a745', '#dc3545', '#ffc107', '#6f42c1',
            '#fd7e14', '#20c997', '#e83e8c', '#6c757d', '#17a2b8'
        ]
        
        for i, calendar_name in enumerate(selected_calendars):
            if client.select_calendar(calendar_name):
                events = client.get_events(start_dt, end_dt)
                
                color = calendar_colors.get(calendar_name, 
                                          default_colors[i % len(default_colors)])
                
                for event in events:
                    formatted_event = {
                        'id': f"{calendar_name}:{event['uid']}",
                        'title': event['summary'],
                        'start': event['start'].isoformat(),
                        'end': event['end'].isoformat(),
                        'description': event['description'],
                        'location': event.get('location', ''),
                        'url': event['url'],
                        'backgroundColor': color,
                        'borderColor': color,
                        'calendar_name': calendar_name,
                        'is_recurring': event.get('is_recurring', False),
                        'original_uid': event.get('original_uid', event['uid'])
                    }
                    all_events.append(formatted_event)
        
        return jsonify(all_events)
    
    elif request.method == 'POST':
        # Create event
        if 'username' not in session:
            return jsonify({'error': 'Not authenticated'}), 401
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        try:
            start_dt = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
            end_dt = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
        except (ValueError, KeyError):
            return jsonify({'error': 'Invalid date format'}), 400
        
        # Determine target calendar
        prefs = get_user_preferences()
        target_calendar = data.get('calendar_name')
        if not target_calendar:
            if prefs.get('default_calendar'):
                target_calendar = prefs['default_calendar']
            else:
                selected_calendars = prefs.get('selected_calendars', [])
                if selected_calendars:
                    target_calendar = selected_calendars[0]
                else:
                    return jsonify({'error': 'No calendars available'}), 400
        
        # Check session data
        if not all(key in session for key in ['username', 'password', 'caldav_url']):
            return jsonify({'error': 'Session incomplete'}), 401
        
        client = CalDAVClient(session['username'], session['password'], 
                             session['caldav_url'], session.get('server_type', 'generic'))
        
        if not client.connect():
            return jsonify({'error': 'CalDAV connection failed'}), 500
        
        if not client.select_calendar(target_calendar):
            return jsonify({'error': f'Calendar "{target_calendar}" not found'}), 500
        
        # Build RRULE string if recurrence is specified
        rrule = None
        if data.get('recurring') and data.get('recurring') != 'none':
            rrule_parts = [f"FREQ={data['recurring'].upper()}"]
            
            if data.get('recurring_interval') and int(data.get('recurring_interval', 1)) > 1:
                rrule_parts.append(f"INTERVAL={data['recurring_interval']}")
            
            if data.get('recurring_count'):
                rrule_parts.append(f"COUNT={data['recurring_count']}")
            elif data.get('recurring_until'):
                try:
                    until_date = datetime.fromisoformat(data['recurring_until'] + 'T23:59:59')
                    rrule_parts.append(f"UNTIL={until_date.strftime('%Y%m%dT%H%M%SZ')}")
                except Exception:
                    pass
            
            rrule = ';'.join(rrule_parts)
        
        # Create the event
        try:
            success = client.create_event(
                data.get('title', ''),
                data.get('description', ''),
                data.get('location', ''),
                start_dt,
                end_dt,
                rrule
            )
            
            if success:
                return jsonify({'success': True})
            else:
                return jsonify({'error': 'Failed to create event'}), 500
                
        except Exception as e:
            app.logger.error(f"Exception during event creation: {e}")
            return jsonify({'error': f'Error creating event: {str(e)}'}), 500

@app.route('/api/events/<path:event_id>', methods=['PUT'])
def api_update_event(event_id):
    """API endpoint to update event"""
    event_id = unquote(event_id)
    
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        start_dt = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
    except (ValueError, KeyError):
        return jsonify({'error': 'Invalid date format'}), 400
    
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
    
    event_url = data.get('url')
    if not event_url:
        return jsonify({'error': 'Event URL required for updates'}), 400
    
    # Check session data
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete'}), 401
    
    try:
        client = CalDAVClient(session['username'], session['password'], 
                             session['caldav_url'], session.get('server_type', 'generic'))
        
        if not client.connect():
            return jsonify({'error': 'CalDAV connection failed'}), 500
        
        if not client.select_calendar(calendar_name):
            return jsonify({'error': f'Calendar "{calendar_name}" not found'}), 500
        
        # Build RRULE string if recurrence is specified
        rrule = None
        if data.get('recurring') and data.get('recurring') != 'none':
            rrule_parts = [f"FREQ={data['recurring'].upper()}"]
            
            if data.get('recurring_interval') and int(data.get('recurring_interval', 1)) > 1:
                rrule_parts.append(f"INTERVAL={data['recurring_interval']}")
            
            if data.get('recurring_count'):
                rrule_parts.append(f"COUNT={data['recurring_count']}")
            elif data.get('recurring_until'):
                try:
                    until_date = datetime.fromisoformat(data['recurring_until'] + 'T23:59:59')
                    rrule_parts.append(f"UNTIL={until_date.strftime('%Y%m%dT%H%M%SZ')}")
                except Exception:
                    pass
            
            rrule = ';'.join(rrule_parts)
        
        # Update the event
        success = client.update_event(
            event_url,
            data.get('title', ''),
            data.get('description', ''),
            data.get('location', ''),
            start_dt,
            end_dt,
            rrule
        )
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': 'Failed to update event'}), 500
            
    except Exception as e:
        app.logger.error(f"Exception during event update: {e}")
        return jsonify({'error': f'Error updating event: {str(e)}'}), 500

@app.route('/api/events/<path:event_id>', methods=['DELETE'])
def api_delete_event(event_id):
    """API endpoint to delete event with recurring options support"""
    event_id = unquote(event_id)
    
    if 'username' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
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
    
    # Get delete options from request data
    try:
        data = request.get_json() or {}
    except Exception:
        return jsonify({'error': 'Invalid JSON data'}), 400
    
    event_url = data.get('url')
    delete_type = data.get('deleteType', 'single')
    event_date = data.get('eventDate')
    original_uid = data.get('originalUid')
    
    if not event_url:
        return jsonify({'error': 'Event URL required for deletion'}), 400
    
    # Check session data
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete'}), 401
    
    try:
        client = CalDAVClient(session['username'], session['password'], 
                             session['caldav_url'], session.get('server_type', 'generic'))
        
        if not client.connect():
            return jsonify({'error': 'CalDAV connection failed'}), 500
        
        if not client.select_calendar(calendar_name):
            return jsonify({'error': f'Calendar "{calendar_name}" not found'}), 500
        
        # Handle different delete types
        success = False
        
        if delete_type == 'single':
            success = client.delete_event(event_url)
        elif delete_type == 'this':
            if not original_uid or not event_date:
                return jsonify({'error': 'Missing original UID or event date'}), 400
            success = client.delete_recurring_occurrence(event_url, original_uid, event_date)
        elif delete_type == 'future':
            if not original_uid or not event_date:
                return jsonify({'error': 'Missing original UID or event date'}), 400
            success = client.delete_recurring_future(event_url, original_uid, event_date)
        elif delete_type == 'all':
            if not original_uid:
                return jsonify({'error': 'Missing original UID'}), 400
            success = client.delete_recurring_series(original_uid)
        else:
            return jsonify({'error': f'Invalid delete type: {delete_type}'}), 400
        
        if success:
            return jsonify({'success': True})
        else:
            return jsonify({'error': f'Failed to delete event (type: {delete_type})'}), 500
            
    except Exception as e:
        app.logger.error(f"Exception during deletion: {e}")
        return jsonify({'error': f'Exception during deletion: {str(e)}'}), 500

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
    
    app.logger.info(f"Starting CalDAV Web Client on 0.0.0.0:{port}")
    app.run(host='0.0.0.0', port=port, debug=debug)