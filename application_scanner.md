I want to add a new Windows Desktop GUI feature to my existing keypad configurator program.

Feature name:
Application Library / Application Scanner

Purpose:
The desktop GUI should scan the Windows PC for installed programs, collect the information needed to launch them, store them in a local database, and allow keypad buttons to choose from that database.

Do not rewrite the existing project. Add this as a new isolated module.

Add a top menu item:
Applications

Menu entries:
- Scan Installed Applications
- Application Library
- Add Application Manually
- Rescan / Refresh Database

Application scanner must collect:
- Application name
- Executable path
- Working directory
- Launch arguments
- Icon path
- Shortcut path
- Publisher
- Version
- Install location
- Detection source
- Enabled/disabled
- Manual or auto-detected
- Last scanned time

Scan these Windows locations:
- HKLM uninstall registry
- HKCU uninstall registry
- WOW6432Node uninstall registry
- Start Menu shortcuts
- Program Files
- Program Files (x86)
- LocalAppData Programs

Skip:
- uninstallers
- setup files
- installers
- updaters
- repair tools
- crash reporters
- helpers
- services
- Windows system executables
- temp files

Scanning must never launch anything.

Application Library window:
- View apps
- Search apps
- Filter apps
- Add manually
- Edit
- Delete
- Disable
- Test launch
- Rescan

Manual app fields:
- Name
- Executable path
- Working directory
- Arguments
- Icon path
- Category
- Notes
- Enabled

Keypad Configurator integration:
When configuring a button, add action type:

Launch Application

When Launch Application is selected:
- The field below becomes a dropdown.
- The dropdown is populated from the Application Library database.
- Only enabled apps appear by default.
- Dropdown shows friendly app names.
- Searchable dropdown is preferred.

When an app is selected:
Copy the application database values directly into the button record for fast launch.

Copy:
- application_id
- application_name
- executable_path
- working_directory
- arguments
- icon_path
- run_mode
- source
- launch_source_snapshot_time

Important:
The button must launch from its copied snapshot fields, not by looking up the database every time.

Still keep application_id for future relinking or refreshing.

Button table/action fields should include:
- action_type
- application_id
- application_name
- executable_path
- working_directory
- arguments
- override_arguments
- icon_path
- run_mode
- launch_source_snapshot_time

Launch behavior:
- ESP32 only sends the button/action trigger.
- Windows desktop host launches the application.
- Do not send Windows executable paths to the ESP32.
- Use safe process launching.
- Quote executable paths safely.
- Do not build unsafe command strings.

Suggested modules/classes:
- ApplicationScanner
- ApplicationRepository
- ApplicationLauncher
- ApplicationLibraryWindow
- ApplicationMenuController
- ButtonApplicationSelector

Logging:
Log scan counts, skipped files, apps added, apps updated, missing apps, launch attempts, and launch failures.

Main rule:
This must be additive and isolated. Do not break existing keypad configuration, ESP32 communication, icons, layouts, API routes, or existing button actions.