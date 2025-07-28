"""
CalDAV Web Client for Nextcloud
A Flask-based web application for managing calendar events via CalDAV
Enhanced version with recurring events and location support
"""

import os
import json
import secrets
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import caldav
from caldav.lib import error
import pytz
from icalendar import Calendar, Event as ICalEvent, vRecur
import uuid
from dotenv import load_dotenv
import sys
import logging



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

# Configure logging to show debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)

# Also ensure Flask debug mode is on
app.debug = True

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
                    
                    # Parse the event(s) - handle recurring events
                    parsed_events = self.safe_parse_event(raw_data, str(obj_url), start_date, end_date)
                    if parsed_events:
                        for parsed_event in parsed_events:
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

    def safe_parse_event(self, ical_text, event_url, start_date, end_date):
        """Safely parse iCalendar text with extensive error handling and recurring event support"""
        try:
            if not ical_text or not isinstance(ical_text, str):
                return []
            
            # Try using icalendar library first for better RRULE parsing
            try:
                from icalendar import Calendar as ICalendar
                cal = ICalendar.from_ical(ical_text)
                
                events = []
                for component in cal.walk():
                    if component.name == "VEVENT":
                        event_data = self.parse_ical_component(component, event_url)
                        if event_data:
                            # Handle recurring events
                            if event_data.get('rrule'):
                                expanded = self.expand_recurring_event(event_data, start_date, end_date)
                                events.extend(expanded)
                            else:
                                events.append(event_data)
                
                if events:
                    return events
                    
            except Exception as ical_error:
                app.logger.debug(f"iCalendar parsing failed, falling back to manual parsing: {ical_error}")
            
            # Fall back to manual parsing
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
                return []
            
            # Initialize with safe defaults
            event_data = {
                'uid': str(uuid.uuid4()),
                'summary': 'Untitled Event',
                'description': '',
                'location': '',
                'start': datetime.now().replace(hour=9, minute=0, second=0, microsecond=0),
                'end': datetime.now().replace(hour=10, minute=0, second=0, microsecond=0),
                'url': str(event_url) if event_url else '/unknown',
                'rrule': None
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
                    elif prop == 'LOCATION' and value:
                        # Clean up location
                        clean_location = value.replace('\\n', '\n').replace('\\,', ',').replace('\\;', ';')
                        event_data['location'] = clean_location[:200]  # Limit length
                    elif prop == 'DTSTART' and value:
                        parsed_dt = self.robust_date_parse(value)
                        if parsed_dt:
                            event_data['start'] = parsed_dt
                    elif prop == 'DTEND' and value:
                        parsed_dt = self.robust_date_parse(value)
                        if parsed_dt:
                            event_data['end'] = parsed_dt
                    elif prop == 'RRULE' and value:
                        event_data['rrule'] = value
                            
                except Exception as line_error:
                    app.logger.debug(f"Error parsing line '{line[:50]}': {line_error}")
                    continue
            
            # Validate event data
            if event_data['end'] <= event_data['start']:
                event_data['end'] = event_data['start'] + timedelta(hours=1)
            
            # Handle recurring events
            if event_data['rrule']:
                return self.expand_recurring_event(event_data, start_date, end_date)
            else:
                return [event_data]
            
        except Exception as e:
            app.logger.error(f"Error in safe_parse_event: {e}")
            return []

    def parse_ical_component(self, component, event_url):
        """Parse an iCalendar component into event data"""
        try:
            event_data = {
                'uid': str(component.get('uid', uuid.uuid4())),
                'summary': str(component.get('summary', 'Untitled Event')),
                'description': str(component.get('description', '')),
                'location': str(component.get('location', '')),
                'url': str(event_url) if event_url else '/unknown',
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
                # Convert RRULE to string format
                rrule_str = str(rrule).replace('vRecur(', '').replace(')', '')
                # Clean up the format
                parts = []
                for item in str(rrule).split("'"):
                    if '=' in item and not item.startswith('v'):
                        parts.append(item)
                
                if parts:
                    event_data['rrule'] = ';'.join(parts)
                else:
                    # Fallback to direct string conversion
                    rrule_dict = rrule.to_ical().decode('utf-8') if hasattr(rrule, 'to_ical') else str(rrule)
                    event_data['rrule'] = rrule_dict
            
            return event_data
            
        except Exception as e:
            app.logger.error(f"Error parsing iCalendar component: {e}")
            return None

    def expand_recurring_event(self, base_event, start_date, end_date):
        """Expand a recurring event into individual occurrences within the date range"""
        try:
            events = []
            rrule_text = base_event['rrule']
            
            # Parse RRULE - handle different formats
            rrule_parts = {}
            
            # Clean up the RRULE text
            if rrule_text.startswith('FREQ='):
                # Standard format: FREQ=WEEKLY;INTERVAL=1;COUNT=5
                for part in rrule_text.split(';'):
                    if '=' in part:
                        key, value = part.split('=', 1)
                        rrule_parts[key.upper()] = value.upper() if key.upper() in ['FREQ'] else value
            else:
                # Handle other formats
                return [base_event]  # Return original event if we can't parse
            
            freq = rrule_parts.get('FREQ', '').upper()
            interval = int(rrule_parts.get('INTERVAL', 1))
            count = int(rrule_parts.get('COUNT', 0)) if rrule_parts.get('COUNT') else None
            until_str = rrule_parts.get('UNTIL', '')
            
            # Parse UNTIL date if present
            until_date = None
            if until_str:
                until_date = self.robust_date_parse(until_str)
            
            # Calculate event duration
            duration = base_event['end'] - base_event['start']
            
            # Generate occurrences
            current_date = base_event['start']
            occurrence_count = 0
            max_occurrences = count if count else 100  # Reasonable limit to prevent infinite loops
            
            # Ensure all dates are timezone-naive for comparison
            if hasattr(start_date, 'tzinfo') and start_date.tzinfo:
                start_date = start_date.replace(tzinfo=None)
            if hasattr(end_date, 'tzinfo') and end_date.tzinfo:
                end_date = end_date.replace(tzinfo=None)
            if hasattr(current_date, 'tzinfo') and current_date.tzinfo:
                current_date = current_date.replace(tzinfo=None)
            if until_date and hasattr(until_date, 'tzinfo') and until_date.tzinfo:
                until_date = until_date.replace(tzinfo=None)
            
            # Expand the date range to catch events that might overlap
            expanded_start = start_date - timedelta(days=60)
            expanded_end = end_date + timedelta(days=60)
            
            while (occurrence_count < max_occurrences and 
                   current_date <= expanded_end and
                   (not until_date or current_date <= until_date)):
                
                event_end = current_date + duration
                
                # Check if this occurrence overlaps with our query range
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
                    # Add months more carefully
                    month = current_date.month
                    year = current_date.year
                    month += interval
                    while month > 12:
                        month -= 12
                        year += 1
                    try:
                        current_date = current_date.replace(year=year, month=month)
                    except ValueError:
                        # Handle day overflow (e.g., Jan 31 -> Feb 28)
                        import calendar
                        last_day = calendar.monthrange(year, month)[1]
                        day = min(current_date.day, last_day)
                        current_date = current_date.replace(year=year, month=month, day=day)
                elif freq == 'YEARLY':
                    try:
                        current_date = current_date.replace(year=current_date.year + interval)
                    except ValueError:
                        # Handle leap year issues (Feb 29)
                        current_date = current_date.replace(year=current_date.year + interval, day=28)
                else:
                    break
                
                # Safety check to prevent infinite loops
                if occurrence_count > 1000:
                    break
            
            return events
            
        except Exception as e:
            app.logger.error(f"Error expanding recurring event: {e}")
            # Return the base event if we can't expand it
            return [base_event]

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
    
    def create_event(self, summary, description, location, start_dt, end_dt, rrule=None):
        """Create a new event with optional recurrence and location"""
        if not self.calendar:
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
                    app.logger.info(f"Adding RRULE to event: {rrule}")
                    # Parse and add RRULE
                    rrule_dict = self.parse_rrule_string(rrule)
                    if rrule_dict:
                        recur = vRecur(rrule_dict)
                        event.add('rrule', recur)
                        app.logger.info(f"Successfully added RRULE: {rrule_dict}")
                    else:
                        app.logger.error(f"Failed to parse RRULE: {rrule}")
                except Exception as e:
                    app.logger.error(f"Error adding RRULE: {e}")
            
            cal.add_component(event)
            
            ical_data = cal.to_ical()
            app.logger.debug(f"Generated iCal data:\n{ical_data.decode('utf-8')}")
            
            self.calendar.save_event(ical_data)
            return True
        except Exception as e:
            app.logger.error(f"Error creating event: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            return False
    
    def parse_rrule_string(self, rrule_string):
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
                        # Parse UNTIL date
                        until_date = self.robust_date_parse(value)
                        if until_date:
                            rrule_dict[key] = until_date
                    else:
                        rrule_dict[key] = value
            
            return rrule_dict if rrule_dict else None
        except Exception as e:
            app.logger.error(f"Error parsing RRULE string: {e}")
            return None
    
    def update_event(self, event_url, summary, description, location, start_dt, end_dt, rrule=None):
        """Update an existing event"""
        try:
            event = self.calendar.event_by_url(event_url)
            cal = Calendar.from_ical(event.data)
            
            for component in cal.walk():
                if component.name == "VEVENT":
                    # Update basic properties
                    component['summary'] = summary
                    component['description'] = description
                    
                    # Handle location
                    if location:
                        component['location'] = location
                    elif 'location' in component:
                        del component['location']
                    
                    # Ensure timezone-naive datetimes for CalDAV compatibility
                    if hasattr(start_dt, 'tzinfo') and start_dt.tzinfo:
                        start_dt = start_dt.replace(tzinfo=None)
                    if hasattr(end_dt, 'tzinfo') and end_dt.tzinfo:
                        end_dt = end_dt.replace(tzinfo=None)
                    
                    # Update dates - ensure they exist
                    component['dtstart'] = start_dt
                    component['dtend'] = end_dt
                    component['dtstamp'] = datetime.now(pytz.UTC).replace(tzinfo=None)
                    
                    # Handle recurrence rule
                    if rrule:
                        try:
                            rrule_dict = self.parse_rrule_string(rrule)
                            if rrule_dict:
                                recur = vRecur(rrule_dict)
                                component['rrule'] = recur
                        except Exception as e:
                            app.logger.error(f"Error updating RRULE: {e}")
                    elif 'rrule' in component:
                        del component['rrule']
                    
                    break
            
            # Generate the updated iCal data
            updated_ical = cal.to_ical()
            
            event.data = updated_ical
            event.save()
            return True
        except Exception as e:
            app.logger.error(f"Error updating event: {e}")
            return False
    
    def delete_event(self, event_url):
        """Delete an event with debugging"""
        try:
            print(f"DEBUG: delete_event called with URL: {event_url}")
            
            if not self.calendar:
                print("DEBUG: No calendar selected")
                return False
            
            print(f"DEBUG: Attempting to find event by URL")
            
            # Try to get the event object
            try:
                event = self.calendar.event_by_url(event_url)
                print(f"DEBUG: Found event object: {event}")
            except Exception as e:
                print(f"DEBUG: Error finding event by URL: {e}")
                # Try alternative approach - find by searching all events
                print("DEBUG: Trying alternative approach to find event")
                
                try:
                    all_objects = list(self.calendar.objects())
                    print(f"DEBUG: Found {len(all_objects)} total objects in calendar")
                    
                    for i, obj in enumerate(all_objects):
                        try:
                            obj_url = getattr(obj, 'url', None) or getattr(obj, 'canonical_url', None)
                            if obj_url and str(obj_url) == event_url:
                                print(f"DEBUG: Found matching event at index {i}")
                                event = obj
                                break
                        except Exception as obj_e:
                            print(f"DEBUG: Error checking object {i}: {obj_e}")
                            continue
                    else:
                        print(f"DEBUG: No event found with URL: {event_url}")
                        return False
                        
                except Exception as search_e:
                    print(f"DEBUG: Error searching for event: {search_e}")
                    return False
            
            # Try to delete the event
            try:
                print(f"DEBUG: Attempting to delete event")
                event.delete()
                print(f"DEBUG: Event deleted successfully")
                return True
            except Exception as delete_e:
                print(f"DEBUG: Error deleting event: {delete_e}")
                import traceback
                print(f"DEBUG: Delete traceback: {traceback.format_exc()}")
                return False
                
        except Exception as e:
            print(f"DEBUG: Error in delete_event: {e}")
            import traceback
            print(f"DEBUG: Full traceback: {traceback.format_exc()}")
            return False

    def delete_recurring_occurrence(self, event_url, original_uid, event_date):
        """Delete only a specific occurrence of a recurring event"""
        try:
            app.logger.info(f"Attempting to delete recurring occurrence: {original_uid} on {event_date}")
            
            # Find the original recurring event by UID
            original_event = self.find_event_by_uid(original_uid)
            if not original_event:
                app.logger.error(f"Could not find original event with UID: {original_uid}")
                return False
            
            app.logger.info(f"Found original event for UID: {original_uid}")
            
            # Get the event data
            try:
                raw_data = original_event.data
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode('utf-8', errors='ignore')
                
                cal = Calendar.from_ical(raw_data)
            except Exception as e:
                app.logger.error(f"Error parsing original event data: {e}")
                return False
            
            # Add an EXDATE (exception date) to exclude this occurrence
            event_modified = False
            for component in cal.walk():
                if component.name == "VEVENT":
                    try:
                        # Parse the event date - handle different formats
                        if 'T' in event_date:
                            exception_date = datetime.fromisoformat(event_date.replace('Z', '')).date()
                        else:
                            exception_date = datetime.fromisoformat(event_date).date()
                        
                        app.logger.info(f"Adding EXDATE for: {exception_date}")
                        
                        # Add EXDATE property
                        if 'exdate' in component:
                            # Add to existing EXDATE
                            existing_exdates = component['exdate']
                            if not isinstance(existing_exdates, list):
                                existing_exdates = [existing_exdates]
                            existing_exdates.append(exception_date)
                            component['exdate'] = existing_exdates
                            app.logger.info(f"Added to existing EXDATE list")
                        else:
                            # Create new EXDATE
                            component.add('exdate', exception_date)
                            app.logger.info(f"Created new EXDATE")
                        
                        event_modified = True
                        break
                    except Exception as e:
                        app.logger.error(f"Error adding EXDATE: {e}")
                        return False
            
            if not event_modified:
                app.logger.error("No VEVENT component found to modify")
                return False
            
            # Save the modified event
            try:
                original_event.data = cal.to_ical()
                original_event.save()
                app.logger.info("Successfully saved modified recurring event with EXDATE")
                return True
            except Exception as e:
                app.logger.error(f"Error saving modified event: {e}")
                return False
                
        except Exception as e:
            app.logger.error(f"Error deleting recurring occurrence: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            return False

    def delete_recurring_future(self, event_url, original_uid, event_date):
        """Delete this occurrence and all future occurrences"""
        try:
            app.logger.info(f"Attempting to delete future recurring events: {original_uid} from {event_date}")
            
            # Find the original recurring event by UID
            original_event = self.find_event_by_uid(original_uid)
            if not original_event:
                app.logger.error(f"Could not find original event with UID: {original_uid}")
                return False
            
            app.logger.info(f"Found original event for UID: {original_uid}")
            
            # Get the event data
            try:
                raw_data = original_event.data
                if isinstance(raw_data, bytes):
                    raw_data = raw_data.decode('utf-8', errors='ignore')
                
                cal = Calendar.from_ical(raw_data)
            except Exception as e:
                app.logger.error(f"Error parsing original event data: {e}")
                return False
            
            # Modify the RRULE to end before this date
            event_modified = False
            for component in cal.walk():
                if component.name == "VEVENT":
                    try:
                        # Parse the event date and set UNTIL to day before
                        if 'T' in event_date:
                            until_date = datetime.fromisoformat(event_date.replace('Z', '')) - timedelta(days=1)
                        else:
                            until_date = datetime.fromisoformat(event_date) - timedelta(days=1)
                        
                        app.logger.info(f"Setting RRULE UNTIL date to: {until_date}")
                        
                        # Get existing RRULE
                        rrule = component.get('rrule')
                        if rrule:
                            # Convert to dict and modify
                            rrule_dict = {}
                            for key, value in rrule.items():
                                rrule_dict[key] = value
                            
                            # Set UNTIL date and remove COUNT if present
                            rrule_dict['UNTIL'] = until_date
                            if 'COUNT' in rrule_dict:
                                del rrule_dict['COUNT']
                                app.logger.info("Removed COUNT from RRULE")
                            
                            # Update the component
                            new_recur = vRecur(rrule_dict)
                            component['rrule'] = new_recur
                            app.logger.info(f"Updated RRULE with UNTIL: {until_date}")
                            event_modified = True
                        else:
                            app.logger.warning("No RRULE found in event - treating as single event deletion")
                            # If no RRULE, just delete the whole event
                            return self.delete_event(event_url)
                        break
                    except Exception as e:
                        app.logger.error(f"Error modifying RRULE: {e}")
                        return False
            
            if not event_modified:
                app.logger.error("No VEVENT component with RRULE found to modify")
                return False
            
            # Save the modified event
            try:
                original_event.data = cal.to_ical()
                original_event.save()
                app.logger.info("Successfully saved modified recurring event with updated RRULE")
                return True
            except Exception as e:
                app.logger.error(f"Error saving modified event: {e}")
                return False
                
        except Exception as e:
            app.logger.error(f"Error deleting future recurring events: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            return False

    def delete_recurring_series(self, original_uid):
        """Delete the entire recurring event series"""
        try:
            app.logger.info(f"Attempting to delete entire recurring series: {original_uid}")
            
            # Find the original recurring event by UID
            original_event = self.find_event_by_uid(original_uid)
            if not original_event:
                app.logger.error(f"Could not find original event with UID: {original_uid}")
                return False
            
            app.logger.info(f"Found original event for UID: {original_uid}")
            
            # Delete the entire event
            try:
                original_event.delete()
                app.logger.info("Successfully deleted entire recurring event series")
                return True
            except Exception as e:
                app.logger.error(f"Error deleting event: {e}")
                return False
                
        except Exception as e:
            app.logger.error(f"Error deleting recurring series: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
            return False

    def find_event_by_uid(self, uid):
        """Find an event by its UID with improved logging"""
        try:
            app.logger.info(f"Searching for event with UID: {uid}")
            
            # Clean the UID (remove recurrence suffix if present)
            clean_uid = uid.split('_recurrence_')[0] if '_recurrence_' in uid else uid
            app.logger.info(f"Cleaned UID: {clean_uid}")
            
            if not self.calendar:
                app.logger.error("No calendar selected")
                return None
            
            all_objects = list(self.calendar.objects())
            app.logger.info(f"Searching through {len(all_objects)} calendar objects")
            
            for i, obj in enumerate(all_objects):
                try:
                    raw_data = obj.data
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode('utf-8', errors='ignore')
                    
                    if f'UID:{clean_uid}' in raw_data:
                        app.logger.info(f"Found event with UID {clean_uid} at object index {i}")
                        return obj
                        
                    # Also check for UID without colon (some formats)
                    if f'UID {clean_uid}' in raw_data or clean_uid in raw_data:
                        app.logger.info(f"Found event with UID {clean_uid} (alternative format) at object index {i}")
                        return obj
                        
                except Exception as e:
                    app.logger.debug(f"Error checking object {i}: {e}")
                    continue
            
            app.logger.warning(f"No event found with UID: {clean_uid}")
            return None
            
        except Exception as e:
            app.logger.error(f"Error finding event by UID: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
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
                    'location': event.get('location', ''),
                    'url': event['url'],
                    'backgroundColor': color,
                    'borderColor': color,
                    'calendar_name': calendar_name,
                    'is_recurring': event.get('is_recurring', False),
                    'original_uid': event.get('original_uid', event['uid'])
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
    
    try:
        start_dt = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
    except (ValueError, KeyError) as e:
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
    
    # Check CalDAV connection info
    if not all(key in session for key in ['username', 'password', 'caldav_url']):
        return jsonify({'error': 'Session incomplete - please log in again'}), 401
    
    # Create CalDAV client
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
            # Convert until date to proper format
            try:
                until_date = datetime.fromisoformat(data['recurring_until'] + 'T23:59:59')
                rrule_parts.append(f"UNTIL={until_date.strftime('%Y%m%dT%H%M%SZ')}")
            except Exception as e:
                app.logger.error(f"Error parsing recurring_until date: {e}")
        
        rrule = ';'.join(rrule_parts)
    
    # Create the event
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
    
    # Build RRULE string if recurrence is specified
    rrule = None
    if data.get('recurring') and data.get('recurring') != 'none':
        rrule_parts = [f"FREQ={data['recurring'].upper()}"]
        
        if data.get('recurring_interval') and int(data.get('recurring_interval', 1)) > 1:
            rrule_parts.append(f"INTERVAL={data['recurring_interval']}")
        
        if data.get('recurring_count'):
            rrule_parts.append(f"COUNT={data['recurring_count']}")
        elif data.get('recurring_until'):
            # Convert until date to proper format
            try:
                until_date = datetime.fromisoformat(data['recurring_until'] + 'T23:59:59')
                rrule_parts.append(f"UNTIL={until_date.strftime('%Y%m%dT%H%M%SZ')}")
            except Exception as e:
                app.logger.error(f"Error parsing recurring_until date: {e}")
        
        rrule = ';'.join(rrule_parts)
        app.logger.info(f"Generated RRULE for update: {rrule}")
    
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
        app.logger.info("Event updated successfully")
        return jsonify({'success': True})
    else:
        app.logger.error("Failed to update event")
        return jsonify({'error': 'Failed to update event'}), 500

    @app.route('/api/events/<event_id>', methods=['DELETE'])
    def api_delete_event(event_id):
        """API endpoint to delete event with extensive debugging"""
        print(f"DEBUG: Delete request received for event_id: {event_id}")
        
        if 'username' not in session:
            print("DEBUG: User not authenticated")
            return jsonify({'error': 'Not authenticated'}), 401
        
        print(f"DEBUG: User authenticated: {session['username']}")
        
        # Extract calendar name from event ID
        if ':' in event_id:
            calendar_name, uid = event_id.split(':', 1)
            print(f"DEBUG: Extracted calendar_name: {calendar_name}, uid: {uid}")
        else:
            prefs = get_user_preferences()
            selected_calendars = prefs.get('selected_calendars', [])
            calendar_name = selected_calendars[0] if selected_calendars else None
            uid = event_id
            print(f"DEBUG: Using first selected calendar: {calendar_name}, uid: {uid}")
        
        if not calendar_name:
            print("DEBUG: Cannot determine target calendar")
            return jsonify({'error': 'Cannot determine target calendar'}), 400
        
        # Get event URL and delete options from request data
        try:
            data = request.get_json() or {}
            print(f"DEBUG: Request data: {data}")
        except Exception as e:
            print(f"DEBUG: Error parsing request JSON: {e}")
            return jsonify({'error': 'Invalid JSON data'}), 400
        
        event_url = data.get('url')
        delete_type = data.get('deleteType', 'single')
        event_date = data.get('eventDate')
        original_uid = data.get('originalUid')
        
        print(f"DEBUG: Delete parameters - Type: {delete_type}, URL: {event_url}, Date: {event_date}, Original UID: {original_uid}")
        
        if not event_url:
            print("DEBUG: Event URL is missing")
            return jsonify({'error': 'Event URL required for deletion'}), 400
        
        # Check CalDAV connection info
        required_session_keys = ['username', 'password', 'caldav_url']
        missing_keys = [key for key in required_session_keys if key not in session]
        if missing_keys:
            print(f"DEBUG: Missing session keys: {missing_keys}")
            return jsonify({'error': 'Session incomplete - please log in again'}), 401
        
        print(f"DEBUG: Creating CalDAV client for {session['username']} at {session['caldav_url']}")
        
        try:
            client = CalDAVClient(session['username'], session['password'], 
                                session['caldav_url'], session.get('server_type', 'generic'))
            print("DEBUG: CalDAV client created successfully")
        except Exception as e:
            print(f"DEBUG: Error creating CalDAV client: {e}")
            return jsonify({'error': f'Error creating CalDAV client: {str(e)}'}), 500
        
        try:
            if not client.connect():
                print("DEBUG: CalDAV connection failed")
                return jsonify({'error': 'CalDAV connection failed'}), 500
            print("DEBUG: CalDAV connection successful")
        except Exception as e:
            print(f"DEBUG: Exception during CalDAV connection: {e}")
            return jsonify({'error': f'CalDAV connection error: {str(e)}'}), 500
        
        try:
            if not client.select_calendar(calendar_name):
                print(f"DEBUG: Calendar selection failed: {calendar_name}")
                return jsonify({'error': f'Calendar "{calendar_name}" not found'}), 500
            print(f"DEBUG: Calendar selected successfully: {calendar_name}")
        except Exception as e:
            print(f"DEBUG: Exception during calendar selection: {e}")
            return jsonify({'error': f'Calendar selection error: {str(e)}'}), 500
        
        # Handle different delete types
        success = False
        error_message = None
        
        try:
            print(f"DEBUG: Starting deletion process for type: {delete_type}")
            
            if delete_type == 'single':
                print("DEBUG: Attempting single event deletion")
                success = client.delete_event(event_url)
                print(f"DEBUG: Single deletion result: {success}")
                
            elif delete_type == 'this':
                print("DEBUG: Attempting single occurrence deletion of recurring event")
                if not original_uid or not event_date:
                    error_message = 'Missing original UID or event date for recurring deletion'
                    print(f"DEBUG: {error_message}")
                    return jsonify({'error': error_message}), 400
                success = client.delete_recurring_occurrence(event_url, original_uid, event_date)
                print(f"DEBUG: Recurring occurrence deletion result: {success}")
                
            elif delete_type == 'future':
                print("DEBUG: Attempting future occurrences deletion")
                if not original_uid or not event_date:
                    error_message = 'Missing original UID or event date for future deletion'
                    print(f"DEBUG: {error_message}")
                    return jsonify({'error': error_message}), 400
                success = client.delete_recurring_future(event_url, original_uid, event_date)
                print(f"DEBUG: Future deletion result: {success}")
                
            elif delete_type == 'all':
                print("DEBUG: Attempting entire series deletion")
                if not original_uid:
                    error_message = 'Missing original UID for series deletion'
                    print(f"DEBUG: {error_message}")
                    return jsonify({'error': error_message}), 400
                success = client.delete_recurring_series(original_uid)
                print(f"DEBUG: Series deletion result: {success}")
                
            else:
                error_message = f'Invalid delete type: {delete_type}'
                print(f"DEBUG: {error_message}")
                return jsonify({'error': error_message}), 400
            
            if success:
                print(f"DEBUG: Event deletion successful for type: {delete_type}")
                return jsonify({'success': True})
            else:
                error_message = f'Failed to delete event (type: {delete_type})'
                print(f"DEBUG: {error_message}")
                return jsonify({'error': error_message}), 500
                
        except Exception as e:
            error_message = f'Exception during deletion: {str(e)}'
            print(f"DEBUG: {error_message}")
            import traceback
            print(f"DEBUG: Full traceback: {traceback.format_exc()}")
            return jsonify({'error': error_message}), 500

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