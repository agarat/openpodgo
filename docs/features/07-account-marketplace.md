# Feature: Account & Marketplace (P-02)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_, "Marketplace & Account Options" pp. 38–40.

---

## Overview

POD Go Edit integrates with the Line 6 account for:
- Authenticating the user
- Authorizing the computer to use premium Marketplace assets
- Syncing licenses for purchased products
- Accessing the Marketplace store

## UI Components

### My Account Menu

Button in the bottom-left corner of the main window, with a state
indicator:

| State | Label | Indicator |
|-------|-------|-----------|
| Not signed in | "My Account" | No color |
| Signed in + authorized | Username | Green |
| Signed out + deauthorized | "My Account" | Red/gray |

### Dropdown menu

```
┌─────────────────────┐
│ My Account          │
├─────────────────────┤
│ Sign In...          │
│ Sign Out            │
│─────────────────────│
│ Get More Presets    │  → opens https://line6.com/marketplace/
│ Get More IRs        │  → opens https://line6.com/marketplace/
│─────────────────────│
│ Authorize Computer  │  (only visible if not authorized)
│ Deauthorize Computer│  (only visible if authorized)
│─────────────────────│
│ Manage Account      │  → opens https://line6.com/account/
└─────────────────────┘
```

### Sign In Window

Modal window with:
- Username field
- Password field
- "Sign In" button
- "Forgot my password/username" link
- "Create a Line 6 account" link

## Flow

### Sign In + Authorize
1. User clicks "Sign In", enters credentials
2. App authenticates against the Line 6 API
3. Automatically authorizes the computer
4. Menu shows the username, green indicator
5. Syncs Marketplace licenses (takes up to 5 minutes)

### Authorize / Deauthorize
- Up to 4 computers can be authorized simultaneously
- If exceeded, an existing one must be deauthorized
- On deauthorize, sign out happens automatically
- When deauthorized: premium assets cannot be imported/exported,
  but the rest of the app still works

### License Sync
- When purchasing on Marketplace, the license is deposited in the account
- On the next POD Go Edit launch (while signed in), it syncs
- Once synced, no Internet is needed to use the assets

### Premium Asset Indicators
Marketplace premium presets and IRs are shown with a gold guitar pick
badge in the list.

## Implementation considerations

### Network layer

This feature requires integration with the Line 6 API. Strategies:

1. **Simplified OAuth**: Line 6 may have a REST API for
   authentication. Requires RE or checking Line 6 developer documentation
2. **WebView**: open `https://line6.com/account/` in a QWebEngineView
   for login, and capture the token
3. **Minimal**: for now, store credentials locally and mark the
   state as "not implemented — requires Internet"

### Marketplace

- "Get More Presets" and "Get More IRs" simply open URLs in the
  system browser (QDesktopServices::openUrl)
- The actual purchase happens on the web, not in the app

### UI

- [ ] My Account button with state indicator (QPushButton with icon)
- [ ] QMenu with sign in/out, authorize, marketplace link options
- [ ] Sign In dialog (QDialog with username/password fields)
- [ ] Premium badge (guitar pick icon) on preset and IR list items
- [ ] Premium asset detection in backup/restore

### Priority

Non-critical functionality for PodGo Lab's offline use. For an MVP
it can be left as a stub. Prioritize if Marketplace functionality
is needed for testing.
