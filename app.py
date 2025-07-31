#!/usr/bin/env python3
"""
CalDAV Web Client for Nextcloud
A Flask-based web application for managing calendar events via CalDAV
Complete version with recurring events and enhanced debugging features
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
import traceback

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
            app.logger.info(f"Successfully connected to CalDAV server: {self.base_url}")
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
                app.logger.info(f"Found calendar: {display_name} at {cal.url}")
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
                    app.logger.info(f"Selected calendar: {display_name}")
                    return True
            app.logger.warning(f"Calendar not found: {calendar_name}")
            return False
        except Exception as e:
            app.logger.error(f"Error selecting calendar: {e}")
            return False

    def debug_raw_calendar_data(self):
        """Enhanced debug method to inspect raw calendar data and parsing"""
        if not self.calendar:
            app.logger.error("No calendar selected for debugging")
            return
        
        try:
            app.logger.info(f"=== ENHANCED CALENDAR DEBUG: {self.calendar.name} ===")
            app.logger.info(f"Calendar URL: {self.calendar.url}")
            
            # Get all objects in the calendar
            all_objects = list(self.calendar.objects())
            app.logger.info(f"Total objects found: {len(all_objects)}")
            
            if len(all_objects) == 0:
                app.logger.warning("No objects found in calendar - calendar might be empty")
                return
            
            # Inspect each object in detail
            for i, obj in enumerate(all_objects):
                try:
                    app.logger.info(f"--- OBJECT {i+1} DETAILED ANALYSIS ---")
                    app.logger.info(f"Object type: {type(obj)}")
                    app.logger.info(f"Object URL: {getattr(obj, 'url', 'No URL')}")
                    
                    # Get raw data in multiple ways
                    raw_data = None
                    
                    # Try different methods to get data
                    data_methods = [
                        ('obj.data', lambda: getattr(obj, 'data', None)),
                        ('obj.get_data()', lambda: obj.get_data() if hasattr(obj, 'get_data') else None),
                        ('str(obj)', lambda: str(obj) if obj else None)
                    ]
                    
                    for method_name, method_func in data_methods:
                        try:
                            test_data = method_func()
                            if test_data:
                                app.logger.info(f"  {method_name} succeeded - length: {len(test_data) if test_data else 0}")
                                if not raw_data:
                                    raw_data = test_data
                            else:
                                app.logger.info(f"  {method_name} returned None/empty")
                        except Exception as e:
                            app.logger.warning(f"  {method_name} failed: {e}")
                    
                    if raw_data is None:
                        app.logger.warning(f"Object {i+1}: No data available via any method")
                        continue
                    
                    # Convert to string if needed
                    if isinstance(raw_data, bytes):
                        try:
                            raw_data = raw_data.decode('utf-8')
                            app.logger.info(f"  Decoded bytes to UTF-8 string")
                        except UnicodeDecodeError as e:
                            app.logger.error(f"  Failed to decode bytes: {e}")
                            try:
                                raw_data = raw_data.decode('latin1')
                                app.logger.info(f"  Fallback: decoded bytes to latin1 string")
                            except Exception as e2:
                                app.logger.error(f"  Complete decode failure: {e2}")
                                continue
                    
                    app.logger.info(f"Object {i+1} final data length: {len(raw_data)} characters")
                    
                    # Show first few lines for inspection
                    lines = raw_data.split('\n')[:10]
                    app.logger.info(f"Object {i+1} first 10 lines:")
                    for line_num, line in enumerate(lines, 1):
                        app.logger.info(f"  Line {line_num}: {repr(line)}")
                    
                    # Check for different component types
                    component_types = ['VCALENDAR', 'VEVENT', 'VTODO', 'VJOURNAL', 'VFREEBUSY', 'VTIMEZONE']
                    found_components = []
                    for comp_type in component_types:
                        if f'BEGIN:{comp_type}' in raw_data:
                            found_components.append(comp_type)
                    
                    app.logger.info(f"Object {i+1} contains components: {found_components}")
                    
                    # If it contains VEVENT, try to parse it
                    if 'BEGIN:VEVENT' in raw_data:
                        app.logger.info(f"Object {i+1}: Attempting to parse VEVENT...")
                        
                        try:
                            # Try parsing with icalendar
                            from icalendar import Calendar as ICalendar
                            cal = ICalendar.from_ical(raw_data)
                            
                            vevent_count = 0
                            for component in cal.walk():
                                if component.name == "VEVENT":
                                    vevent_count += 1
                                    app.logger.info(f"    VEVENT {vevent_count} found:")
                                    
                                    # Extract basic properties
                                    summary = component.get('summary', 'No Summary')
                                    uid = component.get('uid', 'No UID')
                                    dtstart = component.get('dtstart')
                                    dtend = component.get('dtend')
                                    rrule = component.get('rrule')
                                    
                                    app.logger.info(f"      Summary: {summary}")
                                    app.logger.info(f"      UID: {uid}")
                                    app.logger.info(f"      DTSTART: {dtstart}")
                                    app.logger.info(f"      DTEND: {dtend}")
                                    app.logger.info(f"      RRULE: {rrule}")
                                    
                                    # Check for parsing issues
                                    if dtstart:
                                        try:
                                            start_dt = dtstart.dt
                                            app.logger.info(f"      Start datetime parsed: {start_dt} (type: {type(start_dt)})")
                                        except Exception as e:
                                            app.logger.error(f"      Failed to parse DTSTART: {e}")
                                    
                                    if dtend:
                                        try:
                                            end_dt = dtend.dt
                                            app.logger.info(f"      End datetime parsed: {end_dt} (type: {type(end_dt)})")
                                        except Exception as e:
                                            app.logger.error(f"      Failed to parse DTEND: {e}")
                            
                            if vevent_count == 0:
                                app.logger.warning(f"    No VEVENT components found after parsing!")
                            else:
                                app.logger.info(f"    Successfully parsed {vevent_count} VEVENT components")
                                
                        except Exception as parse_error:
                            app.logger.error(f"    iCalendar parsing failed: {parse_error}")
                            app.logger.error(f"    Raw data causing error (first 500 chars): {repr(raw_data[:500])}")
                    
                    else:
                        app.logger.info(f"Object {i+1}: Does not contain VEVENT")
                    
                except Exception as obj_error:
                    app.logger.error(f"Error analyzing object {i+1}: {obj_error}")
                    app.logger.error(f"Traceback: {traceback.format_exc()}")
            
            app.logger.info("=== END ENHANCED CALENDAR DEBUG ===")
            
        except Exception as e:
            app.logger.error(f"Error in debug_raw_calendar_data: {e}")
            app.logger.error(f"Traceback: {traceback.format_exc()}")

    def create_test_recurring_event(self):
        """Create a test recurring event for debugging"""
        if not self.calendar:
            app.logger.error("No calendar selected for test event creation")
            return False
        
        try:
            app.logger.info("Creating test recurring event...")
            
            # Create a simple weekly recurring event
            now = datetime.now()
            start_time = now.replace(hour=10, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(hours=1)
            
            # Simple weekly RRULE
            rrule = "FREQ=WEEKLY;COUNT=5"
            
            success = self.create_event(
                "Test Recurring Event",
                "This is a test event created for debugging recurring functionality",
                "Test Location",
                start_time,
                end_time,
                rrule
            )
            
            if success:
                app.logger.info("Test recurring event created successfully")
            else:
                app.logger.error("Failed to create test recurring event")
                
            return success
            
        except Exception as e:
            app.logger.error(f"Error creating test event: {e}")
            return False

    def create_event(self, summary, description, location, start_dt, end_dt, rrule=None):
        """Create a new event with optional recurrence"""
        if not self.calendar:
            app.logger.error("No calendar selected for event creation")
            return False
        
        try:
            app.logger.info(f"Creating event: {summary}")
            
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
            
            app.logger.info(f"Generated iCal data ({len(ical_data)} bytes)")
            
            self.calendar.save_event(ical_data)
            app.logger.info("Event created successfully")
            return True
                
        except Exception as e:
            app.logger.error(f"Error creating event: {e}")
            return False

    def update_event(self, event_url, summary, description, location, start_dt, end_dt, rrule=None):
        """Update an existing event"""
        try:
            app.logger.info(f"Updating event at URL: {event_url}")
            
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
            app.logger.info(f"Deleting recurring occurrence: {original_uid} on {event_date}")
            
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
                    
                    app.logger.info(f"Added EXDATE: {exception_datetime}")
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
            app.logger.info(f"Deleting future recurring events: {original_uid} from {event_date}")
            
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
                        app.logger.info(f"Modified RRULE UNTIL: {until_date}")
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
            app.logger.info(f"Deleting entire recurring series: {original_uid}")
            
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
            app.logger.info(f"Searching for event with UID: {clean_uid}")
            
            all_objects = list(self.calendar.objects())
            
            for obj in all_objects:
                try:
                    raw_data = obj.data
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode('utf-8', errors='ignore')
                    
                    if isinstance(raw_data, str) and f'UID:{clean_uid}' in raw_data:
                        app.logger.info(f"Found event with UID: {clean_uid}")
                        return obj
                        
                except Exception:
                    continue
            
            app.logger.warning(f"Event not found with UID: {clean_uid}")
            return None
            
        except Exception as e:
            app.logger.error(f"Error finding event by UID: {e}")
            return None

    def get_events(self, start_date, end_date):
        """Enhanced get_events with better debugging and error handling"""
        if not self.calendar:
            app.logger.warning("No calendar selected")
            return []
        
        try:
            app.logger.info(f"=== ENHANCED GET_EVENTS ===")
            app.logger.info(f"Getting events from {start_date} to {end_date}")
            app.logger.info(f"Calendar: {self.calendar.name}")
            
            all_objects = list(self.calendar.objects())
            app.logger.info(f"Found {len(all_objects)} objects in calendar")
            
            if len(all_objects) == 0:
                app.logger.warning("No objects found in calendar")
                return []
            
            event_list = []
            
            for i, obj in enumerate(all_objects):
                try:
                    app.logger.info(f"--- Processing object {i+1}/{len(all_objects)} ---")
                    
                    # Get raw data
                    raw_data = obj.data
                    if isinstance(raw_data, bytes):
                        raw_data = raw_data.decode('utf-8', errors='ignore')
                    
                    if not isinstance(raw_data, str):
                        app.logger.warning(f"Object {i+1}: Data is not string, skipping")
                        continue
                    
                    app.logger.info(f"Object {i+1}: Data length = {len(raw_data)}")
                    
                    if 'BEGIN:VEVENT' not in raw_data:
                        app.logger.info(f"Object {i+1}: No VEVENT found, skipping")
                        continue
                    
                    obj_url = getattr(obj, 'url', f'/event/{i}')
                    app.logger.info(f"Object {i+1}: Processing as event, URL = {obj_url}")
                    
                    # Use enhanced parsing
                    parsed_events = self._parse_event_enhanced(raw_data, str(obj_url), start_date, end_date)
                    
                    for parsed_event in parsed_events:
                        # Date range check
                        event_start = parsed_event['start']
                        event_end = parsed_event['end']
                        
                        app.logger.info(f"  Event: {parsed_event['summary']} ({event_start} to {event_end})")
                        
                        if (event_start.date() <= end_date.date() and 
                            event_end.date() >= start_date.date()):
                            event_list.append(parsed_event)
                            app.logger.info(f"  -> Added to event list")
                        else:
                            app.logger.info(f"  -> Outside date range, skipped")
                    
                except Exception as obj_error:
                    app.logger.error(f"Error processing object {i+1}: {obj_error}")
                    app.logger.error(f"Traceback: {traceback.format_exc()}")
                    continue
            
            app.logger.info(f"=== FINAL RESULT: {len(event_list)} events ===")
            for i, event in enumerate(event_list, 1):
                app.logger.info(f"  {i}. {event['summary']} - {event['start']} to {event['end']}")
            
            return event_list
            
        except Exception as e:
            app.logger.error(f"Error in enhanced_get_events: {e}")
            app.logger.error(f"Traceback: {traceback.format_exc()}")
            return []

    def _parse_event_enhanced(self, ical_text, event_url, start_date, end_date):
        """Enhanced event parsing with better error handling and debugging"""
        try:
            app.logger.info(f"=== PARSING EVENT DATA ===")
            app.logger.info(f"Event URL: {event_url}")
            app.logger.info(f"Data length: {len(ical_text)} characters")
            app.logger.info(f"Data type: {type(ical_text)}")
            
            # Ensure we have string data
            if isinstance(ical_text, bytes):
                try:
                    ical_text = ical_text.decode('utf-8')
                    app.logger.info("Converted bytes to UTF-8 string")
                except UnicodeDecodeError:
                    ical_text = ical_text.decode('latin1')
                    app.logger.info("Converted bytes to latin1 string")
            
            # Show a preview of the data
            lines = ical_text.split('\n')[:15]
            app.logger.info("First 15 lines of iCal data:")
            for i, line in enumerate(lines, 1):
                app.logger.info(f"  {i:2d}: {repr(line)}")
            
            # Check for required components
            if 'BEGIN:VCALENDAR' not in ical_text:
                app.logger.error("Missing BEGIN:VCALENDAR - not a valid iCalendar")
                return []
            
            if 'BEGIN:VEVENT' not in ical_text:
                app.logger.warning("No VEVENT found in data")
                return []
            
            # Attempt parsing
            from icalendar import Calendar as ICalendar
            
            app.logger.info("Attempting to parse with icalendar library...")
            cal = ICalendar.from_ical(ical_text)
            app.logger.info("Successfully created iCalendar object")
            
            events = []
            component_count = 0
            
            for component in cal.walk():
                component_count += 1
                app.logger.info(f"Found component {component_count}: {component.name}")
                
                if component.name == "VEVENT":
                    app.logger.info(f"Processing VEVENT component...")
                    event_data = self._parse_ical_component_enhanced(component, event_url)
                    
                    if event_data:
                        app.logger.info(f"Successfully parsed event: {event_data.get('summary', 'No title')}")
                        
                        # Handle recurring events
                        if event_data.get('rrule'):
                            app.logger.info("Event has RRULE - expanding recurring events")
                            expanded = self._expand_recurring_event(event_data, start_date, end_date)
                            events.extend(expanded)