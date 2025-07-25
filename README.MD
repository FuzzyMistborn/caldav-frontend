# CalDAV Web Client

A modern, web-based CalDAV client built with Flask that provides a calendar interface for managing events across multiple calendars. Perfect for connecting to Nextcloud, Baikal, Radicale, and other CalDAV servers.

🚨🚨🚨**THIS IS 100% VIBE/AI CODED.  DO NOT DEPLOY IN A PRODUCTION ENVIRNOMENT WITHOUT ADDITIONAL SECURITY/CODE REVIEW**🚨🚨🚨

I wanted this because I'm thinking of moving away from Nextcloud but I need a good web-based CalDav frontend.  I couldn't find any I liked, so I asked Claude to make one for me.

## 🖼️ Screenshots
![Login](https://github.com/FuzzyMistborn/caldav-frontend/blob/main/screenshots/login.png?raw=true)
![Monthly](https://github.com/FuzzyMistborn/caldav-frontend/blob/main/screenshots/monthly.png?raw=true)

Additional Screenshots [here](https://github.com/FuzzyMistborn/caldav-frontend/tree/main/screenshots)

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
- Session-based user preferences (no database required)
- Session management with configurable lifetime
- Health check endpoints for monitoring
- Production-ready with Gunicorn WSGI server
- Docker containerization support

## 🚀 Quick Start

### Using Docker (Recommended)

See the example [compose.yaml](compose.yaml).

Builds are available at `ghcr.io/fuzzymistborn/caldav-frontend`.  For now I'm not tagging releases beyond `latest` unless I start iterating further.

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `CALDAV_SERVER_URL` | Your CalDAV server base URL | - | Yes |
| `CALDAV_SERVER_TYPE` | Server type (nextcloud, baikal, radicale, generic) | `generic` | No |
| `SECRET_KEY` | Flask secret key for sessions | Generated | No |
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

## 🔗 API Endpoints

The application provides a REST API for integration:

- `GET /api/events?start=<date>&end=<date>` - Fetch events for date range
- `GET /api/settings` - Get user preferences
- `POST /api/settings` - Update user preferences
- `GET /api/calendar-selection` - Get available calendars
- `POST /api/calendar-selection` - Update selected calendars
- `GET /health` - Health check endpoint
- `GET /debug` - Debug information (development only)

## 🗄️ Data Storage

This application uses **session-only storage** - all user preferences and settings are stored in Flask sessions and persist only for the duration of the session (configurable via `SESSION_LIFETIME_DAYS`).

## 🔐 Security Considerations

1. **Use App Passwords:** For Nextcloud, create dedicated app passwords instead of using your main password
2. **HTTPS Only:** Always use HTTPS in production to protect credentials
3. **Secret Key:** Generate a strong secret key for session security
4. **Session Lifetime:** Configure appropriate session lifetime for your security needs

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [CalDAV](https://tools.ietf.org/html/rfc4791) - The standard this project implements
- [Flask](https://flask.palletsprojects.com/) - The web framework
- [FullCalendar](https://fullcalendar.io/) - The calendar JavaScript library
- [Bootstrap](https://getbootstrap.com/) - The CSS framework
- [python-caldav](https://github.com/python-caldav/caldav) - CalDAV client library