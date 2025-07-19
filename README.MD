# CalDAV Web Client

A modern, web-based CalDAV client built with Flask that provides a calendar interface for managing events across multiple calendars. Perfect for connecting to Nextcloud, Baikal, Radicale, and other CalDAV servers.

**THIS IS 100% VIBE CODED.  DO NOT DEPLOY IN A PRODUCTION ENVIRNOMENT WITHOUT ADDITIONAL SECURITY/CODE REVIEW**
I wanted this because I'm thinking of moving away from Nextcloud but I need a good web-based CalDav frontend.  I couldn't find any I liked, so I asked Claude to make one for me.

## ✨ Features

### 🗓️ Multi-Calendar Support
- Connect to multiple CalDAV servers
- Display events from multiple calendars simultaneously
- Color-coded calendar visualization
- Toggle calendar visibility on/off

### 🎨 Customizable Interface
- Customizable calendar colors
- Week start preferences (Sunday/Monday)
- Responsive design that works on desktop and mobile
- Modern Bootstrap 5 UI

### 🖥️ Server Compatibility
- **Nextcloud** - Full support with proper URL handling
- **Baikal** (sabre.io) - Complete integration
- **Radicale** - Lightweight server support
- **Generic CalDAV** - Works with any RFC-compliant server

### 🔧 Advanced Features
- Persistent user preferences stored in SQLite
- Session management with configurable lifetime
- Health check endpoints for monitoring
- Production-ready with Gunicorn WSGI server
- Docker containerization support



## 🚀 Quick Start

### Using Docker (Recommended)

For now you'll need to build your own container.  I'll add more instructions later, but if you clone the repo you should be able to figure it out.

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `CALDAV_SERVER_URL` | Your CalDAV server base URL | - | Yes |
| `CALDAV_SERVER_TYPE` | Server type (nextcloud, baikal, radicale, generic) | `generic` | No |
| `SECRET_KEY` | Flask secret key for sessions | Generated | No |
| `DATABASE_URL` | SQLite database path | `sqlite:///data/caldav_client.db` | No |
| `SESSION_LIFETIME_DAYS` | Session expiration in days | `7` | No |
| `FLASK_ENV` | Environment (development/production) | `production` | No |
| `LOG_LEVEL` | Logging level (debug, info, warning, error) | `info` | No |
| `PORT` | Application port | `5000` | No |

### Server Type Configuration

Different CalDAV servers use different URL patterns:

- **Nextcloud:** `{server}/remote.php/dav/calendars/{username}/`
- **Baikal:** `{server}/cal.php/calendars/{username}/`
- **Radicale:** `{server}/{username}/`
- **Generic:** `{server}/calendars/{username}/`

```

## 🔗 API Endpoints

The application provides a REST API for integration:

- `GET /api/events?start=<date>&end=<date>` - Fetch events for date range
- `GET /api/settings` - Get user preferences
- `POST /api/settings` - Update user preferences
- `GET /api/calendar-selection` - Get available calendars
- `POST /api/calendar-selection` - Update selected calendars
- `GET /health` - Health check endpoint
- `GET /debug` - Debug information (development only)

### User Permissions

The container automatically adapts to the mounted volume's ownership:

```yaml
user: "1000:1000"  # Set to your user ID
```

## 🔐 Security Considerations

1. **Use App Passwords:** For Nextcloud, create dedicated app passwords instead of using your main password
2. **HTTPS Only:** Always use HTTPS in production to protect credentials
3. **Secret Key:** Generate a strong secret key for session security
4. **Regular Updates:** Keep dependencies updated for security patches


## 📋 Requirements

- **Python:** 3.8+ 
- **Dependencies:** See `requirements.txt`
- **CalDAV Server:** Any RFC 4791 compliant server
- **Browser:** Modern browser with JavaScript enabled

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [CalDAV](https://tools.ietf.org/html/rfc4791) - The standard this project implements
- [Flask](https://flask.palletsprojects.com/) - The web framework
- [FullCalendar](https://fullcalendar.io/) - The calendar JavaScript library
- [Bootstrap](https://getbootstrap.com/) - The CSS framework
- [python-caldav](https://github.com/python-caldav/caldav) - CalDAV client library
