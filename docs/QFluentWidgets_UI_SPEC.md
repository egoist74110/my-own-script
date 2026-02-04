# QFluentWidgets UI Spec (Launcher/Toolbox)

> Source: User requirements (2026-02-04). Keep as implementation checklist.

## Style
- QFluentWidgets look & feel
- **Dark theme preferred**, but **toggleable light theme**
- Overall vibe: **game launcher / toolbox**

## Layout
- **Top bar**: Title + Search box + top-right Settings / Account
- **Left nav**: Categories / Favorites / Recent
- **Main area**: Card grid, responsive **3–4 columns**
- **Right drawer / details panel**: On tool selection show:
  - Description
  - Parameter form
  - Recent runs
  - Logs
- **Bottom status bar**:
  - Online/offline
  - Queue
  - Current task
  - Version

## Card spec
- 48px icon
- Title
- 1-line description
- Top-right status dot: idle / running / failed
- Primary button: Run
- Secondary button: Configure
- Card radius: **14**
- Card padding: **16**
- Card spacing: **12**

## Interaction spec
- Run requires **2-step confirmation** (option to disable)
- Any slow operation must show:
  - Loading state
  - Progress
  - Toast
- Error display:
  - Card status
  - Details drawer logs
